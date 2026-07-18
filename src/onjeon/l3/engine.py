"""L3 결정론적 계산 엔진 (AI 아님 — 의도된 설계).

모든 금액은 원(₩) 정수. 세제·시장 규칙은 룰 DB(JSON dict)로 주입받으며
함수 내 하드코딩을 금지한다. LLM 호출 금지. docs/design.md §3~4 참조.
"""

from __future__ import annotations


def split_funding(amount_needed: int, user_assets: int) -> tuple[int, int]:
    """필요 자금을 (자기자본, 대출) 으로 분할한다."""
    own = min(amount_needed, user_assets)
    loan = amount_needed - own
    return own, loan


def annual_cost_jeonse(
    *,
    deposit: int,
    user_assets: int,
    loan_rate: float,
    opportunity_rate: float,
    e_loss: int,
) -> int:
    """전세 연간 실질비용 = 대출이자 + 자기자본 기회비용 + E[Loss]."""
    own, loan = split_funding(deposit, user_assets)
    return round(loan * loan_rate + own * opportunity_rate + e_loss)


def wolse_tax_credit(annual_rent: int, annual_income: int, tax_rules: dict) -> int:
    """월세 세액공제액 (조특법 §95-2 — 구간·한도는 룰 DB에서)."""
    credit_rule = tax_rules["wolse_tax_credit"]
    base = min(annual_rent, credit_rule["annual_rent_cap_krw"])
    # L0가 공급한 룰의 구간 순서를 신뢰하지 않는다 — 항상 소득 상한 오름차순으로 매칭
    for bracket in sorted(credit_rule["brackets"], key=lambda b: b["max_income_krw"]):
        if annual_income <= bracket["max_income_krw"]:
            return round(base * bracket["rate"])
    return 0


def annual_cost_wolse(
    *,
    deposit: int,
    monthly_rent: int,
    annual_income: int,
    user_assets: int,
    loan_rate: float,
    opportunity_rate: float,
    tax_rules: dict,
) -> int:
    """월세 연간 실질비용 = 연월세 − 세액공제 + 보증금 자금비용(이자+기회비용)."""
    annual_rent = monthly_rent * 12
    credit = wolse_tax_credit(annual_rent, annual_income, tax_rules)
    own, loan = split_funding(deposit, user_assets)
    return round(annual_rent - credit + loan * loan_rate + own * opportunity_rate)


def annual_cost_buy(
    *,
    price: int,
    user_assets: int,
    loan_rate: float,
    opportunity_rate: float,
    stay_years: int,
    tax_rules: dict,
) -> int:
    """매수 연간 실질비용 = (취득세+중개보수)/거주연수 + 보유세 + 이자 + 기회비용."""
    if stay_years <= 0:
        raise ValueError("stay_years는 1 이상이어야 한다")
    acquisition = price * tax_rules["acquisition"]["rate"]
    brokerage = price * tax_rules["brokerage"]["buy_rate"]
    holding = price * tax_rules["holding"]["estimate_rate"]
    own, loan = split_funding(price, user_assets)
    return round(
        (acquisition + brokerage) / stay_years
        + holding
        + loan * loan_rate
        + own * opportunity_rate
    )


def lgd(
    *,
    market_price: int,
    auction_rate: float,
    senior_claims: int,
    deposit: int,
    insured: bool = False,
) -> float:
    """LGD = 1 − (경매 회수 예상액 / 보증금), [0, 1] 클램프.

    보증보험 가입 매물은 0.0 (MVP 가정 — [확인] 부분 보전 조건 반영 필요).
    """
    if deposit <= 0:
        raise ValueError("deposit은 1원 이상이어야 한다")
    if insured:
        return 0.0
    expected_auction = market_price * auction_rate
    recovery = max(expected_auction - senior_claims, 0.0)
    recovery = min(recovery, deposit)
    return 1.0 - recovery / deposit


def expected_loss(p_accident: float, lgd_value: float, deposit: int) -> int:
    """E[Loss] = P(사고) × LGD × 보증금 (docs/design.md §4)."""
    return round(p_accident * lgd_value * deposit)
