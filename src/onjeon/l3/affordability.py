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
    """실질 월주거비 vs 적정선. over_under_krw>0=초과, <0=여유.

    **소득 0은 예외가 아니다.** RIR은 분모가 소득이라 산출 자체가 불가능하지만,
    그건 이 진단 하나가 못 나오는 것이지 의사결정 전체가 실패할 일이 아니다
    (전세vs월세 비교·기대손실·대출 자격은 소득 0에서도 그대로 계산된다).
    예전엔 여기서 ValueError를 올려 무소득 청년이 화면 전체를 못 봤다.

    소득 0이면 `available=False` + 사유를 남기고 월주거비는 그대로 알려준다 —
    "얼마 쓰는지"는 소득과 무관하게 답할 수 있는 정보다.
    """
    if monthly_income < 0:
        raise ValueError(f"월소득이 음수: {monthly_income!r}")
    cost = monthly_housing_cost(
        monthly_rent=monthly_rent, maintenance=maintenance,
        deposit=deposit, opportunity_rate=opportunity_rate,
    )
    if monthly_income == 0:
        return {
            "available": False,
            "reason": "월소득이 0이라 소득 대비 주거비 비율(RIR)을 낼 수 없어요. "
                      "주거비 자체는 아래와 같고, 대출 자격은 소득과 별개로 판정했어요.",
            "monthly_cost": cost,
            "appropriate": None,
            "over_under_krw": None,
            "rir_actual": None,
            "rir_cap": rir_cap,
            "verdict": None,
        }
    cap = appropriate_rent(monthly_income=monthly_income, rir_cap=rir_cap)
    return {
        "available": True,
        "reason": None,
        "monthly_cost": cost,
        "appropriate": cap,
        "over_under_krw": cost - cap,
        "rir_actual": cost / monthly_income,
        "rir_cap": rir_cap,
        "verdict": "초과" if cost > cap else "적정",
    }
