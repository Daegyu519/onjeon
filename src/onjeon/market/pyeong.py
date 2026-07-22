"""평당가 계산 — 원(₩) 정수. 만원 변환은 표시 계층 몫."""

from __future__ import annotations

PYEONG_PER_M2 = 3.3058  # 1평 = 3.3058 m²


def price_per_pyeong(amount_krw: int, area_m2: float) -> int:
    """거래금액(원)·전용면적(m²) → 평당가(원/평) 정수. 면적 0 이하면 ValueError."""
    if area_m2 <= 0:
        raise ValueError(f"전용면적이 0 이하: {area_m2!r}")
    pyeong = area_m2 / PYEONG_PER_M2
    return round(amount_krw / pyeong)
