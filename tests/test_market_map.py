"""동네 지도 집계 — 희소 표본 가드와 구별 좌표 분리.

이 테스트가 지키는 것 두 가지:
1) 거래 몇 건뿐인 동의 평균이 색으로 칠해지면, 데이터가 없다는 사실이 색에 가려진다.
2) 동 이름은 구 사이에서 중복된다(신사동=강남구·관악구). 좌표 조인이 이름만 보면
   강남 신사동 가격이 관악 신사동 자리에 찍힌다.
"""

from __future__ import annotations

import pytest

from onjeon.market import cache as cache_mod
from onjeon.market.map import MIN_DEALS, market_map
from scripts.geocode_dongs import geocode

TODAY = "2026-07-25"
GANGNAM, GWANAK = "11680", "11620"


def _deal(dong, pyeong_krw, jibun="1"):
    return {"deal_date": "2026-06-10", "pyeong_krw": pyeong_krw,
            "dong": dong, "jibun": jibun, "area_m2": 40.0}


def _conn(tmp_path):
    return cache_mod.open_cache(tmp_path / "cache.db")


def test_sparse_dong_gets_no_price_but_keeps_count(tmp_path):
    """MIN_DEALS 미만이면 price=None, n은 그대로 — '적다'는 사실을 숨기지 않는다."""
    conn = _conn(tmp_path)
    try:
        cache_mod.save_dong_geo(conn, GWANAK, "봉천동", 37.475, 126.957, TODAY)
        cache_mod.save_month(conn, GWANAK, "rh", "trade", "202606",
                             [_deal("봉천동", 30_000_000)] * (MIN_DEALS - 1), TODAY)
        res = market_map(conn, "rh", "1m", "mae", today=TODAY)
    finally:
        conn.close()
    (point,) = res["points"]
    assert point["price"] is None
    assert point["n"] == MIN_DEALS - 1


def test_enough_deals_gets_price_in_man(tmp_path):
    """MIN_DEALS 이상이면 평당가를 만원 정수로 준다."""
    conn = _conn(tmp_path)
    try:
        cache_mod.save_dong_geo(conn, GWANAK, "봉천동", 37.475, 126.957, TODAY)
        cache_mod.save_month(conn, GWANAK, "rh", "trade", "202606",
                             [_deal("봉천동", 30_000_000)] * MIN_DEALS, TODAY)
        res = market_map(conn, "rh", "1m", "mae", today=TODAY)
    finally:
        conn.close()
    (point,) = res["points"]
    assert point["price"] == 3000  # 30,000,000원/평 → 3,000만원/평
    assert point["region"] == "관악구"


def test_same_dong_name_in_two_gu_keeps_own_coords(tmp_path):
    """신사동은 강남구·관악구 양쪽에 있다 — 좌표가 서로 섞이면 안 된다."""
    conn = _conn(tmp_path)
    try:
        cache_mod.save_dong_geo(conn, GANGNAM, "신사동", 37.5223, 127.0277, TODAY)
        cache_mod.save_dong_geo(conn, GWANAK, "신사동", 37.4800, 126.9300, TODAY)
        for code, price in ((GANGNAM, 90_000_000), (GWANAK, 30_000_000)):
            cache_mod.save_month(conn, code, "rh", "trade", "202606",
                                 [_deal("신사동", price)] * MIN_DEALS, TODAY)
        res = market_map(conn, "rh", "1m", "mae", today=TODAY)
    finally:
        conn.close()
    by_gu = {p["region"]: p for p in res["points"]}
    assert by_gu["강남구"]["lat"] == pytest.approx(37.5223)
    assert by_gu["관악구"]["lat"] == pytest.approx(37.4800)
    assert by_gu["강남구"]["price"] == 9000
    assert by_gu["관악구"]["price"] == 3000


def test_dong_without_coords_is_counted_not_dropped_silently(tmp_path):
    """좌표 없는 동은 목록에서 빠지되 missing_geo로 드러난다."""
    conn = _conn(tmp_path)
    try:
        cache_mod.save_month(conn, GWANAK, "rh", "trade", "202606",
                             [_deal("봉천동", 30_000_000)] * MIN_DEALS, TODAY)
        res = market_map(conn, "rh", "1m", "mae", today=TODAY)
    finally:
        conn.close()
    assert res["points"] == []
    assert res["missing_geo"] == 1


def test_wolse_keeps_one_decimal(tmp_path):
    """환산월세는 평당 수만원이라 만원 정수화하면 0이 된다 — trends와 같은 규칙."""
    conn = _conn(tmp_path)
    try:
        cache_mod.save_dong_geo(conn, GWANAK, "봉천동", 37.475, 126.957, TODAY)
        cache_mod.save_month(conn, GWANAK, "rh", "wolse", "202606",
                             [_deal("봉천동", 85_000)] * MIN_DEALS, TODAY)
        res = market_map(conn, "rh", "1m", "wolse", today=TODAY)
    finally:
        conn.close()
    assert res["points"][0]["price"] == 8.5
    assert res["unit"] == "만원/평·월"


def test_unknown_metric_rejected(tmp_path):
    conn = _conn(tmp_path)
    try:
        with pytest.raises(ValueError):
            market_map(conn, "rh", "1m", "매매가", today=TODAY)
    finally:
        conn.close()


def test_market_map_never_fetches(tmp_path, monkeypatch):
    """지도는 서울 전체를 한 번에 본다 — 캐시 미스마다 fetch면 요청 1건이 수천 회 외부 호출."""
    import onjeon.data_pipeline.molit as molit

    def _boom(*args, **kwargs):
        raise AssertionError("지도 집계가 외부 API를 호출했다")

    monkeypatch.setattr(molit, "fetch_deals", _boom)
    monkeypatch.setattr(molit, "fetch_rent_deals", _boom)
    conn = _conn(tmp_path)
    try:
        res = market_map(conn, "rh", "5y", "mae", today=TODAY)
    finally:
        conn.close()
    assert res["points"] == []
    assert res["cache_only"] is True


def test_geocode_rejects_wrong_gu():
    """동 이름이 같아도 응답의 구가 다르면 버린다 — 관악 신사동 질의에 강남 신사동 응답."""
    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return '[{"lat":"37.5223","lon":"127.0277","display_name":"신사동, 강남구, 서울특별시"}]'.encode()

    assert geocode("관악구", "신사동", opener=lambda *a, **k: _Resp()) is None
    assert geocode("강남구", "신사동", opener=lambda *a, **k: _Resp()) == (37.5223, 127.0277)
