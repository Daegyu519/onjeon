"""L3 계산 엔진 단위 테스트 — 모든 금액은 원(₩) 정수."""

import pytest

from onjeon.l3.engine import (
    annual_cost_buy,
    annual_cost_jeonse,
    annual_cost_wolse,
    expected_loss,
    lgd,
    split_funding,
    wolse_tax_credit,
)

TAX_RULES = {
    "version": "2026-07",
    "wolse_tax_credit": {
        "clause": "조특법 §95-2",
        "brackets": [
            {"max_income_krw": 55_000_000, "rate": 0.17},
            {"max_income_krw": 80_000_000, "rate": 0.15},
        ],
        "annual_rent_cap_krw": 10_000_000,
    },
    "acquisition": {"clause": "지방세법 §11", "rate": 0.011},
    "holding": {"clause": "지방세법 §111", "estimate_rate": 0.0015},
    "brokerage": {"clause": "공인중개사법", "buy_rate": 0.005},
}


class TestSplitFunding:
    def test_deposit_exceeds_assets_uses_loan(self):
        assert split_funding(120_000_000, 30_000_000) == (30_000_000, 90_000_000)

    def test_deposit_within_assets_no_loan(self):
        assert split_funding(10_000_000, 30_000_000) == (10_000_000, 0)

    def test_zero_assets_full_loan(self):
        assert split_funding(50_000_000, 0) == (0, 50_000_000)


class TestJeonse:
    def test_persona_risky_villa(self):
        # 대출 9,000만×3.5% = 315만 + 자기자본 3,000만×4% = 120만 + E[Loss] 180만
        cost = annual_cost_jeonse(
            deposit=120_000_000,
            user_assets=30_000_000,
            loan_rate=0.035,
            opportunity_rate=0.04,
            e_loss=1_800_000,
        )
        assert cost == 6_150_000

    def test_zero_e_loss_is_nominal_only(self):
        cost = annual_cost_jeonse(
            deposit=120_000_000,
            user_assets=30_000_000,
            loan_rate=0.035,
            opportunity_rate=0.04,
            e_loss=0,
        )
        assert cost == 4_350_000


class TestWolseTaxCredit:
    def test_income_in_first_bracket_17pct(self):
        assert wolse_tax_credit(7_800_000, 36_000_000, TAX_RULES) == 1_326_000

    def test_income_in_second_bracket_15pct(self):
        assert wolse_tax_credit(7_800_000, 60_000_000, TAX_RULES) == 1_170_000

    def test_income_above_all_brackets_no_credit(self):
        assert wolse_tax_credit(7_800_000, 90_000_000, TAX_RULES) == 0

    def test_bracket_boundary_inclusive(self):
        assert wolse_tax_credit(7_800_000, 55_000_000, TAX_RULES) == 1_326_000

    def test_annual_rent_capped(self):
        # 연 월세 1,200만 → 한도 1,000만에 17%
        assert wolse_tax_credit(12_000_000, 36_000_000, TAX_RULES) == 1_700_000

    def test_bracket_order_independent(self):
        # L0가 생성한 룰이 내림차순이어도 결과가 같아야 한다
        unsorted_rules = {
            **TAX_RULES,
            "wolse_tax_credit": {
                **TAX_RULES["wolse_tax_credit"],
                "brackets": list(reversed(TAX_RULES["wolse_tax_credit"]["brackets"])),
            },
        }
        assert wolse_tax_credit(7_800_000, 36_000_000, unsorted_rules) == 1_326_000
        assert wolse_tax_credit(7_800_000, 60_000_000, unsorted_rules) == 1_170_000


class TestWolse:
    def test_persona_safe_officetel(self):
        # 780만 − 공제 132.6만 + 보증금 1,000만×4% = 687.4만
        cost = annual_cost_wolse(
            deposit=10_000_000,
            monthly_rent=650_000,
            annual_income=36_000_000,
            user_assets=30_000_000,
            loan_rate=0.035,
            opportunity_rate=0.04,
            tax_rules=TAX_RULES,
        )
        assert cost == 6_874_000

    def test_deposit_above_assets_incurs_interest(self):
        # 보증금 5,000만, 자산 3,000만 → 대출 2,000만×3.5% = 70만 + 자기 3,000만×4% = 120만
        cost = annual_cost_wolse(
            deposit=50_000_000,
            monthly_rent=650_000,
            annual_income=36_000_000,
            user_assets=30_000_000,
            loan_rate=0.035,
            opportunity_rate=0.04,
            tax_rules=TAX_RULES,
        )
        assert cost == 7_800_000 - 1_326_000 + 700_000 + 1_200_000


class TestBuy:
    def test_persona_buys_villa(self):
        # 취득세 165만/4 + 중개 75만/4 + 보유세 22.5만 + 대출 1.2억×4% + 자기 3,000만×4%
        cost = annual_cost_buy(
            price=150_000_000,
            user_assets=30_000_000,
            loan_rate=0.04,
            opportunity_rate=0.04,
            stay_years=4,
            tax_rules=TAX_RULES,
        )
        assert cost == 412_500 + 187_500 + 225_000 + 4_800_000 + 1_200_000

    def test_stay_years_must_be_positive(self):
        with pytest.raises(ValueError):
            annual_cost_buy(
                price=150_000_000,
                user_assets=30_000_000,
                loan_rate=0.04,
                opportunity_rate=0.04,
                stay_years=0,
                tax_rules=TAX_RULES,
            )


class TestLGD:
    def test_risky_villa(self):
        # 낙찰 1.5억×0.78 = 1.17억 − 선순위 0.72억 = 회수 0.45억 → 1 − 45/120 = 0.625
        assert lgd(
            market_price=150_000_000,
            auction_rate=0.78,
            senior_claims=72_000_000,
            deposit=120_000_000,
        ) == pytest.approx(0.625)

    def test_senior_claims_exceed_auction_total_loss(self):
        assert lgd(
            market_price=150_000_000,
            auction_rate=0.78,
            senior_claims=130_000_000,
            deposit=120_000_000,
        ) == pytest.approx(1.0)

    def test_full_recovery_zero_loss(self):
        assert lgd(
            market_price=200_000_000,
            auction_rate=0.85,
            senior_claims=0,
            deposit=10_000_000,
        ) == pytest.approx(0.0)

    def test_insured_overrides_to_zero(self):
        assert lgd(
            market_price=150_000_000,
            auction_rate=0.78,
            senior_claims=130_000_000,
            deposit=120_000_000,
            insured=True,
        ) == pytest.approx(0.0)

    def test_zero_deposit_raises(self):
        with pytest.raises(ValueError):
            lgd(
                market_price=150_000_000,
                auction_rate=0.78,
                senior_claims=0,
                deposit=0,
            )


class TestExpectedLoss:
    def test_formula(self):
        # E[Loss] = P × LGD × 보증금
        assert expected_loss(0.08, 0.625, 120_000_000) == 6_000_000

    def test_returns_int(self):
        assert isinstance(expected_loss(0.0333, 0.625, 120_000_000), int)
