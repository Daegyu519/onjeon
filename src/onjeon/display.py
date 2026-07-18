"""표시 계층 헬퍼 — 만원 변환·인용 라벨.

CLAUDE.md 컨벤션: 금액은 원(₩) 정수로 흐르고, 만원 변환은 여기(표시 계층)에서만.
계산·판정 로직 금지.
"""

from __future__ import annotations


def krw_man(x: int | float) -> str:
    """원 → 만원 문자열 (예: 72_000_000 → '7,200만원')."""
    return f"{x / 10_000:,.0f}만원"


def citation_label(citation: dict) -> str:
    """등기부 인용 한 줄 라벨. 갑구(압류 등)는 금액이 없으므로 None 안전.

    말소된 등기는 위험 계산(선순위 합산)에서 제외되지만, 인용 목록에는
    '말소' 표시와 함께 남긴다 — 원문에 있는 것은 숨기지 않는다.
    """
    amount = f" {krw_man(citation['amount_krw'])}" if citation.get("amount_krw") else ""
    cancelled = " (말소)" if citation.get("cancelled") else ""
    return (
        f"{citation['type']}{amount}{cancelled} — "
        f"등기부 {citation['section']} {citation['entry_no']}번 · p.{citation['page']}"
    )
