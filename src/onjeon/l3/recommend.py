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
# channels: 어디서 신청하나(은행·창구) / provider: 취급 주체
# is_policy_product: 정책 기금상품인가 은행 자체 상품인가 — 화면이 둘을 구분해 표기한다
_CARRIED = {
    "terms": {}, "product_type": "loan", "applies_to": [], "source": {},
    "channels": [], "provider": None, "is_policy_product": False,
}


def _rank_key(result: dict):
    """금리 오름차순 → 한도 내림차순. **싼 것이 먼저다.**

    금리가 없는 상품(interest_rate=null)은 1.0으로 취급해 맨 뒤로 간다.
    은행 자체 변동금리 상품(COFIX+가산)이 여기 해당한다 — 금리를 사전에 확정할 수
    없으니 확정 금리를 가진 정책상품보다 앞에 세울 근거가 없다. 결과적으로
    "정책상품이 먼저, 은행 상품은 그 다음"이 자연히 지켜진다. 이 순서가 뒤집히면
    제품이 자사 상품을 밀어준 셈이 되어 숫자의 신뢰가 통째로 무너진다.
    """
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

    # 미자격 상품의 alternatives는 rule_id 목록이라 화면이 그대로 쓸 수 없다.
    # "당신은 소득 초과로 X가 안 됩니다" 뒤에 "→ 대신 Y는 됩니다"를 붙이려면
    # 이름과 자격 여부가 필요하다. 자격이 실제로 되는 대안만 남긴다 —
    # 안 되는 걸 대안이라고 내밀면 반증이 두 번 실패하는 셈이다.
    by_id = {r["rule_id"]: r for r in ranked + rejected}
    for result in rejected:
        result["alternatives"] = [
            {
                "rule_id": alt_id,
                "product_name": by_id[alt_id]["product_name"],
                "provider": by_id[alt_id]["provider"],
                "is_policy_product": by_id[alt_id]["is_policy_product"],
                "rate_display": by_id[alt_id]["terms"].get("rate_display"),
                "interest_rate": by_id[alt_id]["terms"].get("interest_rate"),
                "limit_krw": by_id[alt_id]["terms"].get("limit_krw"),
                "channels": by_id[alt_id]["channels"],
            }
            for alt_id in result.get("alternatives") or []
            if alt_id in by_id and by_id[alt_id]["eligible"]
        ]
    return {"eligible": ranked, "ineligible": rejected}
