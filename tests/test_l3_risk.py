"""L3 보증금 미회수 위험 — 두 경로가 공유하는 단일 정의.

왜 모듈로 뽑았나: compare.py(Streamlit 3안 비교)와 decision.py(배포 경로)가 각각
"피처 구성 → P(사고) → LGD → E[Loss]"를 따로 구현하고 있었다. 같은 제품이 두 경로에서
다른 답을 낼 수 있는 구조였다 — 특히 compare.py는 월세 E[Loss]를 0으로 하드코딩했다.
"""

import pytest

from onjeon.l3 import engine
from onjeon.l3.risk import deposit_risk

# 실측 앵커: 관악구 빌라 전용 40㎡, 시세 2.899억, 낙찰가율 74%, 선순위 1.2억
PRICE = 289_910_000
AUCTION = 0.74
SENIOR = 120_000_000


class _FixedModel:
    """계수를 고정한 모델 — 위험 계산 구조만 검사하고 학습 결과에 얽매이지 않는다."""

    data_note = "테스트 고정 모델"

    def predict_proba(self, x):
        return 0.05

    def explain(self, x):
        return {"p": 0.05, "base_logit": 0.0, "contributions": [], "data_note": self.data_note}


class TestDepositRisk:
    def test_builds_features_from_prices(self):
        out = deposit_risk(
            deposit=200_000_000, market_price=PRICE, senior_claims=SENIOR,
            building_type="빌라", auction_rate=AUCTION, model=_FixedModel(),
        )
        f = out["features"]
        assert f["jeonse_ratio"] == pytest.approx(200_000_000 / PRICE)
        assert f["lien_ratio"] == pytest.approx(SENIOR / PRICE)
        assert f["is_villa"] == 1
        assert f["auction_rate"] == AUCTION

    def test_is_villa_zero_for_other_types(self):
        for btype in ("아파트", "오피스텔", "기타", None):
            out = deposit_risk(
                deposit=200_000_000, market_price=PRICE, senior_claims=SENIOR,
                building_type=btype, auction_rate=AUCTION, model=_FixedModel(),
            )
            assert out["features"]["is_villa"] == 0, btype

    def test_expected_loss_is_product_of_parts(self):
        out = deposit_risk(
            deposit=200_000_000, market_price=PRICE, senior_claims=SENIOR,
            building_type="빌라", auction_rate=AUCTION, model=_FixedModel(),
        )
        assert out["e_loss_krw"] == engine.expected_loss(
            out["p_accident"], out["lgd"], 200_000_000
        )

    def test_lgd_matches_engine(self):
        out = deposit_risk(
            deposit=200_000_000, market_price=PRICE, senior_claims=SENIOR,
            building_type="빌라", auction_rate=AUCTION, model=_FixedModel(),
        )
        assert out["lgd"] == pytest.approx(
            engine.lgd(
                market_price=PRICE, auction_rate=AUCTION,
                senior_claims=SENIOR, deposit=200_000_000,
            )
        )

    def test_insured_has_no_loss(self):
        out = deposit_risk(
            deposit=200_000_000, market_price=PRICE, senior_claims=SENIOR,
            building_type="빌라", auction_rate=AUCTION, insured=True, model=_FixedModel(),
        )
        assert out["lgd"] == 0.0
        assert out["e_loss_krw"] == 0

    def test_zero_price_raises_not_divides_by_zero(self):
        with pytest.raises((ValueError, ZeroDivisionError)):
            deposit_risk(
                deposit=200_000_000, market_price=0, senior_claims=SENIOR,
                building_type="빌라", auction_rate=AUCTION, model=_FixedModel(),
            )


