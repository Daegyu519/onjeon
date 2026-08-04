"""배포 의사결정 경로 테스트 — compare_jeonse_wolse. 모든 금액은 원(₩) 정수.

이 경로는 한동안 테스트가 0건이었고, 그 사이 결함 4건이 헤드라인 숫자를 틀리게
만들었다 — 전부 예외 없이 그럴듯한 값으로 나오는 종류였다.

룰 드리프트에 영향받지 않도록 로직 테스트는 인라인 최소 룰을 주입한다.
실제 룰 파일에 대한 보증은 TestRealRules에서 따로 확인한다.
"""

import pytest

from onjeon.decision import compare_jeonse_wolse
from onjeon.l3.engine import split_funding_policy
from onjeon.rules_io import load_products

TAX_RULES = {
    "version": "test",
    "wolse_tax_credit": {
        "clause": "조특법 §95-2",
        "brackets": [
            {"max_income_krw": 55_000_000, "rate": 0.17},
            {"max_income_krw": 80_000_000, "rate": 0.15},
        ],
        "annual_rent_cap_krw": 10_000_000,
    },
}

MARKET = {
    "version": "test",
    "loan_rate_jeonse": 0.035,  # 시장금리
    "loan_rate_buy": 0.045,
    "opportunity_rate": 0.04,
}

# 매수전용 상품 금리를 전세 상품보다 **싸게** 둔다 — 용도 필터가 없으면
# min(rate)가 이걸 집어가므로 결함 F가 테스트에 드러난다.
PRODUCTS = [
    {
        "rule_id": "buy-only-test",
        "product_name": "매수전용대출(테스트)",
        "product_type": "loan",
        "applies_to": ["buy"],
        "criteria": [],
        "terms": {"interest_rate": 0.005, "limit_krw": 200_000_000},
    },
    {
        "rule_id": "rental-loan-test",
        "product_name": "전월세보증금대출(테스트)",
        "product_type": "loan",
        "applies_to": ["jeonse", "wolse"],
        "criteria": [],
        "terms": {"interest_rate": 0.012, "limit_krw": 100_000_000},
    },
    {
        "rule_id": "wolse-support-test",
        "product_name": "청년월세지원(테스트)",
        "product_type": "subsidy",
        "applies_to": ["wolse"],
        "criteria": [],
        "terms": {
            "monthly_support_krw": 200_000,
            "support_months": 24,
            "limit_krw": 4_800_000,
        },
    },
]


def profile(*, assets=20_000_000, stay_years=4, income=2_800_000):
    return {
        "monthly_income_krw": income,
        "assets_krw": assets,
        "age": 27,
        "is_homeless": True,
        "is_household_head": True,
        "works_at_sme": True,
        "expected_stay_years": stay_years,
    }


def compare(*, jeonse_deposit, wolse_deposit=20_000_000, wolse_rent=550_000, **prof):
    return compare_jeonse_wolse(
        profile(**prof),
        {"deposit_krw": jeonse_deposit},
        {"deposit_krw": wolse_deposit, "monthly_rent_krw": wolse_rent},
        products=PRODUCTS,
        market_params=MARKET,
        tax_rules=TAX_RULES,
    )


class TestSplitFundingPolicy:
    """자기자본 / 정책대출(한도내) / 시장대출 3분할 — 결함 A의 근본 수정."""

    def test_loan_exceeds_policy_limit_splits_three_ways(self):
        # 2억 필요, 자산 2천만 → 대출 1.8억. 정책한도 1억 → 초과 8천만은 시장대출
        assert split_funding_policy(200_000_000, 20_000_000, 100_000_000) == (
            20_000_000,
            100_000_000,
            80_000_000,
        )

    def test_policy_limit_covers_loan_no_market_portion(self):
        # 5천만 필요, 자산 2천만 → 대출 3천만 < 한도 1억 → 전액 정책대출
        assert split_funding_policy(50_000_000, 20_000_000, 100_000_000) == (
            20_000_000,
            30_000_000,
            0,
        )

    def test_assets_cover_everything_no_loan(self):
        assert split_funding_policy(10_000_000, 30_000_000, 100_000_000) == (
            10_000_000,
            0,
            0,
        )

    def test_zero_policy_limit_is_all_market(self):
        """한도 0 = 정책대출 없음 — 기존 split_funding과 같은 결과."""
        assert split_funding_policy(50_000_000, 0, 0) == (0, 0, 50_000_000)

    def test_parts_always_sum_to_amount_needed(self):
        for needed, assets, limit in [
            (200_000_000, 20_000_000, 100_000_000),
            (50_000_000, 0, 30_000_000),
            (1, 0, 0),
        ]:
            assert sum(split_funding_policy(needed, assets, limit)) == needed


