"""지역 → 법정동 시군구 코드(LAWD_CD) 매핑 + 실거래가 라이브 시세 조회 테스트."""

import pytest

from onjeon.data_pipeline.molit import live_market_price
from onjeon.data_pipeline.regions import recent_deal_ym, resolve_lawd_cd

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>000</resultCode></header><body><items>
  <item><dealAmount>28,000</dealAmount><excluUseAr>29.75</excluUseAr><floor>3</floor>
    <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>12</dealDay><umdNm>신림동</umdNm></item>
  <item><dealAmount>32,000</dealAmount><excluUseAr>39.6</excluUseAr><floor>5</floor>
    <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>3</dealDay><umdNm>봉천동</umdNm></item>
</items></body></response>"""


class TestResolveLawdCd:
    def test_gwanak(self):
        assert resolve_lawd_cd("관악구") == "11620"

    def test_dongjak(self):
        assert resolve_lawd_cd("동작구") == "11590"

    def test_handles_full_address_prefix(self):
        assert resolve_lawd_cd("서울특별시 관악구 신림동") == "11620"

    def test_unknown_region_returns_none(self):
        assert resolve_lawd_cd("부산 해운대구") is None


class TestRecentDealYm:
    def test_format_yyyymm(self):
        assert recent_deal_ym("2026-07-19") == "202606"  # 직전 완결 월

    def test_january_rolls_to_prev_year(self):
        assert recent_deal_ym("2026-01-10") == "202512"


class TestLiveMarketPrice:
    def _fake_get(self, xml=SAMPLE_XML):
        class _Resp:
            text = xml

            def raise_for_status(self):
                pass

        return lambda url, params=None, timeout=None: _Resp()

    def test_returns_median_and_source(self):
        result = live_market_price(
            "관악구", deal_ym="202606", service_key="k", http_get=self._fake_get()
        )
        # 2.8억, 3.2억 → 중위 3.0억
        assert result["market_price_krw"] == 300_000_000
        assert result["source"]["lawd_cd"] == "11620"
        assert result["source"]["queried_at"]
        assert result["n"] == 2

    def test_unknown_region_raises(self):
        with pytest.raises(ValueError):
            live_market_price("제주시", deal_ym="202606", service_key="k", http_get=self._fake_get())

    def test_no_trades_raises(self):
        empty = "<response><body><items></items></body></response>"
        with pytest.raises(ValueError):
            live_market_price(
                "관악구", deal_ym="202606", service_key="k", http_get=self._fake_get(empty)
            )
