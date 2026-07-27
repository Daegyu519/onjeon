"""청년 금융지원 추천 — 자격 랭킹 + 미자격 반증. LLM 없음(결정론).

각 상품을 eligibility.evaluate로 판정한다. 자격 상품은 금리 오름차순·한도 내림차순
으로 랭킹하고, 미자격 상품은 어느 조항을 얼마 초과했는지(failed의 gap·clause)와
차선(alternatives)을 남긴다. 금리·한도는 룰의 구조화 필드 terms에서 읽는다.
"""

from __future__ import annotations

from onjeon.l3.eligibility import evaluate


# 판정 결과에 함께 실어보낼 룰 필드 → 없을 때의 기본값.
# terms: 금리·한도·지원금 / product_type: loan|subsidy|savings
# applies_to: jeonse|wolse|buy 용도 / source: 인용할 조항·원문 링크
_CARRIED = {"terms": {}, "product_type": "loan", "applies_to": [], "source": {}}


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
        # 룰의 메타데이터를 결과에 실어보낸다. 여기 빠진 필드는 호출측에서 조용히
        # None/빈값이 되고, 예외가 아니라 "혜택이 사라지거나 인용이 비는" 형태로
        # 나타나서 눈에 안 띈다(applies_to·source 둘 다 실제로 이렇게 빠뜨렸다).
        # 룰에 호출측이 읽을 필드를 추가하면 여기와 tests/test_eligibility.py의
        # TestRecommendCarriesRuleMetadata.test_carries_every_field_decision_layer_reads
        # 를 같이 갱신한다.
        for key in _CARRIED:
            result[key] = product.get(key, _CARRIED[key])
        (ranked if result["eligible"] else rejected).append(result)
    ranked.sort(key=_rank_key)
    return {"eligible": ranked, "ineligible": rejected}
