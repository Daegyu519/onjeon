"""L3 계산 엔진 단위 테스트 — 모든 금액은 원(₩) 정수."""

import pytest

from onjeon.l3.engine import (
    annual_cost_buy,
    annual_cost_jeonse,
    annual_cost_wolse,
    bracket_fee,
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
    # 구간표는 실제 룰 JSON과 같은 모양이어야 한다 — 픽스처가 단일 요율이면
    # 구간 경계 버그가 테스트를 다 통과하면서 살아남는다(CLAUDE.md 함정 4와 같은 실패).
    "acquisition": {
        "clause": "지방세법 §11①8호 + §151①1호",
        "brackets": [
            {"max_price_krw": 600_000_000, "rate": 0.010},
            {"max_price_krw": 900_000_000, "rate_from": 0.010, "rate_to": 0.030},
            {"max_price_krw": None, "rate": 0.030},
        ],
        "local_education_tax_multiplier": 1.1,
    },
    "holding": {"clause": "지방세법 §111", "estimate_rate": 0.0015},
    "brokerage": {
        "clause": "공인중개사법 시행규칙 별표 1",
        "buy_brackets": [
            {"max_price_krw": 50_000_000, "rate": 0.006, "cap_krw": 250_000},
            {"max_price_krw": 200_000_000, "rate": 0.005, "cap_krw": 800_000},
            {"max_price_krw": 900_000_000, "rate": 0.004},
            {"max_price_krw": 1_200_000_000, "rate": 0.005},
            {"max_price_krw": 1_500_000_000, "rate": 0.006},
            {"max_price_krw": None, "rate": 0.007},
        ],
    },
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


class TestBracketFee:
    """구간표 적용 — 법령 원문(지방세법 §11①8호, 공인중개사법 시행규칙 별표1) 기준.

    단일 요율을 쓰던 시절 중개보수가 실제로 틀려 있었다(2억~9억에 0.5%를 썼는데
    별표1은 1천분의 4다). 경계·한도·선형구간이 여기서 깨지면 매수 비용이
    조용히 틀리므로 세 가지를 다 고정한다.
    """

    BUY = TAX_RULES["brokerage"]["buy_brackets"]
    ACQ = TAX_RULES["acquisition"]["brackets"]

    def test_brokerage_2eok_uses_0_4_percent_not_0_5(self):
        """회귀: 4억 매수 중개보수는 160만원(0.4%)이다. 종전 200만원(0.5%)은 오답."""
        assert bracket_fee(400_000_000, self.BUY) == 1_600_000

    def test_brokerage_bracket_boundary_takes_lower_rate(self):
        """정확히 2억은 '2억원 이상 9억원 미만' 구간 — 0.4%."""
        assert bracket_fee(200_000_000, self.BUY) == 800_000

    def test_brokerage_cap_binds_just_below_boundary(self):
        """1.9억 × 0.5% = 95만이지만 별표1 한도액 80만원에서 잘린다."""
        assert bracket_fee(190_000_000, self.BUY) == 800_000

    def test_brokerage_cap_does_not_bind_when_below(self):
        """4천만 × 0.6% = 24만 < 한도 25만 — 한도를 잘못 적용하면 25만이 된다."""
        assert bracket_fee(40_000_000, self.BUY) == 240_000

    def test_brokerage_top_bracket_is_unbounded(self):
        assert bracket_fee(2_000_000_000, self.BUY) == 14_000_000

    def test_acquisition_flat_bracket(self):
        assert bracket_fee(600_000_000, self.ACQ) == 6_000_000  # 6억 이하 1%

    def test_acquisition_linear_band_matches_statute_formula(self):
        """§11①8호 나목: 세율 = (가액 × 2 ÷ 3억 − 3) ÷ 100. 선형보간과 같아야 한다."""
        for price in (600_000_000, 700_000_000, 750_000_000, 900_000_000):
            statutory = (price * 2 / 300_000_000 - 3) / 100
            assert bracket_fee(price, self.ACQ) == pytest.approx(price * statutory)

    def test_acquisition_above_9eok_is_flat_3_percent(self):
        assert bracket_fee(1_000_000_000, self.ACQ) == 30_000_000

    def test_missing_unbounded_bracket_raises(self):
        """마지막 구간에 상한을 남겨두면 그 위 금액이 조용히 0이 되는 대신 터진다."""
        with pytest.raises(ValueError):
            bracket_fee(10_000_000_000, [{"max_price_krw": 100, "rate": 0.01}])


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
