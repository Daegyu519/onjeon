"""지역명 → 법정동 시군구 코드(LAWD_CD) 매핑 + 계약년월 헬퍼.

실거래가 API는 5자리 시군구 코드를 요구한다. MVP는 서울 25개 구를 커버하고,
그 외 지역은 None(자동 조회 불가 → 수동 입력 폴백)으로 정직하게 처리한다.
"""

from __future__ import annotations

from datetime import date

# 서울특별시 25개 자치구 법정동 시군구 코드 (통계청/법정동코드 기준)
SEOUL_LAWD_CD = {
    "종로구": "11110", "중구": "11140", "용산구": "11170", "성동구": "11200",
    "광진구": "11215", "동대문구": "11230", "중랑구": "11260", "성북구": "11290",
    "강북구": "11305", "도봉구": "11320", "노원구": "11350", "은평구": "11380",
    "서대문구": "11410", "마포구": "11440", "양천구": "11470", "강서구": "11500",
    "구로구": "11530", "금천구": "11545", "영등포구": "11560", "동작구": "11590",
    "관악구": "11620", "서초구": "11650", "강남구": "11680", "송파구": "11710",
    "강동구": "11740",
}


def resolve_lawd_cd(region: str) -> str | None:
    """지역명(또는 주소)에서 시군구 코드를 찾는다. 못 찾으면 None."""
    if not region:
        return None
    if region in SEOUL_LAWD_CD:
        return SEOUL_LAWD_CD[region]
    # 전체 주소 문자열이면 '○○구' 토큰을 추출
    for token in region.split():
        if token in SEOUL_LAWD_CD:
            return SEOUL_LAWD_CD[token]
    return None


def recent_deal_ym(today: str | None = None) -> str:
    """직전 완결 월의 계약년월(YYYYMM). 실거래가는 당월 데이터가 불완전하므로 전월."""
    d = date.fromisoformat(today) if today else date.today()
    year, month = d.year, d.month - 1
    if month == 0:
        year, month = year - 1, 12
    return f"{year}{month:02d}"
