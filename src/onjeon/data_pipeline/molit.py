"""국토부 실거래가 API 클라이언트 (공공데이터포털).

수집 방향은 docs/data-pipeline.md 참조. 원칙:
- 금액은 원(₩) 정수로 변환해 저장 (API 응답은 만원 단위 문자열)
- 모든 조회 결과에 조회 기준일(queried_at)·지역코드·계약년월을 함께 저장
- HTTP는 주입 가능(http_get) — 테스트는 네트워크 없이 수행

엔드포인트·서비스키: 공공데이터포털(data.go.kr) 가입 후 발급,
.env의 MOLIT_API_KEY에 저장. [확인: 연립다세대 매매 실거래가 API 최신 스펙]
"""

from __future__ import annotations

import os
import statistics
import xml.etree.ElementTree as ET
from datetime import date

import requests

# 연립다세대(빌라) 매매 실거래가 — 오피스텔/전월세는 자매 엔드포인트 [확인]
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


def fetch_trades(
    lawd_cd: str,
    deal_ym: str,
    *,
    service_key: str | None = None,
    endpoint: str = DEFAULT_ENDPOINT,
    http_get=requests.get,
) -> dict:
    """실거래가 조회. 반환에 조회 기준 메타데이터(source)를 반드시 포함한다.

    lawd_cd: 법정동 시군구 코드 5자리 (예: 관악구 11620)
    deal_ym: 계약년월 YYYYMM
    """
    key = service_key or os.environ.get("MOLIT_API_KEY")
    if not key:
        raise ValueError("MOLIT_API_KEY가 없다 — .env에 공공데이터포털 서비스키를 설정하라")
    response = http_get(
        endpoint,
        params={"serviceKey": key, "LAWD_CD": lawd_cd, "DEAL_YMD": deal_ym, "numOfRows": "1000"},
        timeout=15,
    )
    response.raise_for_status()
    return {
        "trades": parse_trades(response.text),
        "source": {
            "api": "국토부 실거래가 (RTMSDataSvcRHTrade)",
            "lawd_cd": lawd_cd,
            "deal_ym": deal_ym,
            "queried_at": date.today().isoformat(),
        },
    }
