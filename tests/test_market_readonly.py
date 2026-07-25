"""공개 배포 읽기 전용 경계 — allow_fetch=False면 외부 API를 호출하지 않는다.

이 테스트가 지키는 것: 공개 엔드포인트가 외부 국토부 API를 타면 인증 없이
운영자 서비스키 쿼터를 소진시킬 수 있다(1요청 최대 183회). 회귀하면 즉시 실패한다.
"""

from __future__ import annotations

from onjeon.market import cache as cache_mod
from onjeon.market.pyeong import price_per_pyeong
from onjeon.market.trends import market_trends


def _boom(*args, **kwargs):  # 호출되면 테스트 실패
    raise AssertionError("읽기 전용인데 외부 API를 호출했다")


def _conn(tmp_path):
    return cache_mod.open_cache(tmp_path / "cache.db")


def test_readonly_never_fetches(tmp_path):
    """캐시가 비어도 외부 호출 없이 빈 시리즈를 반환한다(예외 아님)."""
    conn = _conn(tmp_path)
    try:
        res = market_trends("관악구", "rh", "1m", cache=conn, queried_at="2026-07-25",
                            http_get=_boom, service_key="x", allow_fetch=False)
    finally:
        conn.close()
    assert res["dates"] == []
    assert res["cache_only"] is True


def test_readonly_serves_cached_data(tmp_path):
    """캐시에 있으면 외부 호출 없이 그 데이터로 응답한다."""
    conn = _conn(tmp_path)
    try:
        deals = [{"deal_date": "2026-06-10",
                  "pyeong_krw": price_per_pyeong(300_000_000, 40.0),
                  "dong": "봉천동", "jibun": "100", "area_m2": 40.0}]
        # region_code(법정동코드)로 저장 — market_trends가 조회하는 키와 같아야 한다
        cache_mod.save_month(conn, "11620", "rh", "trade", "202606", deals, "2026-07-25")
        res = market_trends("관악구", "rh", "1m", cache=conn, queried_at="2026-07-25",
                            http_get=_boom, service_key="x", allow_fetch=False,
                            today="2026-07-25")
    finally:
        conn.close()
    assert res["dates"], "캐시된 달이 응답에 나와야 한다"
    assert any(v is not None for v in res["mae_price"])
    assert res["cache_only"] is True


_RENT_XML = """<response><body><items>
<item><보증금액>20,000</보증금액><월세금액>550</월세금액><전용면적>40</전용면적>
 <년>2026</년><월>6</월><일>10</일><법정동> 봉천동 </법정동><지번>100</지번></item>
<item><보증금액>30,000</보증금액><월세금액>0</월세금액><전용면적>50</전용면적>
 <년>2026</년><월>6</월><일>11</일><법정동> 봉천동 </법정동><지번>101</지번></item>
</items></body></response>"""
_TRADE_XML = """<response><body><items>
<item><거래금액>50,000</거래금액><전용면적>60</전용면적>
 <년>2026</년><월>6</월><일>12</일><법정동> 봉천동 </법정동><지번>102</지번></item>
</items></body></response>"""


def test_rent_endpoint_called_once_per_month(tmp_path):
    """전세·월세는 같은 전월세 응답에서 갈라진다 — 월당 1회만 호출해야 한다.

    회귀하면 일일 쿼터를 두 배로 쓴다(서울 전 지역 워밍에서 1,300회 차이).
    """
    calls: list[str] = []

    def counting_get(url, **kwargs):
        calls.append(url)
        body = _TRADE_XML if "Trade" in url else _RENT_XML

        class Resp:
            status_code = 200
            text = body

            def raise_for_status(self):
                pass

        return Resp()

    conn = _conn(tmp_path)
    try:
        res = market_trends("관악구", "rh", "1m", cache=conn, queried_at="2026-07-25",
                            today="2026-07-25", http_get=counting_get, service_key="k",
                            retry_wait=0)
    finally:
        conn.close()

    rent = [c for c in calls if "Rent" in c]
    trade = [c for c in calls if "Trade" in c]
    assert len(rent) == len(trade), f"전월세 호출이 매매보다 많다(중복): rent={len(rent)} trade={len(trade)}"
    # 한 번 받은 응답에서 전세·월세가 모두 나와야 한다
    assert any(v is not None for v in res["jun_price"])
    assert any(v is not None for v in res["wolse_price"])


def test_allow_fetch_default_is_unchanged(tmp_path):
    """하위호환: 기본값은 종전처럼 조회를 시도한다(=_boom이 불린다)."""
    conn = _conn(tmp_path)
    try:
        try:
            market_trends("관악구", "rh", "1m", cache=conn, queried_at="2026-07-25",
                          http_get=_boom, service_key="x")
        except AssertionError as exc:
            assert "외부 API를 호출했다" in str(exc)
        else:
            raise AssertionError("기본값에서 조회를 시도하지 않았다")
    finally:
        conn.close()
