"""시세 추이 오케스트레이터 — 캐시 우선, 없으면 fetch→평당가→저장→집계."""

from __future__ import annotations

from onjeon.data_pipeline.molit import fetch_deals
from onjeon.data_pipeline.regions import resolve_lawd_cd
from onjeon.market import cache as cache_mod
from onjeon.market.buckets import average_by_bucket
from onjeon.market.period import granularity_for, period_months
from onjeon.market.pyeong import price_per_pyeong

_KINDS = {"mae_price": "trade", "jun_price": "jeonse"}


def _ensure_cached(conn, region, btype, kind, months, queried_at, **fetch_kw):
    for ym in months:
        if cache_mod.is_month_fetched(conn, region, btype, kind, ym):
            continue
        raw = fetch_deals(region, ym, btype, kind, **fetch_kw)
        deals = [{"deal_date": d["deal_date"],
                  "pyeong_krw": price_per_pyeong(d["amount_krw"], d["area_m2"])}
                 for d in raw if d["area_m2"] > 0]
        cache_mod.save_month(conn, region, btype, kind, ym, deals, queried_at)


def market_trends(region, building_type, period, *, cache, today=None, queried_at,
                  service_key=None, http_get=None, retry_wait=None) -> dict:
    """지역·용도·기간 → {dates, mae_price, jun_price}(평당 만원, 결측 None)."""
    region_code = resolve_lawd_cd(region)
    if region_code is None:
        raise ValueError(f"실거래가 자동 조회 미지원 지역: {region!r}")

    months = period_months(period, today)
    gran = granularity_for(period)
    fetch_kw = {"service_key": service_key, "retry_wait": retry_wait}
    if http_get is not None:
        fetch_kw["http_get"] = http_get

    series = {}
    all_buckets: set[str] = set()
    for out_key, kind in _KINDS.items():
        _ensure_cached(cache, region_code, building_type, kind, months, queried_at, **fetch_kw)
        deals = cache_mod.load_deals(cache, region_code, building_type, kind, months)
        by_bucket = average_by_bucket(deals, gran)
        series[out_key] = {k: v["pyeong_krw"] // 10_000 for k, v in by_bucket.items()}
        all_buckets |= set(by_bucket)

    dates = sorted(all_buckets)
    return {
        "dates": dates,
        "mae_price": [series["mae_price"].get(d) for d in dates],
        "jun_price": [series["jun_price"].get(d) for d in dates],
    }