class TestDefectF_용도필터:
    """매수 전용 대출 금리가 전세·월세 비용에 쓰이면 안 된다."""

    def test_buy_only_product_not_used_for_jeonse(self):
        r = compare(jeonse_deposit=200_000_000)
        # 매수전용 0.5%가 아니라 전월세 1.2%가 쓰여야 한다
        assert r["jeonse"]["loan_rate"] == pytest.approx(0.012)

    def test_selected_product_name_is_reported(self):
        """어느 상품이 적용됐는지 화면이 인용할 수 있어야 한다(CLAUDE.md 원칙 2)."""
        r = compare(jeonse_deposit=200_000_000)
        assert r["jeonse"]["product_name"] == "전월세보증금대출(테스트)"


class TestDefectA_한도적용:
    """정책대출 한도 초과분에는 시장금리가 붙어야 한다."""

    def test_over_limit_portion_uses_market_rate(self):
        # 1억×1.2% + 8천만×3.5% + 2천만×4% = 120만 + 280만 + 80만
        r = compare(jeonse_deposit=200_000_000)
        assert r["jeonse"]["annual_krw"] == 4_800_000

    def test_within_limit_unchanged_regression_anchor(self):
        """한도 이내 케이스는 수정 전과 같아야 한다 — 3천만×1.2% + 2천만×4%."""
        r = compare(jeonse_deposit=50_000_000)
        assert r["jeonse"]["annual_krw"] == 1_160_000


class TestDefectB_월세보증금대출:
    """월세 보증금에도 정책대출이 적용돼야 한다(전세만 혜택받는 편향 제거)."""

    def test_wolse_deposit_gets_policy_rate(self):
        # 자산 0, 월세 보증금 5천만 → 정책금리 1.2% (시장 3.5% 아님)
        r = compare(jeonse_deposit=200_000_000, wolse_deposit=50_000_000, assets=0)
        assert r["wolse"]["loan_rate"] == pytest.approx(0.012)

    def test_wolse_funding_cost_uses_policy_rate(self):
        r = compare(
            jeonse_deposit=200_000_000,
            wolse_deposit=50_000_000,
            wolse_rent=550_000,
            assets=0,
            stay_years=2,
        )
        # 연월세 660만 − 세액공제 112.2만 + 보증금 5천만×1.2%(60만) − 지원 240만
        assert r["wolse"]["annual_krw"] == 6_600_000 - 1_122_000 + 600_000 - 2_400_000


class TestDefectC_지원기간:
    """월세지원은 24개월 한시다 — 매년 반복 차감하면 과대 계상."""

    def test_four_year_stay_averages_support_over_stay(self):
        # 총 480만(20만×24개월) ÷ 4년 = 연 120만
        r = compare(jeonse_deposit=200_000_000, stay_years=4)
        assert r["wolse"]["support_annual_krw"] == 1_200_000

    def test_two_year_stay_gets_full_annual_support(self):
        # 거주 2년 = 지원기간과 동일 → 연 240만 그대로
        r = compare(jeonse_deposit=200_000_000, stay_years=2)
        assert r["wolse"]["support_annual_krw"] == 2_400_000

    def test_one_year_stay_capped_by_months_lived(self):
        """1년만 살면 12개월분(240만)만 받는다 — 24개월분을 앞당겨 받지 않는다."""
        r = compare(jeonse_deposit=200_000_000, stay_years=1)
        assert r["wolse"]["support_annual_krw"] == 2_400_000

    def test_total_support_never_exceeds_rule_cap(self):
        for years in (1, 2, 3, 4, 10):
            r = compare(jeonse_deposit=200_000_000, stay_years=years)
            total = r["wolse"]["support_annual_krw"] * years
            assert total <= 4_800_000, f"{years}년 거주 시 총 {total:,}원 > 상한 480만"


