"""L2 리스크 모델 — 로지스틱 회귀 + 계수 기반 기여도 설명.

설명 가능성이 성능보다 우선 (docs/architecture.md). shap은 환경 문제로
optional — 기여도 = coef × (x − 학습평균) 폴백은 로지스틱 회귀에서
logit을 정확히 분해하므로 SHAP(linear)과 동일한 구조를 보여준다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from onjeon.l2.synth import DATA_NOTE, FEATURES


@dataclass
class RiskModel:
    coef: dict[str, float]
    intercept: float
    feature_means: dict[str, float]
    data_note: str = DATA_NOTE

    @property
    def base_logit(self) -> float:
        return self.intercept + sum(self.coef[f] * self.feature_means[f] for f in FEATURES)

    def _logit(self, x: dict) -> float:
        return self.intercept + sum(self.coef[f] * x[f] for f in FEATURES)

    def predict_proba(self, x: dict) -> float:
        """P(사고) — 매물 피처 dict → 확률."""
        return float(1.0 / (1.0 + np.exp(-self._logit(x))))

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


def train(df: pd.DataFrame) -> RiskModel:
    """합성(또는 실) 데이터로 로지스틱 회귀 학습."""
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


def train_xgb(df: pd.DataFrame, *, num_boost_round: int = 200, **params) -> XGBRiskModel:
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


def train_risk_model(df: pd.DataFrame, *, backend: str | None = None):
    """L2 백엔드 팩토리 — 기본 'lr'(합성 데이터 단계 정직성), 'xgb'로 전환 가능.

    우선순위: 명시 인자 > 환경변수 ONJEON_L2_BACKEND > 'lr'.
    """
    resolved = (backend or os.environ.get("ONJEON_L2_BACKEND", "lr")).lower()
    if resolved == "lr":
        return train(df)
    if resolved == "xgb":
        return train_xgb(df)
    raise ValueError(f"알 수 없는 L2 백엔드: {resolved!r} — 'lr' 또는 'xgb'")
