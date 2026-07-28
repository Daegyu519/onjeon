"""소액임차인 최우선변제 — 지역 판정. 지금은 서울만 지원한다.

주택임대차보호법 시행령 §10·§11은 지역을 4구간으로 나누고 금액이 2배 이상 벌어진다
(법제처 OPEN API로 원문 수집, 시행 2026-07-01):

    서울특별시                                    5,500만 / 기준 1억6,500만
    과밀억제권역·세종·용인·화성·김포                4,800만 / 기준 1억4,500만
    광역시·안산·광주·파주·이천·평택                2,800만 / 기준   8,500만
    그 밖의 지역                                  2,500만 / 기준   7,500만

전국에 서울 값을 쓰면 비서울 매물이 **받지도 못할 보호를 받은 것으로** 계산된다.
최우선변제는 engine.lgd에서 회수액에 더해지므로, 과대계상하면 LGD가 낮아지고
E[Loss]가 줄어든다 — 위험한 집이 안전해 보이는 방향이라 이 제품이 가장 하면 안 되는 오류다.

서울 밖은 0으로 둔다. 과대평가 방향이라 안전하고, 화면이 "아직 서울만 가능"이라고 말한다.
"""

import pytest

from onjeon.l3.risk import deposit_risk, priority_amount
from onjeon.rules_io import load_rules


@pytest.fixture
def rule():
    return load_rules("market_params")["small_deposit_priority"]


class TestSeoulApplied:
    @pytest.mark.parametrize("region", ["관악구", "강남구", "서울특별시 관악구 봉천동", "서울 강서구"])
    def test_seoul_gets_protection(self, rule, region):
        assert priority_amount(100_000_000, rule, region) == 55_000_000

    def test_deposit_below_limit_returns_deposit(self, rule):
        """보증금이 한도보다 작으면 전액이 보호 대상이다."""
        assert priority_amount(30_000_000, rule, "관악구") == 30_000_000

    def test_above_threshold_gets_nothing(self, rule):
        """기준액(1억6,500만) 초과면 소액임차인이 아니다."""
        assert priority_amount(165_000_001, rule, "관악구") == 0
        assert priority_amount(165_000_000, rule, "관악구") == 55_000_000


class TestNonSeoulBlocked:
    @pytest.mark.parametrize("region", ["유성구", "대전광역시 유성구 궁동", "부산광역시 해운대구", "제주시"])
    def test_non_seoul_gets_zero(self, rule, region):
        assert priority_amount(100_000_000, rule, region) == 0

    def test_unknown_region_is_not_assumed_seoul(self, rule):
        """모름 ≠ 서울. 모를 때 적용하면 비서울에 서울 값을 쓰게 된다."""
        assert priority_amount(100_000_000, rule, None) == 0
        assert priority_amount(100_000_000, rule, "default") == 0

    def test_no_rule_means_no_protection(self, rule):
        """없는 보호를 가정하지 않는다."""
        assert priority_amount(100_000_000, None, "관악구") == 0


class TestRuleIsData:
    """지역명을 코드에 박으면 룰만 고쳐서는 지역을 못 늘린다(CLAUDE.md 원칙 3)."""

    def test_region_tokens_live_in_rule(self, rule):
        assert rule["region_match"], "region_match가 룰에 없다"
        assert "서울특별시" in rule["region_match"]
        assert "관악구" in rule["region_match"], "서울 25개 구가 토큰에 있어야 한다"

    def test_amounts_match_law_text(self, rule):
        """룰의 숫자가 조문 원문과 일치하는지 — 손으로 옮기다 자릿수를 틀리는 자리다."""
        assert "5천500만원" in rule["clause_text"]["제10조 제1호"]
        assert "1억6천500만원" in rule["clause_text"]["제11조 제1호"]
        assert rule["limit_krw"] == 55_000_000
        assert rule["threshold_krw"] == 165_000_000

    def test_other_regions_kept_for_later(self, rule):
        """지원은 서울뿐이지만 4구간 원문은 버리지 않는다 — 확장할 때 다시 안 받아도 된다."""
        items = rule["other_regions_reference"]["제11조"]
        assert len(items) == 4
        assert any("그 밖의 지역" in x for x in items)


class TestSurfacedToCaller:
    """왜 보호가 0인지 화면이 말할 수 있어야 한다."""

    def _risk(self, region, rule):
        class Model:
            def predict_proba(self, f): return 0.05
        return deposit_risk(
            deposit=100_000_000, market_price=200_000_000, senior_claims=50_000_000,
            building_type="빌라", auction_rate=0.75, model=Model(),
            priority_rule=rule, region=region,
        )

    def test_seoul_marked_supported(self, rule):
        r = self._risk("관악구", rule)
        assert r["priority_supported"] is True
        assert r["priority_krw"] == 55_000_000

    def test_non_seoul_marked_unsupported(self, rule):
        r = self._risk("유성구", rule)
        assert r["priority_supported"] is False
        assert r["priority_krw"] == 0
        assert r["priority_region_scope"] == "서울특별시"

    def test_non_seoul_has_higher_loss(self, rule):
        """보호가 빠지면 기대손실이 커져야 한다 — 방향이 반대면 배선이 틀린 것이다."""
        assert self._risk("유성구", rule)["e_loss_krw"] >= self._risk("관악구", rule)["e_loss_krw"]
