"""집계 레벨 선택 — 차트 레벨(3종 합산)과 시세 밴드 레벨(매매만)의 분리.

이 테스트가 지키는 것 두 가지:
1. 월세만 활발한 원룸 건물이 동 평균으로 희석되지 않는다(원룸 월세 = 타깃 매물).
2. 그 완화가 매매 시세 밴드로 새지 않는다 — mae_level은 매매 거래만 센다.
   레벨은 decision._price_band를 거쳐 E[Loss] 범위 폭이 되므로, 근거 없이
   좁아지면 위험이 실제보다 확실해 보인다(CLAUDE.md 원칙 5).
"""

from __future__ import annotations

import pytest

from onjeon.market import cache as cache_mod
from onjeon.market.trends import market_trends

REGION_CODE = "11620"  # 관악구
DONG, JIBUN = "봉천동", "100"


def _deal(ym_day: str, jibun: str = JIBUN) -> dict:
    return {"deal_date": ym_day, "pyeong_krw": 30_000_000,
            "dong": DONG, "jibun": jibun, "area_m2": 40.0}


@pytest.fixture
def conn(tmp_path):
    c = cache_mod.open_cache(tmp_path / "cache.db")
    yield c
    c.close()


def _save(conn, kind: str, dates: list[str], jibun: str = JIBUN) -> None:
    """월별로 묶어 저장. deal_cache는 (종류, ym) 단위라 ym이 섞이면 덮어써진다."""
    by_ym: dict[str, list[dict]] = {}
    for d in dates:
        by_ym.setdefault(d[:4] + d[5:7], []).append(_deal(d, jibun))
    for ym, deals in by_ym.items():
        cache_mod.save_month(conn, REGION_CODE, "rh", kind, ym, deals, "2026-07-25")


def _run(conn):
    return market_trends("관악구", "rh", "1y", cache=conn, queried_at="2026-07-25",
                         today="2026-07-25", allow_fetch=False, dong=DONG, jibun=JIBUN)


def test_wolse_only_building_is_not_diluted_to_dong(conn):
    """월세 3개월 + 전세 1건뿐이어도 차트는 건물 단위로 그린다.

    실측 사례(신림동 613-13): 월세 101건/44개월, 전세 1건. 예전 로직은 매매+전세만
    세서 dong으로 떨어뜨렸다 — 정작 이 건물을 보는 사람이 궁금한 건 월세다.
    """
    _save(conn, "wolse", ["2026-04-10", "2026-05-10", "2026-06-10"])
    _save(conn, "jeonse", ["2026-06-11"])
    assert _run(conn)["level"] == "building"


def test_mae_level_ignores_wolse(conn):
    """같은 상황에서 시세 밴드 레벨은 building이 아니다 — 매매 거래가 0건이다."""
    _save(conn, "wolse", ["2026-04-10", "2026-05-10", "2026-06-10"])
    _save(conn, "jeonse", ["2026-06-11"])
    res = _run(conn)
    assert res["level"] == "building"
    # 매매가 building에서도 dong에서도 3버킷을 못 채우니 구 단위까지 떨어진다 — 가장 넓은 밴드
    assert res["mae_level"] == "sigungu", "월세 거래량이 매매 시세의 정밀도를 주장하면 안 된다"


def test_mae_level_ignores_jeonse(conn):
    """전세도 마찬가지 — 이건 월세 포함 이전부터 있던 결함이다.

    매매 1개월 + 전세 2개월이면 예전 로직은 합산 3버킷으로 building을 줬다.
    시세는 mae_price에서만 나오는데 밴드는 전세 덕에 좁아지던 셈이다.
    """
    _save(conn, "trade", ["2026-06-12"])
    _save(conn, "jeonse", ["2026-05-10", "2026-04-10"])
    res = _run(conn)
    assert res["level"] == "building"
    assert res["mae_level"] == "sigungu"


def test_mae_level_building_when_mae_itself_has_support(conn):
    """매매가 스스로 3개월치를 채우면 밴드도 건물 단위를 받는다(과잉 보수화 방지)."""
    _save(conn, "trade", ["2026-04-12", "2026-05-12", "2026-06-12"])
    res = _run(conn)
    assert res["level"] == "building"
    assert res["mae_level"] == "building"
    assert res["mae_level_label"] == f"{DONG} {JIBUN} 기준"


def test_other_building_deals_do_not_count(conn):
    """같은 동 다른 지번의 거래는 building 레벨을 채워주지 않는다(필터 회귀 방지)."""
    _save(conn, "wolse", ["2026-04-10", "2026-05-10", "2026-06-10"], jibun="999")
    res = _run(conn)
    assert res["level"] == "dong"
    assert res["mae_level"] == "sigungu"
