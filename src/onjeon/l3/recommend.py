"""청년 금융지원 추천 — 자격 랭킹 + 미자격 반증. LLM 없음(결정론).

각 상품을 eligibility.evaluate로 판정한다. 자격 상품은 금리 오름차순·한도 내림차순
으로 랭킹하고, 미자격 상품은 어느 조항을 얼마 초과했는지(failed의 gap·clause)와
차선(alternatives)을 남긴다. 금리·한도는 룰의 구조화 필드 terms에서 읽는다.
"""

from __future__ import annotations

from onjeon.l3.eligibility import evaluate


def _rank_key(result: dict):
    terms = result["terms"]
    rate = terms.get("interest_rate")
    return (rate if rate is not None else 1.0, -(terms.get("limit_krw") or 0))


def recommend(profile: dict, products: list[dict]) -> dict:
    """profile을 각 상품 룰에 대조 → {eligible:[금리↑·한도↓ 랭킹], ineligible:[반증]}."""
    ranked, rejected = [], []
    for product in products:
        if product.get("status") == "discontinued":
            continue  # 종료 상품은 추천하지 않는다(staleness 방어)
        result = evaluate(profile, product)
        result["terms"] = product.get("terms", {})
        result["product_type"] = product.get("product_type", "loan")
        (ranked if result["eligible"] else rejected).append(result)
    ranked.sort(key=_rank_key)
    return {"eligible": ranked, "ineligible": rejected}
