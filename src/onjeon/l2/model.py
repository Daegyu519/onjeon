"""L2 리스크 모델 — 로지스틱 회귀 + 계수 기반 기여도 설명.

설명 가능성이 성능보다 우선 (docs/architecture.md). shap은 환경 문제로
optional — 기여도 = coef × (x − 학습평균) 폴백은 로지스틱 회귀에서
logit을 정확히 분해하므로 SHAP(linear)과 동일한 구조를 보여준다.

**추론은 stdlib만 쓴다.** numpy·pandas·scikit-learn은 학습(train/train_xgb)과
XGBoost 백엔드에서만 필요하므로 함수 안에서 import한다. 배포 런타임
(requirements-api.txt)에는 그 셋이 없어서(커밋 7485de9, 의존성 11배 축소)
최상단 import면 api.main이 컨테이너에서 죽는다. 로지스틱 회귀의 추론은
시그모이드 한 줄이라 계수만 있으면 되고, 학습된 계수는
scripts/dump_risk_model.py가 rules/risk_model_*.json으로 덤프한다.
tests/test_risk_wiring.py가 최상단 import를 정적으로 검사한다.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from onjeon.rules_io import load_rules

# 피처 순서와 데이터 한계 문구는 여기(추론 쪽)가 소유한다. synth가 이걸 재수출한다 —
# 반대로 두면 stdlib 경계가 깨진다(synth는 numpy·pandas를 최상단에서 쓴다).
FEATURES = ["jeonse_ratio", "lien_ratio", "is_villa", "auction_rate"]
DATA_NOTE = "합성 데이터 — 구조 시연 목적, 기저율은 실 HUG 사고율 2.2%(2025-08)에 앵커"


@dataclass
class RiskModel:
    coef: dict[str, float]
    intercept: float
    feature_means: dict[str, float]
    data_note: str = DATA_NOTE
    # 시점별 계수 [{coef, intercept}, ...]. 공개 통계 보정 시 채워지며 P의 밴드를 만든다.
    # 보증사고율은 시점에 크게 흔들려서(전국 2023-05 8.1% → 2026-06 1.0%) 점추정 하나만
    # 내면 거짓 정밀도다. 비어 있으면 밴드 없이 점추정만 나온다.
    periods: list[dict] = field(default_factory=list)

    @property
    def base_logit(self) -> float:
        return self.intercept + sum(self.coef[f] * self.feature_means[f] for f in FEATURES)

    def _logit(self, x: dict) -> float:
        return self.intercept + sum(self.coef[f] * x[f] for f in FEATURES)

    def predict_proba(self, x: dict) -> float:
        """P(사고) — 매물 피처 dict → 확률.

        시간 단위: **연간** 확률이다. 절편이 HUG 전세보증금반환보증 연 사고율
        2.2%(2025-08)에 앵커돼 있다(synth.TRUE_INTERCEPT). engine.expected_loss가
        이 값을 그대로 곱해 연간 기대손실을 내고 annual_cost_jeonse가 연비용에 더한다 —
        계약기간(2년) 확률로 오해해 ÷2 하면 헤드라인이 절반으로 틀린다.
        """
        return 1.0 / (1.0 + math.exp(-self._logit(x)))

    def predict_proba_band(self, x: dict) -> tuple[float, float]:
        """시점별 계수로 P의 (하한, 상한). 시점 데이터가 없으면 점추정을 양쪽에 준다.

        밴드는 통계적 신뢰구간이 아니라 **관측된 시점 변동**이다. 보증사고율이
        해에 따라 8배까지 움직였으므로, 어느 시점 기준이냐에 따라 이만큼 달라진다는 뜻.
        """
        if not self.periods:
            p = self.predict_proba(x)
            return p, p
        ps = []
        for period in self.periods:
            coef, intercept = period["coef"], period["intercept"]
            z = intercept + sum(coef[f] * x[f] for f in FEATURES)
            ps.append(1.0 / (1.0 + math.exp(-z)))
        return min(ps), max(ps)

    def explain(self, x: dict) -> dict:
        """피처별 logit 기여도 분해. base_logit + Σ기여도 = logit(p)."""
        contributions = [
            (f, float(self.coef[f] * (x[f] - self.feature_means[f]))) for f in FEATURES
        ]
        return {
            "p": self.predict_proba(x),
            "base_logit": float(self.base_logit),
            "contributions": contributions,
            "data_note": self.data_note,
        }


def load_risk_model() -> RiskModel:
    """학습된 계수를 룰 JSON에서 읽어 추론 전용 모델을 만든다 (stdlib만).

    배포 런타임에는 scikit-learn이 없다(requirements-api.txt). 로지스틱 회귀의 추론은
    시그모이드 한 줄이므로 계수·절편·학습평균만 있으면 된다. 학습은 오프라인에서
    scripts/dump_risk_model.py가 하고 결과를 rules/risk_model_*.json에 남긴다.
    """
    rule = load_rules("risk_model")
    return RiskModel(
        coef={f: float(rule["coef"][f]) for f in FEATURES},
        intercept=float(rule["intercept"]),
        feature_means={f: float(rule["feature_means"][f]) for f in FEATURES},
        # 폴백으로 DATA_NOTE를 쓰면 안 된다 — 그건 synth 학습 모델의 출처이고
        # (dump_risk_model.py가 그 값을 쓴다), 배포에 실리는 룰은 공개통계 보정이다.
        # 룰에 출처가 없으면 "합성 데이터"라고 단정하는 대신 모른다고 말한다(원칙 2·5).
        data_note=rule.get("data_note") or "출처 미상 — 룰 JSON에 data_note가 없습니다",
        periods=rule.get("periods", []),
    )


def train(df) -> RiskModel:
    """합성(또는 실) 데이터로 로지스틱 회귀 학습. scikit-learn 필요(개발 환경 전용)."""
    from sklearn.linear_model import LogisticRegression

    X = df[FEATURES]
    y = df["accident"]
    clf = LogisticRegression(max_iter=1000)
    clf.fit(X, y)
    return RiskModel(
        coef={f: float(c) for f, c in zip(FEATURES, clf.coef_[0])},
        intercept=float(clf.intercept_[0]),
        feature_means={f: float(X[f].mean()) for f in FEATURES},
    )


@dataclass
class XGBRiskModel:
    """XGBoost 스왑 백엔드 — RiskModel과 동일 인터페이스(덕타이핑).

    기여도는 shap 패키지 없이 XGBoost 내장 TreeSHAP(pred_contribs=True)을 쓴다.
    pred_contribs는 margin(logit) 단위이며 마지막 열이 bias(base) —
    base + Σ기여도 = logit(p) 불변식이 LR 백엔드와 동일하게 성립한다.
    실데이터(KB 결합) 시점의 기본 백엔드 후보 — 합성 데이터 단계에서는 LR가 기본.
    """

    booster: object  # xgboost.Booster (lazy import 유지를 위해 타입은 느슨하게)
    data_note: str = DATA_NOTE + " · XGBoost 백엔드"

    def _dmatrix(self, x: dict):
        import numpy as np
        import xgboost as xgb

        row = np.array([[float(x[f]) for f in FEATURES]])
        return xgb.DMatrix(row, feature_names=FEATURES)

    def predict_proba(self, x: dict) -> float:
        """P(사고) — 매물 피처 dict → 확률."""
        return float(self.booster.predict(self._dmatrix(x))[0])

    def explain(self, x: dict) -> dict:
        """피처별 TreeSHAP 기여도 분해. base_logit + Σ기여도 = logit(p)."""
        contribs = self.booster.predict(self._dmatrix(x), pred_contribs=True)[0]
        return {
            "p": self.predict_proba(x),
            "base_logit": float(contribs[-1]),
            "contributions": [(f, float(c)) for f, c in zip(FEATURES, contribs[:-1])],
            "data_note": self.data_note,
        }


def train_xgb(df, *, num_boost_round: int = 200, **params) -> XGBRiskModel:
    """XGBoost 이진 분류기 학습 — 결정론(seed 고정), CPU."""
    import xgboost as xgb

    dtrain = xgb.DMatrix(
        df[FEATURES].values, label=df["accident"].values, feature_names=FEATURES
    )
    merged = {
        "objective": "binary:logistic",
        "max_depth": 3,
        "eta": 0.15,
        "subsample": 0.9,
        "seed": 42,
        "nthread": 2,
        **params,
    }
    booster = xgb.train(merged, dtrain, num_boost_round=num_boost_round)
    return XGBRiskModel(booster=booster)


def train_risk_model(df, *, backend: str | None = None):
    """L2 백엔드 팩토리 — 기본 'lr'(합성 데이터 단계 정직성), 'xgb'로 전환 가능.

    우선순위: 명시 인자 > 환경변수 ONJEON_L2_BACKEND > 'lr'.
    """
    resolved = (backend or os.environ.get("ONJEON_L2_BACKEND", "lr")).lower()
    if resolved == "lr":
        return train(df)
    if resolved == "xgb":
        return train_xgb(df)
    raise ValueError(f"알 수 없는 L2 백엔드: {resolved!r} — 'lr' 또는 'xgb'")
