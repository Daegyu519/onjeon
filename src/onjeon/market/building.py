"""등기부 건물용도 문자열 → 실거래가 유형(apt/rh/offi)."""

from __future__ import annotations

# 순서 중요: '오피스텔'을 먼저 판정(아파트 오인 방지)
_RULES = [
    ("오피스텔", "offi"),
    ("아파트", "apt"),
    ("연립", "rh"),
    ("다세대", "rh"),
]


def building_type_for_use(use: str) -> str:
    """부분 문자열 매칭으로 유형 분류. 미분류는 ValueError."""
    for needle, btype in _RULES:
        if needle in use:
            return btype
    raise ValueError(f"실거래가 유형 미분류 건물용도: {use!r}")
