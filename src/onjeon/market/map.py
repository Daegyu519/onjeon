"""동네별 평당가 집계 — 시세 추이를 시간축에서 공간축으로 뒤집은 것.

trends.market_trends가 (지역·유형·기간) → 시간 버킷별 평균이라면, 여기는 같은
캐시를 (유형·기간·거래종류) → 서울 전체 법정동별 평균으로 묶는다. 새 수식은 없고
GROUP BY 축만 다르다. 좌표는 dong_geo에서 조인한다(scripts/geocode_dongs.py가 채움).

읽기 전용이다 — 외부 국토부 API를 호출하지 않는다. 지도는 서울 25구 전체를 한 번에
보여주는데, 캐시 미스마다 fetch를 걸면 요청 하나가 수천 회 외부 호출이 된다.
빈 곳은 '거래 없음'이 아니라 '아직 워밍 안 됨'일 수 있고, 그건 cache_only와 같은
방식으로 정직하게 표시한다.
"""

from __future__ import annotations

from onjeon.data_pipeline.regions import SEOUL_LAWD_CD
from onjeon.market.cache import load_dong_geo
from onjeon.market.period import period_months

# 프론트 지표 키 → 캐시의 deal_kind. trends._KINDS와 같은 대응이되 방향이 반대다.
KINDS = {"mae": "trade", "jun": "jeonse", "wolse": "wolse"}

# 이 건수 미만인 동은 평균을 내지 않는다(price=None). 2건짜리 평균을 19,327건짜리와
# 같은 색으로 칠하면 데이터가 없다는 사실이 색에 가려진다 — CLAUDE.md 원칙 5.
MIN_DEALS = 5

_CODE_TO_GU = {code: gu for gu, code in SEOUL_LAWD_CD.items()}


def _to_man(pyeong_krw: float, kind: str) -> float | int:
    """평당가(원) → 만원. 환산월세는 월 flow라 정수화하면 0이 되므로 소수 1자리.

    trends.market_trends와 같은 규칙 — 두 엔드포인트의 단위가 어긋나면 프론트가
    같은 지표를 두 방식으로 다뤄야 한다.
    """
    if kind == "wolse":
        return round(pyeong_krw / 10_000, 1)
    return int(pyeong_krw // 10_000)


def market_map(conn, building_type: str, period: str, metric: str, *,
               today: str | None = None, min_deals: int = MIN_DEALS) -> dict:
    """(유형·기간·지표) → 법정동별 평당가 포인트 목록.

    반환 point: {region, dong, lat, lng, price, n}
      price — 만원(매매·전세는 정수, 환산월세는 소수1). 거래 min_deals 미만이면 None.
      n     — 해당 기간 거래 건수. price가 None이어도 '얼마나 희소한지'는 보여준다.

    좌표가 없는 동은 목록에서 빠지고 missing_geo에 개수로 집계된다 — 조용히
    사라지면 지도가 실제보다 촘촘해 보인다.
    """
    if metric not in KINDS:
        raise ValueError(f"알 수 없는 지표: {metric!r} (mae|jun|wolse)")
    kind = KINDS[metric]
    months = period_months(period, today)  # period 검증도 겸한다

    placeholders = ",".join("?" * len(months))
    rows = conn.execute(
        f"SELECT region_code, dong, AVG(pyeong_krw), COUNT(*) FROM deal_cache "
        f"WHERE building_type=? AND deal_kind=? AND ym IN ({placeholders}) "
        f"GROUP BY region_code, dong",
        (building_type, kind, *months),
    ).fetchall()

    geo = load_dong_geo(conn)
    points, missing_geo = [], 0
    for code, dong, avg_krw, n in rows:
        coord = geo.get((code, dong))
        if coord is None:
            missing_geo += 1
            continue
        points.append({
            "region": _CODE_TO_GU.get(code, code),
            "dong": dong,
            "lat": coord[0],
            "lng": coord[1],
            "price": _to_man(avg_krw, kind) if n >= min_deals else None,
            "n": n,
        })
    points.sort(key=lambda p: (p["region"], p["dong"]))
    return {
        "points": points,
        "metric": metric,
        "unit": "만원/평·월" if kind == "wolse" else "만원/평",
        "min_deals": min_deals,
        "missing_geo": missing_geo,
        "cache_only": True,
    }
