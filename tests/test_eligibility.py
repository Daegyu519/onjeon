"""L3 자격 판정 룰엔진 테스트 — 미자격 반증(gap·clause) 포함."""

from onjeon.l3.eligibility import check_criterion, evaluate

PASS_RULE = {
    "rule_id": "youth-jeonse-loan-2026-07",
    "product_name": "청년전용 버팀목전세자금대출",
    "version": "2026-07 기준",
    "criteria": [
        {"field": "age", "op": "<=", "value": 34, "clause": "대출대상 제1호"},
        {"field": "annual_income_krw", "op": "<=", "value": 50_000_000, "clause": "대출대상 제2호"},
    ],
    "alternatives": [],
}

FAIL_RULE = {
    "rule_id": "sme-youth-jeonse-2026-07",
    "product_name": "중소기업취업청년 전월세보증금대출",
    "version": "2026-07 기준",
    "criteria": [
        {"field": "age", "op": "<=", "value": 34, "clause": "대출대상 제1호"},
        {"field": "annual_income_krw", "op": "<=", "value": 35_000_000, "clause": "대출대상 제2호"},
    ],
    "alternatives": ["youth-jeonse-loan-2026-07"],
}

USER = {"age": 26, "annual_income_krw": 36_000_000}


class TestCheckCriterion:
    def test_le(self):
        assert check_criterion(26, "<=", 34) is True
        assert check_criterion(35, "<=", 34) is False

    def test_le_boundary_inclusive(self):
        assert check_criterion(34, "<=", 34) is True

    def test_ge(self):
        assert check_criterion(5, ">=", 3) is True
        assert check_criterion(2, ">=", 3) is False

    def test_eq(self):
        assert check_criterion("무주택", "==", "무주택") is True

    def test_in(self):
        assert check_criterion("서울", "in", ["서울", "경기"]) is True
        assert check_criterion("부산", "in", ["서울", "경기"]) is False

    def test_unknown_op_raises(self):
        import pytest

        with pytest.raises(ValueError):
            check_criterion(1, "~", 2)


class TestEvaluate:
    def test_eligible(self):
        result = evaluate(USER, PASS_RULE)
        assert result["eligible"] is True
        assert result["failed"] == []
        assert result["version"] == "2026-07 기준"

    def test_ineligible_with_gap_and_clause(self):
        result = evaluate(USER, FAIL_RULE)
        assert result["eligible"] is False
        [failure] = result["failed"]
        assert failure["field"] == "annual_income_krw"
        assert failure["gap"] == 1_000_000  # 얼마 초과했는지 — 미자격 반증
        assert failure["clause"] == "대출대상 제2호"
        assert failure["limit"] == 35_000_000
        assert failure["actual"] == 36_000_000

    def test_ineligible_suggests_alternatives(self):
        result = evaluate(USER, FAIL_RULE)
        assert result["alternatives"] == ["youth-jeonse-loan-2026-07"]

    def test_missing_user_field_fails_that_criterion(self):
        result = evaluate({"age": 26}, FAIL_RULE)
        assert result["eligible"] is False
        fields = [f["field"] for f in result["failed"]]
        assert "annual_income_krw" in fields


class TestRecommendCarriesRuleMetadata:
    """recommend()가 룰 메타데이터를 빠뜨리면 호출측에서 조용히 빈값이 된다.

    실제로 두 번 당했다: applies_to 누락 → 용도 필터가 빈 목록을 받아 정책 혜택이
    사라지고 전 구간 시장금리로 계산됨. source 누락 → 화면 인용의 조항이 빔.
    둘 다 예외가 아니라 '그럴듯한 오답'으로 나타나서 눈에 안 띄었다.
    """

    def test_carries_every_field_decision_layer_reads(self):
        from onjeon.l3.recommend import recommend
        from onjeon.rules_io import load_products

        products = load_products()
        user = {
            "age": 27, "assets_krw": 20_000_000, "is_homeless": True,
            "is_household_head": True, "works_at_sme": True,
            "annual_income_krw": 33_600_000, "deposit_krw": 100_000_000,
        }
        out = recommend(user, products)
        assert out["eligible"], "이 프로필이면 자격 상품이 하나는 나와야 한다"
        for entry in out["eligible"] + out["ineligible"]:
            for field in ("terms", "product_type", "applies_to", "source"):
                assert field in entry, f"{entry['rule_id']}에 {field} 누락"

    def test_source_has_clause_refs_for_citation(self):
        """모든 출력에 원문 출처 (CLAUDE.md 원칙 2) — 조항이 비면 인용이 껍데기다."""
        from onjeon.l3.recommend import recommend
        from onjeon.rules_io import load_products

        out = recommend(
            {"age": 27, "assets_krw": 20_000_000, "is_homeless": True,
             "is_household_head": True, "works_at_sme": True,
             "annual_income_krw": 33_600_000, "deposit_krw": 100_000_000},
            load_products(),
        )
        for entry in out["eligible"]:
            assert entry["source"].get("clause_refs"), f"{entry['rule_id']} 조항 없음"
            assert entry["source"].get("url"), f"{entry['rule_id']} 원문 링크 없음"
