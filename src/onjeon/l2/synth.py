"""L2 합성 데이터 생성기 — 구조 시연 목적 (성능 주장 아님, CLAUDE.md 원칙 5).

진짜 로지스틱 모형에서 라벨을 뽑아, 학습된 모델이 '설명 가능한 구조'를
재현하는지 보여준다. 실데이터(HUG 보증사고율 [확인]) 결합은 고도화 로드맵.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ["jeonse_ratio", "lien_ratio", "is_villa", "auction_rate"]

# 데이터 생성용 진짜 계수 — 전세가율·근저당비율↑ 위험↑, 낙찰가율↑ 위험↓
TRUE_COEF = {"jeonse_ratio": 5.0, "lien_ratio": 3.0, "is_villa": 0.8, "auction_rate": -2.0}
TRUE_INTERCEPT = -5.5

DATA_NOTE = "합성 데이터 — 구조 시연 목적 (KB 실데이터 결합 시 고도화)"


def generate(n: int = 1500, seed: int = 42) -> pd.DataFrame:
    """합성 매물 n건 생성. 같은 seed면 항상 같은 결과."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            "jeonse_ratio": rng.uniform(0.2, 1.0, n),
            "lien_ratio": rng.uniform(0.0, 0.8, n),
            "is_villa": rng.integers(0, 2, n),
            "auction_rate": rng.uniform(0.6, 0.95, n),
        }
    )
    logit = TRUE_INTERCEPT + sum(TRUE_COEF[f] * df[f] for f in FEATURES)
    p = 1.0 / (1.0 + np.exp(-logit))
    df["accident"] = (rng.uniform(0, 1, n) < p).astype(int)
    return df
