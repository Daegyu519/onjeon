"""compare 오케스트레이터 단위 테스트 — 낙찰가율 조회 폴백."""

from onjeon.compare import _auction_rate
from onjeon.rules_io import load_rules

RATES = {
    "rates": {
        "관악구": {"빌라": 0.78, "오피스텔": 0.85, "아파트": 0.92, "기타": 0.70},
        "default": {"빌라": 0.75, "오피스텔": 0.82, "아파트": 0.90, "기타": 0.68},
    }
}


def make_doc(region: str, building_type: str) -> dict:
    return {"property": {"region": region, "building_type": building_type}}


class TestAuctionRate:
    def test_region_and_type_match(self):
        assert _auction_rate(make_doc("관악구", "빌라"), RATES) == 0.78

    def test_unknown_region_falls_back_to_default(self):
        assert _auction_rate(make_doc("송파구", "오피스텔"), RATES) == 0.82

    def test_gita_building_type_supported(self):
        assert _auction_rate(make_doc("관악구", "기타"), RATES) == 0.70

    def test_unknown_type_falls_back_conservative(self):
        # 테이블에 없는 유형은 가장 보수적(최저) 낙찰가율로 — 크래시 금지
        assert _auction_rate(make_doc("관악구", "상가"), RATES) == 0.68

    def test_rules_json_covers_gita(self):
        rates = load_rules("auction_rates")["rates"]
        assert "기타" in rates["관악구"] and "기타" in rates["default"]
