"""L2 합성 데이터 생성기 — 구조 시연 목적 (성능 주장 아님, CLAUDE.md 원칙 5).

진짜 로지스틱 모형에서 라벨을 뽑아, 학습된 모델이 '설명 가능한 구조'를
재현하는지 보여준다. 실데이터(KB 내부 전세대출·보증사고) 결합은 고도화 로드맵.

기저 사고율 앵커: 절편을 실제 HUG 공개 통계에 정렬 — 전세보증금반환보증
사고율 2.2%(2025-08 기준, 뉴시스/MBC 보도)에 합성 모집단 평균이 ~2.1%로
수렴하도록 절편 -7.5 설정. 임의값이 아니라 '실 공개 통계 앵커 + 합성 분포'.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURES = ["jeonse_ratio", "lien_ratio", "is_villa", "auction_rate"]

# 데이터 생성용 진짜 계수 — 전세가율·근저당비율↑ 위험↑, 낙찰가율↑ 위험↓
TRUE_COEF = {"jeonse_ratio": 5.0, "lien_ratio": 3.0, "is_villa": 0.8, "auction_rate": -2.0}
# 절편: 실 HUG 사고율 2.2%(2025-08)에 모집단 평균 정렬 (측정: 평균 2.1%)
TRUE_INTERCEPT = -7.5

# 실 공개 통계 기저율 (참조·문서화용)
HUG_BASE_ACCIDENT_RATE = 0.022  # 전세보증금반환보증 사고율, 2025-08 기준 [출처 확인됨]

DATA_NOTE = "합성 데이터 — 구조 시연 목적, 기저율은 실 HUG 사고율 2.2%(2025-08)에 앵커"


def generate(n: int = 1500, seed: int = 42) -> pd.DataFrame:
    """합성 매물 n건 생성. 같은 seed면 항상 같은 결과."""
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        {
            # 하한 0.0 — 월세 매물(보증금/시세 ≈ 0.05)도 학습 분포 안에 들어오도록
            "jeonse_ratio": rng.uniform(0.0, 1.0, n),
            "lien_ratio": rng.uniform(0.0, 0.8, n),
            "is_villa": rng.integers(0, 2, n),
            "auction_rate": rng.uniform(0.6, 0.95, n),
        }
    )
    logit = TRUE_INTERCEPT + sum(TRUE_COEF[f] * df[f] for f in FEATURES)
    p = 1.0 / (1.0 + np.exp(-logit))
    df["accident"] = (rng.uniform(0, 1, n) < p).astype(int)
    return df
