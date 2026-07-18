"""L2 리스크 모델 — 로지스틱 회귀 + 계수 기반 기여도 설명.

설명 가능성이 성능보다 우선 (docs/architecture.md). shap은 환경 문제로
optional — 기여도 = coef × (x − 학습평균) 폴백은 로지스틱 회귀에서
logit을 정확히 분해하므로 SHAP(linear)과 동일한 구조를 보여준다.
"""

from __future__ import annotations

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