class TestSmallDepositPriority:
    """소액임차인 최우선변제 — 주택임대차보호법 §8, 시행령 §10·§11.

    선순위 근저당보다 먼저 일정액을 배당받는다. 이걸 빼면 소액 보증금(월세)의
    미회수 위험이 실제보다 크게 나온다 — 반영 전 한계로 명시돼 있던 항목이다.
    """

    # 선순위가 낙찰가를 거의 다 먹는 상황: 시세 2억 × 74% = 1.48억 < 선순위 1.6억
    TIGHT = dict(market_price=200_000_000, auction_rate=0.74, senior_claims=160_000_000)

    def test_without_priority_small_deposit_loses_everything(self):
        """최우선변제 없이는 회수 예상액이 0 → LGD 1.0."""
        assert engine.lgd(deposit=20_000_000, **self.TIGHT) == 1.0

    def test_priority_protects_small_deposit_ahead_of_liens(self):
        """한도 내 소액 보증금은 선순위보다 먼저 배당 → 전액 회수."""
        got = engine.lgd(
            deposit=20_000_000, priority_krw=20_000_000, **self.TIGHT
        )
        assert got == 0.0

    def test_priority_is_capped_and_partial(self):
        """보증금이 최우선변제 한도를 넘으면 한도까지만 보호된다."""
        got = engine.lgd(deposit=100_000_000, priority_krw=55_000_000, **self.TIGHT)
        # 5,500만 최우선 + 잔여 배당 max(1.48억 − 5,500만 − 1.6억, 0) = 0
        assert got == pytest.approx(1 - 55_000_000 / 100_000_000)

    def test_priority_does_not_double_count_against_ample_auction(self):
        """낙찰가가 넉넉하면 최우선변제가 있으나 없으나 전액 회수 — 이중계산 금지."""
        ample = dict(market_price=1_000_000_000, auction_rate=0.9, senior_claims=100_000_000)
        assert engine.lgd(deposit=20_000_000, **ample) == 0.0
        assert engine.lgd(deposit=20_000_000, priority_krw=20_000_000, **ample) == 0.0

    def test_priority_zero_is_same_as_absent(self):
        assert engine.lgd(deposit=20_000_000, priority_krw=0, **self.TIGHT) == engine.lgd(
            deposit=20_000_000, **self.TIGHT
        )


class TestPriorityAmountFromRules:
    """한도·기준액은 룰 데이터에서 온다 (원칙 3).

    수치는 이제 [확인] 대상이 아니다 — 법제처 국가법령정보 OPEN API로 시행령 §10·§11
    **원문을 받아** 채웠다(시행 2026-07-01). 지역 판정은 tests/test_priority_region.py.
    """

    def test_rule_has_seoul_thresholds(self):
        from onjeon.rules_io import load_rules

        rule = load_rules("market_params")["small_deposit_priority"]
        assert rule["threshold_krw"] > 0
        assert rule["limit_krw"] > 0
        assert rule["limit_krw"] <= rule["threshold_krw"]
        # 2차 출처가 아니라 법령 원문을 인용해야 한다(원칙 2)
        assert "법제처" in rule["source"]
        assert rule["clause_text"], "조문 원문을 함께 보관해야 사람이 대조할 수 있다"

    def test_small_deposit_qualifies(self):
        """서울 매물 기준. 지역을 안 주면 0이 되는 것이 의도된 동작이다."""
        from onjeon.l3.risk import priority_amount
        from onjeon.rules_io import load_rules

        rule = load_rules("market_params")["small_deposit_priority"]
        assert priority_amount(1_000_000, rule, "관악구") == 1_000_000  # 보증금 전액(한도 이하)
        assert priority_amount(rule["threshold_krw"], rule, "관악구") == rule["limit_krw"]

    def test_large_deposit_gets_no_priority(self):
        from onjeon.l3.risk import priority_amount
        from onjeon.rules_io import load_rules

        rule = load_rules("market_params")["small_deposit_priority"]
        assert priority_amount(rule["threshold_krw"] + 1, rule, "관악구") == 0

    def test_missing_rule_means_no_priority(self):
        """룰이 없으면 보호를 가정하지 않는다 — 보수적으로 0."""
        from onjeon.l3.risk import priority_amount

        assert priority_amount(20_000_000, None) == 0
        assert priority_amount(20_000_000, {}) == 0


