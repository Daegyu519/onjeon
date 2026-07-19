"""국토부 실거래가 API 클라이언트 (공공데이터포털).

수집 방향은 docs/data-pipeline.md 참조. 원칙:
- 금액은 원(₩) 정수로 변환해 저장 (API 응답은 만원 단위 문자열)
- 모든 조회 결과에 조회 기준일(queried_at)·지역코드·계약년월을 함께 저장
- HTTP는 주입 가능(http_get) — 테스트는 네트워크 없이 수행
- 재시도는 일시 장애만: Timeout·ConnectionError·HTTP 5xx (총 3회, 지수 백오프).
  4xx는 요청 자체가 잘못된 것이므로 즉시 실패. wait는 주입 가능(retry_wait).

엔드포인트·서비스키: 공공데이터포털(data.go.kr) 가입 후 발급,
.env의 MOLIT_API_KEY에 저장.
스펙 검증 완료: 2026-07-19 실키 호출 — 관악구(11620) 2026-06 매매 154건 수신,
영문 태그(dealAmount 등) 파싱 확인.
"""

from __future__ import annotations

import logging
import os
import statistics
import xml.etree.ElementTree as ET
from datetime import date

import requests
from tenacity import Retrying, retry_if_exception, stop_after_attempt, wait_exponential

logger = logging.getLogger("onjeon.data_pipeline")

# 연립다세대(빌라) 매매 실거래가 (2026-07-19 실검증) — 오피스텔/전월세는 자매 엔드포인트
DEFAULT_ENDPOINT = "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade"

# 신형(영문)·구형(국문) 응답 태그 모두 수용
_TAGS = {
    "amount": ("dealAmount", "거래금액"),
    "area": ("excluUseAr", "전용면적"),
    "floor": ("floor", "층"),
    "year": ("dealYear", "년"),
    "month": ("dealMonth", "월"),
    "day": ("dealDay", "일"),
    "dong": ("umdNm", "법정동"),
    "build_year": ("buildYear", "건축년도"),
}


def _find(item: ET.Element, key: str) -> str:
    for tag in _TAGS[key]:
        node = item.find(tag)
        if node is not None and node.text:
            return node.text.strip()
    return ""


def parse_trades(xml_text: str) -> list[dict]:
    """API 응답 XML → 거래 목록. 거래금액 '15,000'(만원) → 150_000_000(원)."""
    root = ET.fromstring(xml_text)
    trades = []
    for item in root.iter("item"):
        amount_man = _find(item, "amount").replace(",", "")
        year, month, day = _find(item, "year"), _find(item, "month"), _find(item, "day")
        trades.append(
            {
                "price_krw": int(amount_man) * 10_000,
                "area_m2": float(_find(item, "area") or 0),
                "floor": int(_find(item, "floor") or 0),
                "deal_date": f"{year}-{int(month):02d}-{int(day):02d}",
                "dong": _find(item, "dong"),
                "build_year": int(_find(item, "build_year") or 0),
            }
        )
    return trades


def median_price_krw(trades: list[dict]) -> int:
    """거래 목록의 중위 가격(원). L3 시세 입력으로 쓰는 보수적 대표값."""
    if not trades:
        raise ValueError("거래 데이터가 비어 있다 — 시세를 추정할 수 없음")
    return int(statistics.median(t["price_krw"] for t in trades))


def _is_retryable(exc: BaseException) -> bool:
    """일시 장애만 재시도 대상 — Timeout·ConnectionError·HTTP 5xx. 4xx는 즉시 실패."""
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError):
        response = getattr(exc, "response", None)
        return response is not None and 500 <= response.status_code < 600
    return False


def _warn_before_retry(retry_state) -> None:
    logger.warning(
        "실거래가 조회 재시도 대기 (시도 %d회 실패) — 원인: %r",
        retry_state.attempt_number,
        retry_state.outcome.exception(),
    )


def live_market_price(
    region: str,
    *,
    deal_ym: str | None = None,
    service_key: str | None = None,
    http_get=requests.get,
    retry_wait=None,
) -> dict:
    """지역명 → 실거래가 중위 시세(원). L3/앱이 소비하는 실데이터 시세 진입점.

    지역을 시군구 코드로 해석(서울 25구)한 뒤 실거래가를 조회해 중위가를 낸다.
    미지원 지역·거래 0건이면 ValueError(호출측이 수동 입력으로 폴백).
    """
    from onjeon.data_pipeline.regions import recent_deal_ym, resolve_lawd_cd

    lawd_cd = resolve_lawd_cd(region)
    if lawd_cd is None:
        raise ValueError(f"실거래가 자동 조회 미지원 지역: {region!r} (서울 25구만 커버)")
    result = fetch_trades(
        lawd_cd,
        deal_ym or recent_deal_ym(),
        service_key=service_key,
        http_get=http_get,
        retry_wait=retry_wait,
    )
    trades = result["trades"]
    return {
        "market_price_krw": median_price_krw(trades),
        "n": len(trades),
        "source": result["source"],
    }


def fetch_trades(
    lawd_cd: str,
    deal_ym: str,
    *,
    service_key: str | None = None,
    endpoint: str = DEFAULT_ENDPOINT,
    http_get=requests.get,
    retry_wait=None,
) -> dict:
    """실거래가 조회. 반환에 조회 기준 메타데이터(source)를 반드시 포함한다.

    lawd_cd: 법정동 시군구 코드 5자리 (예: 관악구 11620)
    deal_ym: 계약년월 YYYYMM
    retry_wait: tenacity wait 전략 주입 (기본 지수 백오프 multiplier=0.5,
        테스트는 wait_none()으로 대기 없이 검증)
    """
    key = service_key or os.environ.get("MOLIT_API_KEY")
    if not key:
        raise ValueError("MOLIT_API_KEY가 없다 — .env에 공공데이터포털 서비스키를 설정하라")

    def _request():
        try:
            response = http_get(
                endpoint,
                params={
                    "serviceKey": key,
                    "LAWD_CD": lawd_cd,
                    "DEAL_YMD": deal_ym,
                    "numOfRows": "1000",
                },
                timeout=15,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            # requests 예외 메시지엔 URL(serviceKey 포함)이 들어간다 — 키 마스킹.
            # 같은 타입으로 재던져 재시도 판별(_is_retryable)을 보존한다.
            sanitized = str(exc).replace(key, "***")
            raise type(exc)(sanitized, response=getattr(exc, "response", None)) from None
        return response

    retryer = Retrying(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=retry_wait if retry_wait is not None else wait_exponential(multiplier=0.5),
        before_sleep=_warn_before_retry,
        reraise=True,  # 소진 시 RetryError 대신 원래 예외를 그대로 던진다
    )
    response = retryer(_request)
    trades = parse_trades(response.text)
    queried_at = date.today().isoformat()
    logger.info(
        "실거래가 조회 성공 lawd_cd=%s deal_ym=%s 건수=%d queried_at=%s",
        lawd_cd,
        deal_ym,
        len(trades),
        queried_at,
    )
    return {
        "trades": trades,
        "source": {
            "api": "국토부 실거래가 (RTMSDataSvcRHTrade)",
            "lawd_cd": lawd_cd,
            "deal_ym": deal_ym,
            "queried_at": queried_at,
        },
    }
