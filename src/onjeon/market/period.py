"""기간 퀵버튼(1m/6m/1y/3y/5y) → 계약월 범위·집계 단위."""

from __future__ import annotations

from onjeon.data_pipeline.regions import month_range, recent_deal_ym

_MONTHS_BACK = {"1m": 1, "6m": 6, "1y": 12, "3y": 36, "5y": 60}
_WEEK_PERIODS = {"1m", "6m"}


def granularity_for(period: str) -> str:
    """짧은 기간(≤6m)은 주 단위, 그 외는 월 단위."""
    if period not in _MONTHS_BACK:
        raise ValueError(f"지원하지 않는 기간: {period!r}")
    return "week" if period in _WEEK_PERIODS else "month"


def period_months(period: str, today: str | None = None) -> list[str]:
    """직전 완결월을 끝으로 N개월 전까지의 YYYYMM 리스트."""
    if period not in _MONTHS_BACK:
        raise ValueError(f"지원하지 않는 기간: {period!r}")
    end = recent_deal_ym(today)
    ey, em = int(end[:4]), int(end[4:])
    back = _MONTHS_BACK[period]
    total = ey * 12 + (em - 1) - back
    sy, sm = divmod(total, 12)
    start = f"{sy}{sm + 1:02d}"
    return month_range(start, end)
