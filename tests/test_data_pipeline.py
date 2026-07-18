"""데이터 수집 파이프라인 테스트 — 실거래가 API 파싱 + 낙찰가율 룰 생성기.

네트워크 없이 검증한다: HTTP는 주입(fake) / 파싱은 고정 XML 픽스처.
"""

import json

import pytest

from onjeon.data_pipeline.auction_rates import build_auction_rates, write_auction_rules
from onjeon.data_pipeline.molit import fetch_trades, median_price_krw, parse_trades

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response>
  <header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
  <body>
    <items>
      <item>
        <dealAmount>15,000</dealAmount><excluUseAr>29.75</excluUseAr><floor>3</floor>
        <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>12</dealDay>
        <umdNm>봉천동</umdNm><buildYear>2015</buildYear>
      </item>
      <item>
        <dealAmount>16,500</dealAmount><excluUseAr>31.20</excluUseAr><floor>2</floor>
        <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>3</dealDay>
        <umdNm>봉천동</umdNm><buildYear>2018</buildYear>
      </item>
    </items>
    <totalCount>2</totalCount>
  </body>
</response>"""


class TestParseTrades:
    def test_parses_items(self):
        trades = parse_trades(SAMPLE_XML)
        assert len(trades) == 2

    def test_price_converted_man_to_won_integer(self):
        # API의 거래금액은 만원 단위 문자열("15,000") — 원(₩) 정수로 변환 (CLAUDE.md)
        trades = parse_trades(SAMPLE_XML)
        assert trades[0]["price_krw"] == 150_000_000
        assert isinstance(trades[0]["price_krw"], int)

    def test_deal_date_zero_padded(self):
        trades = parse_trades(SAMPLE_XML)
        assert trades[0]["deal_date"] == "2026-06-12"
        assert trades[1]["deal_date"] == "2026-06-03"

    def test_median_even_count(self):
        trades = parse_trades(SAMPLE_XML)
        assert median_price_krw(trades) == 157_500_000

    def test_median_empty_raises(self):
        with pytest.raises(ValueError):
            median_price_krw([])


class TestFetchTrades:
    def test_requires_service_key(self, monkeypatch):
        monkeypatch.delenv("MOLIT_API_KEY", raising=False)
        with pytest.raises(ValueError):
            fetch_trades("11620", "202606")

    def test_fetch_returns_trades_with_source_metadata(self):
        class FakeResponse:
            text = SAMPLE_XML

            def raise_for_status(self):
                pass

        captured = {}

        def fake_get(url, params=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

        result = fetch_trades("11620", "202606", service_key="test-key", http_get=fake_get)
        assert len(result["trades"]) == 2
        assert result["source"]["lawd_cd"] == "11620"
        assert result["source"]["deal_ym"] == "202606"
        assert result["source"]["queried_at"]  # 조회 기준일 필수 (CLAUDE.md)
        assert captured["params"]["LAWD_CD"] == "11620"


class TestAuctionRatesBuilder:
    ROWS = [
        {"region": "관악구", "building_type": "빌라", "rate": 0.78},
        {"region": "관악구", "building_type": "오피스텔", "rate": 0.85},
        {"region": "default", "building_type": "빌라", "rate": 0.75},
    ]

    def test_builds_rules_shape(self):
        rules = build_auction_rates(
            self.ROWS, version="2026-08", source="법원경매정보", queried_at="2026-08-01"
        )
        assert rules["version"] == "2026-08"
        assert rules["rates"]["관악구"]["빌라"] == 0.78
        assert rules["queried_at"] == "2026-08-01"

    def test_missing_default_region_raises(self):
        rows = [r for r in self.ROWS if r["region"] != "default"]
        with pytest.raises(ValueError):
            build_auction_rates(rows, version="2026-08", source="s", queried_at="d")

    def test_write_creates_versioned_file(self, tmp_path):
        rules = build_auction_rates(
            self.ROWS, version="2026-08", source="법원경매정보", queried_at="2026-08-01"
        )
        path = write_auction_rules(rules, rules_dir=tmp_path)
        assert path.name == "auction_rates_2026-08.json"
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["rates"]["default"]["빌라"] == 0.75
