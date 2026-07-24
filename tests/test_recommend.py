"""청년 금융지원 recommend — 자격 랭킹·미자격 반증·staleness 필터 회귀 테스트."""
from onjeon.l3.recommend import recommend

RULE_SME = {
    "rule_id": "sme", "product_name": "중기청", "status": "active", "product_type": "loan",
    "terms": {"interest_rate": 0.012, "limit_krw": 100_000_000},
    "criteria": [{"field": "annual_income_krw", "op": "<=", "value": 35_000_000, "clause": "소득"}],
}
RULE_BTM = {
    "rule_id": "btm", "product_name": "버팀목", "status": "active", "product_type": "loan",
    "terms": {"interest_rate": None, "limit_krw": 200_000_000},
    "criteria": [{"field": "annual_income_krw", "op": "<=", "value": 50_000_000, "clause": "소득"}],
}
RULE_DEAD = {
    "rule_id": "dead", "product_name": "종료상품", "status": "discontinued", "product_type": "loan",
    "terms": {}, "criteria": [{"field": "age", "op": "<=", "value": 34, "clause": "나이"}],
}


def test_eligible_ranked_by_rate_ascending():
    r = recommend({"annual_income_krw": 30_000_000}, [RULE_BTM, RULE_SME])
    # 금리 낮은 중기청(1.2%)이 앞, 금리 없는 버팀목(null→후순위) 뒤
    assert [e["rule_id"] for e in r["eligible"]] == ["sme", "btm"]


def test_ineligible_carries_gap():
    r = recommend({"annual_income_krw": 60_000_000}, [RULE_SME, RULE_BTM])
    assert not r["eligible"]
    failed = r["ineligible"][0]["failed"]
    # 소득 60M - 상한 35M = 25M 초과
    assert any(f["field"] == "annual_income_krw" and f["gap"] == 25_000_000 for f in failed)


def test_discontinued_product_excluded():
    r = recommend({"age": 27, "annual_income_krw": 30_000_000}, [RULE_SME, RULE_DEAD])
    all_ids = [e["rule_id"] for e in r["eligible"] + r["ineligible"]]
    assert "dead" not in all_ids  # 종료 상품은 추천에서 제외
