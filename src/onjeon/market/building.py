"""등기부 건물용도 문자열 → 실거래가 유형(apt/rh/offi)."""

from __future__ import annotations

# 순서 중요: '오피스텔'을 먼저 판정(아파트 오인 방지)
_RULES = [
    ("오피스텔", "offi"),
    ("아파트", "apt"),
    ("연립", "rh"),
    ("다세대", "rh"),  # 다세대(구분소유 빌라)는 rh — '다가구'보다 먼저 매칭
    ("다가구", "sh"),
    ("단독", "sh"),
    ("다중", "sh"),  # 단독/다가구/다중(원룸·투룸)
]


def building_type_for_use(use: str) -> str:
    """부분 문자열 매칭으로 유형 분류. 미분류는 ValueError."""
    for needle, btype in _RULES:
        if needle in use:
            return btype
    raise ValueError(f"실거래가 유형 미분류 건물용도: {use!r}")


# 실거래가 유형 코드 → 낙찰가율 룰 표의 유형(한글). 단독·다가구(sh)는 표에 없어
# '기타'로 보내고, engine.auction_rate가 거기서 가장 보수적인 값으로 떨어뜨린다.
_AUCTION_TYPE = {"apt": "아파트", "rh": "빌라", "offi": "오피스텔", "sh": "기타"}


def auction_type(code_or_name: str) -> str:
    """유형 코드(apt/rh/offi/sh) → 낙찰가율 표 유형(한글). 이미 한글이면 그대로 통과."""
    return _AUCTION_TYPE.get(code_or_name, code_or_name)
