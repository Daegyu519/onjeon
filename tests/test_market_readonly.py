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
