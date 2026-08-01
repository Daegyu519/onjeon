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

from onjeon.data_pipeline.molit import fetch_deals, fetch_rent_deals
from onjeon.data_pipeline.regions import resolve_lawd_cd
from onjeon.market import cache as cache_mod
from onjeon.market.buckets import average_by_bucket, bucket_key
from onjeon.market.period import granularity_for, period_months
from onjeon.market.pyeong import price_per_pyeong
from onjeon.rules_io import load_rules

logger = logging.getLogger("onjeon.market")

_KINDS = {"mae_price": "trade", "jun_price": "jeonse", "wolse_price": "wolse"}

MIN_BUCKETS = 3


def _to_cache_rows(raw: list[dict]) -> list[dict]:
    """fetch 결과 → 캐시 행(평당가 환산). 면적 0 이하는 버린다(평당가 계산 불가)."""
    return [{"deal_date": d["deal_date"],
             "pyeong_krw": price_per_pyeong(d["amount_krw"], d["area_m2"]),
             "dong": d["dong"],
             "jibun": d["jibun"],
             "area_m2": d["area_m2"]}
            for d in raw if d["area_m2"] > 0]


def _ensure_cached(conn, region, btype, kind, months, queried_at, **fetch_kw):
    """kind('trade'|'jeonse'|'wolse')의 미캐시 월을 채운다.

    전세·월세는 같은 전월세 응답에서 갈라지므로 한 번 받을 때 둘 다 저장한다 —
    따로 호출하면 동일 XML을 두 번 받아 일일 쿼터를 두 배로 쓴다.
    """
    for ym in months:
        if cache_mod.is_month_fetched(conn, region, btype, kind, ym):
            continue
        if kind == "trade":
            rows = {"trade": _to_cache_rows(fetch_deals(region, ym, btype, "trade", **fetch_kw))}
        else:
            both = fetch_rent_deals(region, ym, btype, **fetch_kw)
            rows = {k: _to_cache_rows(v) for k, v in both.items()}
        for deal_kind, deals in rows.items():
            cache_mod.save_month(conn, region, btype, deal_kind, ym, deals, queried_at)


def _filter(deals: list[dict], level: str, dong: str | None, jibun: str | None) -> list[dict]:
    """레벨별 거래 필터. 면적으로는 걸지 않는다(평당가로 이미 크기 정규화됨)."""
    if level == "building":
        return [d for d in deals if d.get("dong") == dong and d.get("jibun") == jibun]
    if level == "dong":
        return [d for d in deals if d.get("dong") == dong]
    if level == "sigungu":
        return deals
    raise ValueError(f"알 수 없는 level: {level!r}")


def _bucket_count(deal_lists: list[list[dict]], gran: str) -> int:
    """주어진 거래 목록들을 합산했을 때 서로 다른 버킷(기간 단위) 수."""
    return len({bucket_key(d["deal_date"], gran) for deals in deal_lists for d in deals})


def _pick_level(deal_lists: list[list[dict]], dong: str | None,
                jibun: str | None, gran: str) -> str:
    """가장 좁은 레벨부터: 합산 버킷 수 >= MIN_BUCKETS면 채택. sigungu는 무조건 최종 폴백.

    어떤 거래 종류를 세느냐는 호출측이 정한다 — 용도가 다르기 때문이다(market_trends 참조).
    """
    candidates = []
    if dong and jibun:
        candidates.append("building")
    if dong:
        candidates.append("dong")
    candidates.append("sigungu")

    for level in candidates:
        if level == "sigungu":
            return level
        filtered = [_filter(deals, level, dong, jibun) for deals in deal_lists]
        if _bucket_count(filtered, gran) >= MIN_BUCKETS:
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
                  dong=None, jibun=None, conversion_rate=None,
                  allow_fetch=True) -> dict:
    """지역·용도·기간 → {dates, mae_price, jun_price, wolse_price, level, level_label,
    mae_level, mae_level_label} (매매·전세는 평당 만원 정수, 월세는 평당 환산월세
    만원(소수1) — 결측 None).

    레벨이 둘인 이유: level은 "이 화면에 추세선을 그릴 만큼 거래가 있는 가장 좁은
    범위"(3종 합산)이고, mae_level은 "이 매물의 매매 시세를 얼마나 좁혀 말할 수
    있는가"(매매만)다. 후자만 시세 추정·기대손실 밴드에 써야 한다.

    dong/jibun(대상 매물의 법정동·지번)을 주면 계단식으로 매물단위까지 좁힌다.
    기본값 None이면 필터 없음(sigungu, 기존 동작과 동일) — 하위호환.
    conversion_rate(전월세전환율) 미지정 시 market_params 룰에서 로드(월세 환산용).

    allow_fetch=False면 외부 실거래가 API를 호출하지 않고 캐시만 읽는다(읽기 전용).
    공개 배포에서 필요한 이유: 이 함수는 캐시 미스 시 (개월 × 3종)만큼 국토부 API를
    호출한다(5년=최대 183회). 인증 없는 공개 엔드포인트가 이 경로를 타면 누구나
    운영자의 실명 인증 서비스키 쿼터를 소진시킬 수 있다. 공개 경로는 읽기 전용으로
    두고, 캐시 워밍(scripts/warm_cache.py)만 호출 권한을 갖는다.
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
        if allow_fetch:
            try:
                _ensure_cached(cache, region_code, building_type, kind, months, queried_at,
                               **fetch_kw)
            except requests.RequestException as exc:
                # 예: 전세/아파트 엔드포인트 활용신청 미승인(403). 전체를 죽이지 않고
                # 해당 시리즈만 비우고 정직하게 unavailable로 표시한다.
                logger.warning("시세 조회 실패 kind=%s btype=%s: %r — 해당 시리즈 생략",
                               kind, building_type, exc)
                unavailable.append(out_key)
        all_deals[out_key] = cache_mod.load_deals(cache, region_code, building_type, kind, months)

    # 차트 레벨은 3종을 전부 센다. 매매+전세만 세면 월세 위주 건물이 동 평균으로
    # 희석된다(실측: 신림동 613-13은 월세 101건/44개월인데 전세 1건이라 dong으로
    # 떨어졌다) — 원룸 월세는 우리 타깃 매물이 정확히 그 패턴이다.
    level = _pick_level(list(all_deals.values()), dong, jibun, gran)
    # 시세 밴드 레벨은 매매만 세서 따로 뽑는다. api._estimate_price는 mae_price만 쓰는데
    # 거기에 차트 레벨을 주면 전세·월세 거래량이 매매 시세의 정밀도를 대신 주장하고,
    # 그 레벨이 decision._price_band로 들어가 E[Loss] 범위를 좁힌다(실측 1년 창:
    # 월세를 세면 3,910개 지번의 밴드가 근거 없이 좁아졌고, 전세가 끌어올리던
    # 5,586개는 원래부터 근거가 없었다).
    mae_level = _pick_level([all_deals["mae_price"]], dong, jibun, gran)

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
        # 매매 시세 추정 전용 — 차트 레벨과 다를 수 있다(위 주석)
        "mae_level": mae_level,
        "mae_level_label": _level_label(mae_level, region, dong, jibun),
        "unavailable": unavailable,
        # 읽기 전용 응답임을 명시 — 빈 구간이 '거래 없음'이 아니라 '아직 워밍 안 됨'일 수 있다
        "cache_only": not allow_fetch,
        "conversion_rate": conversion_rate,
    }
