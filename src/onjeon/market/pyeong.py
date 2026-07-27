"""평당가 계산 — 원(₩) 정수. 만원 변환은 표시 계층 몫."""

from __future__ import annotations

PYEONG_PER_M2 = 3.3058  # 1평 = 3.3058 m²


def price_per_pyeong(amount_krw: int, area_m2: float) -> int:
    """거래금액(원)·전용면적(m²) → 평당가(원/평) 정수. 면적 0 이하면 ValueError."""
    if area_m2 <= 0:
        raise ValueError(f"전용면적이 0 이하: {area_m2!r}")
    pyeong = area_m2 / PYEONG_PER_M2
    return round(amount_krw / pyeong)


def estimate_market_price_krw(*, pyeong_price_manwon: float, area_m2: float) -> int:
    """평당가(**만원**)·전용면적(m²) → 시세(원) 정수. 면적 0 이하면 ValueError.

    단위 변환이 이 함수 한 곳에만 있다. market.trends가 평당가를 만원으로 반환하므로
    (trends.py의 `// 10_000`) 호출측에서 ×10000을 빼먹기 쉽고, 빼먹으면 예외 없이
    시세가 1만분의 1이 된다 → engine.lgd의 회수 예상액이 0이 되어 LGD가 1.0으로
    고정되고 E[Loss]가 5.8배로 튄다(실측). 그래서 단위를 인자 이름에 박아둔다.
    """
    if area_m2 <= 0:
        raise ValueError(f"전용면적이 0 이하: {area_m2!r}")
    return round(pyeong_price_manwon * 10_000 * (area_m2 / PYEONG_PER_M2))
