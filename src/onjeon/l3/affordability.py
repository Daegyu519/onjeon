"""적정 주거비 진단 — RIR(소득 대비 주거비 비율) 상한 기준.

L3 결정론(순수함수), 원(₩) 정수. 월 실질 주거비를 적정선(월소득×RIR상한)과 비교한다.
보증금 기회비용은 월환산(deposit×opportunity_rate/12) — engine의 연 opportunity_rate와 일치.
'적정'은 규범적 판단이며 RIR 상한은 룰 데이터(rules/market_params.rir_cap)로 주입한다.
"""

from __future__ import annotations


def monthly_housing_cost(
    *, monthly_rent: int, maintenance: int, deposit: int, opportunity_rate: float
) -> int:
    """월 실질 주거비 = 월세 + 관리비 + 보증금 월환산 기회비용."""
    return round(monthly_rent + maintenance + deposit * opportunity_rate / 12)


def appropriate_rent(*, monthly_income: int, rir_cap: float) -> int:
    """적정 월주거비 상한 = 월소득 × RIR 상한."""
    return round(monthly_income * rir_cap)


def diagnose(
    *,
    monthly_income: int,
    monthly_rent: int,
    maintenance: int,
    deposit: int,
    opportunity_rate: float,
    rir_cap: float,
) -> dict:
    """실질 월주거비 vs 적정선. over_under_krw>0=초과, <0=여유. 소득 0 이하면 ValueError."""
    if monthly_income <= 0:
        raise ValueError("월소득이 0 이하 — RIR 산출 불가")
    cost = monthly_housing_cost(
        monthly_rent=monthly_rent, maintenance=maintenance,
        deposit=deposit, opportunity_rate=opportunity_rate,
    )
    cap = appropriate_rent(monthly_income=monthly_income, rir_cap=rir_cap)
    return {
        "monthly_cost": cost,
        "appropriate": cap,
        "over_under_krw": cost - cap,
        "rir_actual": cost / monthly_income,
        "rir_cap": rir_cap,
        "verdict": "초과" if cost > cap else "적정",
    }
