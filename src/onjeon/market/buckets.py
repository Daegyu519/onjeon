"""거래 레코드를 주/월 버킷으로 묶어 평당가 평균을 낸다(순수 함수)."""

from __future__ import annotations

import statistics


def bucket_key(deal_date: str, granularity: str) -> str:
    """'YYYY-MM-DD' → 'YYYY-MM'(month) 또는 'YYYY-MM-Wn'(week)."""
    year, month, day = deal_date.split("-")
    if granularity == "month":
        return f"{year}-{month}"
    if granularity == "week":
        week = (int(day) - 1) // 7 + 1
        return f"{year}-{month}-W{week}"
    raise ValueError(f"알 수 없는 granularity: {granularity!r}")


def average_by_bucket(records: list[dict], granularity: str) -> dict[str, dict]:
    """버킷별 평당가 평균(반올림)·건수. 버킷 키 오름차순."""
    groups: dict[str, list[int]] = {}
    for rec in records:
        key = bucket_key(rec["deal_date"], granularity)
        groups.setdefault(key, []).append(rec["pyeong_krw"])
    return {
        key: {"pyeong_krw": round(statistics.mean(vals)), "n": len(vals)}
        for key, vals in sorted(groups.items())
    }
