"""데이터 수집 파이프라인 테스트 — 실거래가 API 파싱 + 낙찰가율 룰 생성기.

네트워크 없이 검증한다: HTTP는 주입(fake) / 파싱은 고정 XML 픽스처.
재시도는 tenacity wait 주입(wait_none)으로 대기 없이 검증한다.
"""

import json
import logging

import pytest
import requests
from tenacity import wait_none

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


class _OkResponse:
    text = SAMPLE_XML

    def raise_for_status(self):
        pass


class _FlakyHTTP:
    """지정된 예외를 순서대로 던진 뒤 성공하는 fake http_get — 호출 횟수 기록."""

    def __init__(self, failures):
        self.failures = list(failures)
        self.calls = 0

    def __call__(self, url, params=None, timeout=None):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return _OkResponse()


def _http_error(status: int) -> requests.HTTPError:
    class _Resp:
        status_code = status

    return requests.HTTPError(f"{status} error", response=_Resp())


class TestFetchTradesRetry:
    def _fetch(self, http_get):
        return fetch_trades(
            "11620", "202606", service_key="test-key", http_get=http_get, retry_wait=wait_none()
        )

    def test_5xx_retried_twice_then_success(self):
        fake = _FlakyHTTP([_http_error(500), _http_error(503)])
        result = self._fetch(fake)
        assert fake.calls == 3
        assert len(result["trades"]) == 2
        assert result["source"]["queried_at"]

    def test_4xx_fails_immediately_without_retry(self):
        fake = _FlakyHTTP([_http_error(404)])
        with pytest.raises(requests.HTTPError):
            self._fetch(fake)
        assert fake.calls == 1

    def test_timeout_retried_then_success(self):
        fake = _FlakyHTTP([requests.Timeout("timeout"), requests.ConnectionError("refused")])
        result = self._fetch(fake)
        assert fake.calls == 3
        assert len(result["trades"]) == 2

    def test_exhausted_retries_reraise_original_error(self):
        fake = _FlakyHTTP([_http_error(500)] * 3)
        with pytest.raises(requests.HTTPError):  # RetryError로 감싸지 않는다 (reraise)
            self._fetch(fake)
        assert fake.calls == 3

    def test_success_logs_query_metadata(self, caplog):
        with caplog.at_level(logging.INFO, logger="onjeon.data_pipeline"):
            self._fetch(_FlakyHTTP([]))
        joined = " ".join(rec.getMessage() for rec in caplog.records)
        assert "11620" in joined and "202606" in joined
        assert "queried_at" in joined  # 조회 기준일 필수 (CLAUDE.md)

    def test_retry_logs_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="onjeon.data_pipeline"):
            self._fetch(_FlakyHTTP([_http_error(500)]))
        assert any(rec.levelno == logging.WARNING for rec in caplog.records)

    def test_http_error_message_does_not_leak_service_key(self):
        # requests의 HTTPError는 URL(serviceKey 포함)을 담는다 — 마스킹 필수
        class _Resp:
            status_code = 401

        def leaky_get(url, params=None, timeout=None):
            raise requests.HTTPError(
                f"401 Unauthorized for url: {url}?serviceKey={params['serviceKey']}",
                response=_Resp(),
            )

        with pytest.raises(requests.HTTPError) as excinfo:
            fetch_trades(
                "11620", "202606", service_key="super-secret-key",
                http_get=leaky_get, retry_wait=wait_none(),
            )
        assert "super-secret-key" not in str(excinfo.value)


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
