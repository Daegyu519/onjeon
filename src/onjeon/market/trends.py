"""시세 추이 오케스트레이터 — 캐시 우선, 없으면 fetch→평당가→저장→집계.

계단식 매물단위 좁히기(building→dong→sigungu): 대상 매물의 법정동(dong)·지번
(jibun)이 주어지면 가장 좁은 레벨(같은 건물)부터 시도해, 매매+전세 합산 버킷
수가 MIN_BUCKETS 이상이면 그 레벨을 채택한다. 데이터가 부족하면 한 단계씩
넓혀가며 "듬성듬성" 문제를 피하고, 어느 레벨의 데이터인지 level/level_label로
정직하게 표시한다. sigungu(필터 없음, 현행 동작)가 최종 폴백.
"""

from __future__ import annotations

import logging

import requests

from onjeon.data_pipeline.molit import fetch_deals
from onjeon.data_pipeline.regions import resolve_lawd_cd
from onjeon.market import cache as cache_mod
from onjeon.market.buckets import average_by_bucket, bucket_key
from onjeon.market.period import granularity_for, period_months
from onjeon.market.pyeong import price_per_pyeong
from onjeon.rules_io import load_rules

logger = logging.getLogger("onjeon.market")

_KINDS = {"mae_price": "trade", "jun_price": "jeonse", "wolse_price": "wolse"}

MIN_BUCKETS = 3


def _ensure_cached(conn, region, btype, kind, months, queried_at, **fetch_kw):
    for ym in months:
        if cache_mod.is_month_fetched(conn, region, btype, kind, ym):
            continue
        raw = fetch_deals(region, ym, btype, kind, **fetch_kw)
        deals = [{"deal_date": d["deal_date"],
                  "pyeong_krw": price_per_pyeong(d["amount_krw"], d["area_m2"]),
                  "dong": d["dong"],
                  "jibun": d["jibun"],
                  "area_m2": d["area_m2"]}
                 for d in raw if d["area_m2"] > 0]
        cache_mod.save_month(conn, region, btype, kind, ym, deals, queried_at)


def _filter(deals: list[dict], level: str, dong: str | None, jibun: str | None) -> list[dict]:
    """레벨별 거래 필터. 면적으로는 걸지 않는다(평당가로 이미 크기 정규화됨)."""
    if level == "building":
        return [d for d in deals if d.get("dong") == dong and d.get("jibun") == jibun]
    if level == "dong":
        return [d for d in deals if d.get("dong") == dong]
    if level == "sigungu":
        return deals
    raise ValueError(f"알 수 없는 level: {level!r}")


def _bucket_count(mae_deals: list[dict], jun_deals: list[dict], gran: str) -> int:
    """매매+전세 합산, 서로 다른 버킷(기간 단위) 수."""
    keys = {bucket_key(d["deal_date"], gran) for d in mae_deals}
    keys |= {bucket_key(d["deal_date"], gran) for d in jun_deals}
    return len(keys)


def _pick_level(mae_deals: list[dict], jun_deals: list[dict], dong: str | None,
                jibun: str | None, gran: str) -> str:
    """가장 좁은 레벨부터: 합산 버킷 수 >= MIN_BUCKETS면 채택. sigungu는 무조건 최종 폴백."""
    candidates = []
    if dong and jibun:
        candidates.append("building")
    if dong:
        candidates.append("dong")
    candidates.append("sigungu")

    for level in candidates:
        if level == "sigungu":
            return level
        mae_f = _filter(mae_deals, level, dong, jibun)
        jun_f = _filter(jun_deals, level, dong, jibun)
        if _bucket_count(mae_f, jun_f, gran) >= MIN_BUCKETS:
            return level
    return "sigungu"  # 방어적 폴백(candidates에 항상 sigungu가 있어 실제로는 도달하지 않음)


def _level_label(level: str, region: str, dong: str | None, jibun: str | None) -> str:
    if level == "building":
        return f"{dong} {jibun} 기준"
    if level == "dong":
        return f"{dong} 기준"
    return f"{region} 기준"


def market_trends(region, building_type, period, *, cache, today=None, queried_at,
                  service_key=None, http_get=None, retry_wait=None,
                  dong=None, jibun=None, conversion_rate=None) -> dict:
    """지역·용도·기간 → {dates, mae_price, jun_price, wolse_price, level, level_label}
    (매매·전세는 평당 만원 정수, 월세는 평당 환산월세 만원(소수1) — 결측 None).

    dong/jibun(대상 매물의 법정동·지번)을 주면 계단식으로 매물단위까지 좁힌다.
    기본값 None이면 필터 없음(sigungu, 기존 동작과 동일) — 하위호환.
    conversion_rate(전월세전환율) 미지정 시 market_params 룰에서 로드(월세 환산용).
    """
    region_code = resolve_lawd_cd(region)
    if region_code is None:
        raise ValueError(f"실거래가 자동 조회 미지원 지역: {region!r}")

    if conversion_rate is None:
        conversion_rate = load_rules("market_params")["jeonse_wolse_conversion_rate"]

    months = period_months(period, today)
    gran = granularity_for(period)
    fetch_kw = {"service_key": service_key, "retry_wait": retry_wait,
                "conversion_rate": conversion_rate}
    if http_get is not None:
        fetch_kw["http_get"] = http_get

    all_deals: dict[str, list[dict]] = {}
    unavailable: list[str] = []
    for out_key, kind in _KINDS.items():
        try:
            _ensure_cached(cache, region_code, building_type, kind, months, queried_at, **fetch_kw)
        except requests.RequestException as exc:
            # 예: 전세/아파트 엔드포인트 활용신청 미승인(403). 전체를 죽이지 않고
            # 해당 시리즈만 비우고 정직하게 unavailable로 표시한다.
            logger.warning("시세 조회 실패 kind=%s btype=%s: %r — 해당 시리즈 생략",
                           kind, building_type, exc)
            unavailable.append(out_key)
        all_deals[out_key] = cache_mod.load_deals(cache, region_code, building_type, kind, months)

    level = _pick_level(all_deals["mae_price"], all_deals["jun_price"], dong, jibun, gran)

    series = {}
    all_buckets: set[str] = set()
    for out_key, deals in all_deals.items():
        filtered = _filter(deals, level, dong, jibun)
        by_bucket = average_by_bucket(filtered, gran)
        if out_key == "wolse_price":
            # 환산월세는 월 flow(평당 수만원) — 만원 정수(//)로 나누면 0이 되므로 소수 1자리
            series[out_key] = {k: round(v["pyeong_krw"] / 10_000, 1) for k, v in by_bucket.items()}
        else:
            series[out_key] = {k: v["pyeong_krw"] // 10_000 for k, v in by_bucket.items()}
        all_buckets |= set(by_bucket)

    dates = sorted(all_buckets)
    return {
        "dates": dates,
        "mae_price": [series["mae_price"].get(d) for d in dates],
        "jun_price": [series["jun_price"].get(d) for d in dates],
        "wolse_price": [series["wolse_price"].get(d) for d in dates],
        "level": level,
        "level_label": _level_label(level, region, dong, jibun),
        "unavailable": unavailable,
        "conversion_rate": conversion_rate,
    }