class TestBreakdown:
    """항목별 합이 헤드라인 합계와 일치해야 한다(계획서 검증기준 5)."""

    @pytest.mark.parametrize("side", ["jeonse", "wolse"])
    def test_breakdown_sums_to_total(self, side):
        r = compare(jeonse_deposit=200_000_000)
        assert sum(r[side]["breakdown"].values()) == r[side]["annual_krw"]

    def test_breakdown_labels_are_stable(self):
        r = compare(jeonse_deposit=200_000_000)
        assert set(r["jeonse"]["breakdown"]) == {
            "정책대출이자",
            "시장대출이자",
            "보증금기회비용",
            "미회수기대손실",
        }
        # 월세도 보증금 미회수 위험을 대칭으로 계산한다(Phase 3). 위험 입력이 없으면
        # 0이지만 키는 항상 있다 — 화면이 항목 집합을 조건부로 다루지 않게.
        assert set(r["wolse"]["breakdown"]) == {
            "연월세",
            "월세세액공제",
            "정책대출이자",
            "시장대출이자",
            "보증금기회비용",
            "청년월세지원",
            "미회수기대손실",
        }


class TestRealRules:
    """실제 룰 파일 보증 — 인라인 룰이 통과해도 배포 룰이 틀리면 의미 없다."""

    def test_every_loan_or_subsidy_declares_applies_to(self):
        missing = [
            p["rule_id"]
            for p in load_products()
            if p.get("product_type") in ("loan", "subsidy") and not p.get("applies_to")
        ]
        assert not missing, f"applies_to 누락: {missing}"

    def test_purchase_loan_is_not_marked_for_rental(self):
        didimdol = next(p for p in load_products() if p["rule_id"].startswith("didimdol"))
        assert "jeonse" not in didimdol["applies_to"]
        assert "wolse" not in didimdol["applies_to"]

    def test_policy_jeonse_loan_has_usable_rate(self):
        """**정책상품**은 금리가 있어야 한다 — null이면 비용 비교에서 조용히 탈락한다.

        은행 자체 상품은 예외다. COFIX+가산금리 변동이라 사전에 숫자로 확정할 수 없고,
        지어낸 금리로 비용을 계산하면 자사 상품을 유리(또는 불리)하게 만든 셈이 된다.
        대신 rate_display에 "COFIX + 가산금리(심사 시 결정)"를 문장으로 둔다.
        """
        rentals = [
            p
            for p in load_products()
            if p.get("product_type") == "loan" and "jeonse" in p.get("applies_to", [])
        ]
        assert rentals, "전세용 대출 상품이 없다"
        for p in rentals:
            if p.get("is_policy_product", True):
                assert p["terms"].get("interest_rate") is not None, f"{p['rule_id']} 금리 없음"
            else:
                # 금리를 안 쓰는 대신 무엇으로 정해지는지는 반드시 밝혀야 한다
                assert p["terms"].get("rate_display"), f"{p['rule_id']} rate_display 없음"

    def test_bank_product_ranks_below_policy_products(self):
        """자사 상품이 정책상품을 앞지르면 안 된다 — 숫자의 신뢰가 무너진다.

        금리 null은 _rank_key에서 1.0으로 취급돼 맨 뒤로 간다. 이 동작이 깨지면
        제품이 KB 상품을 밀어준 것처럼 보인다.
        """
        from onjeon.l3.recommend import recommend

        user = {"age": 27, "annual_income_krw": 30_000_000, "assets_krw": 20_000_000,
                "deposit_krw": 150_000_000, "is_homeless": True, "is_household_head": True,
                "works_at_sme": False, "no_credit_delinquency": True, "is_newlywed": False}
        eligible = recommend(user, load_products())["eligible"]
        names = [r["rule_id"] for r in eligible]
        assert "kb-youth-jeonse-2026-07" in names, "KB 상품이 자격에 없다"
        kb_at = names.index("kb-youth-jeonse-2026-07")
        # 비교 대상은 **금리가 확정된 정책 대출**뿐이다. 지원금·적금도 금리가 없어
        # 뒤에 오지만 그건 대출이 아니라 순서를 논할 대상이 아니다.
        rated_policy = [
            i for i, r in enumerate(eligible)
            if r.get("is_policy_product") and r["terms"].get("interest_rate") is not None
        ]
        assert rated_policy, "금리 있는 정책 대출이 하나도 없다 — 테스트 전제가 깨졌다"
        assert kb_at > max(rated_policy), f"KB 상품이 정책 대출보다 앞에 있다: {names}"

    def test_monthly_support_has_structured_terms(self):
        support = next(
            p for p in load_products() if p["rule_id"].startswith("youth-monthly-rent-support")
        )
        assert support["terms"]["monthly_support_krw"] > 0
        assert support["terms"]["support_months"] > 0