class TestPriceBand:
    """밴드 폭은 집계 단위에 달려 있다 — 구 평균에 지번 단위 폭을 붙이면 거짓 정밀도다."""

    RULE = {"jibun": 0.1, "dong": 0.2, "sigungu": 0.3, "default": 0.3}

    def test_wider_band_for_coarser_aggregation(self):
        from onjeon.decision import _price_band

        jibun = _price_band({"price_level": "jibun"}, self.RULE)
        dong = _price_band({"price_level": "dong"}, self.RULE)
        gu = _price_band({"price_level": "sigungu"}, self.RULE)
        assert jibun < dong < gu, "집계가 넓어질수록 불확실성이 커야 한다"

    def test_user_entered_price_has_no_band(self):
        """사용자가 직접 넣은 매매가는 추정이 아니다 — 불확실성을 지어내지 않는다."""
        from onjeon.decision import _price_band

        assert _price_band({}, self.RULE) == 0.0

    def test_unknown_level_uses_default(self):
        from onjeon.decision import _price_band

        assert _price_band({"price_level": "행정동"}, self.RULE) == 0.3

    def test_missing_rule_means_no_band(self):
        from onjeon.decision import _price_band

        assert _price_band({"price_level": "dong"}, None) == 0.0

    def test_rule_file_marks_values_unverified(self):
        """판단값이면 그렇다고 표시하고 오차 방향을 적어야 한다 (원칙 5·6).

        종전에는 `[확인]` 문자열을 봤는데, 마커만으로는 '어느 쪽으로 틀리는지'를
        읽는 사람이 알 수 없었다. 판단값은 judgment 플래그와 error_direction을
        함께 요구한다.
        """
        from onjeon.rules_io import load_rules

        rule = load_rules("market_params")["price_uncertainty_by_level"]
        assert rule["judgment"] is True
        assert rule["error_direction"]
        assert rule["jibun"] < rule["dong"] < rule["sigungu"]


class TestAccidentProbabilityBand:
    """P(사고)의 시점 변동 밴드 — 보증사고율은 해마다 크게 움직인다(전국 8.1% → 1.0%).

    점추정 하나만 내면 "어느 시점 기준이냐"에 따라 몇 배 달라진다는 사실이 숨는다.
    밴드는 통계적 신뢰구간이 아니라 **관측된 시점 변동**이다.
    """

    FEATS = {"jeonse_ratio": 0.69, "lien_ratio": 0.41, "is_villa": 1, "auction_rate": 0.74}

    def _model(self, periods):
        from onjeon.l2.model import FEATURES, RiskModel

        return RiskModel(
            coef=dict.fromkeys(FEATURES, 0.5), intercept=-4.0,
            feature_means=dict.fromkeys(FEATURES, 0.5), periods=periods,
        )

    def test_no_periods_gives_point_estimate_both_sides(self):
        m = self._model([])
        lo, hi = m.predict_proba_band(self.FEATS)
        assert lo == hi == m.predict_proba(self.FEATS)

    def test_band_spans_period_variation(self):
        from onjeon.l2.model import FEATURES

        periods = [
            {"period": "2023-06", "intercept": -2.0, "coef": dict.fromkeys(FEATURES, 0.5)},
            {"period": "2026-06", "intercept": -5.0, "coef": dict.fromkeys(FEATURES, 0.5)},
        ]
        lo, hi = self._model(periods).predict_proba_band(self.FEATS)
        assert lo < hi, "사고율이 높던 해와 낮던 해가 밴드 양끝이어야 한다"
        assert hi / lo > 5, "실제 시점 변동은 몇 배 규모다"

    def test_deposit_risk_exposes_both_p_and_eloss_range(self):
        from onjeon.l2.model import FEATURES

        periods = [
            {"period": "2023-06", "intercept": -2.0, "coef": dict.fromkeys(FEATURES, 0.5)},
            {"period": "2026-06", "intercept": -5.0, "coef": dict.fromkeys(FEATURES, 0.5)},
        ]
        out = deposit_risk(
            deposit=200_000_000, market_price=PRICE, senior_claims=SENIOR,
            building_type="빌라", auction_rate=AUCTION, model=self._model(periods),
        )
        p_lo, p_hi = out["p_accident_range"]
        e_lo, e_hi = out["e_loss_from_p_range"]
        assert p_lo <= out["p_accident"] <= p_hi
        assert e_lo <= out["e_loss_krw"] <= e_hi
        assert e_lo < e_hi

    def test_insured_property_has_zero_band(self):
        """보증보험이면 LGD 0이라 P가 아무리 흔들려도 손실은 0이다."""
        from onjeon.l2.model import FEATURES

        periods = [
            {"period": "2023-06", "intercept": -2.0, "coef": dict.fromkeys(FEATURES, 0.5)},
            {"period": "2026-06", "intercept": -5.0, "coef": dict.fromkeys(FEATURES, 0.5)},
        ]
        out = deposit_risk(
            deposit=200_000_000, market_price=PRICE, senior_claims=SENIOR,
            building_type="빌라", auction_rate=AUCTION, insured=True, model=self._model(periods),
        )
        assert out["e_loss_from_p_range"] == [0, 0]
