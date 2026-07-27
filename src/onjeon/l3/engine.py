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


def split_funding_policy(
    amount_needed: int, user_assets: int, policy_limit: int
) -> tuple[int, int, int]:
    """필요 자금을 (자기자본, 정책대출, 시장대출) 으로 분할한다.

    정책대출은 상품 한도(policy_limit)까지만 받을 수 있고 초과분은 시장금리 대출이다.
    한도를 무시하고 정책금리를 대출 전액에 적용하면 전세 비용이 실제보다 싸게 나온다
    (보증금 2억·자산 2천만·한도 1억 기준 연 184만원 과소평가 — 결론 부호가 뒤집힌다).

        amount_needed ─┬─ own    = min(필요액, 자산)          → 기회비용
                       ├─ policy = min(잔여, policy_limit)    → 정책금리
                       └─ market = 잔여 − policy              → 시장금리

    policy_limit=0 이면 (own, 0, loan) — split_funding과 같은 결과.
    """
    own, loan = split_funding(amount_needed, user_assets)
    policy = min(loan, max(policy_limit, 0))
    return own, policy, loan - policy


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


def auction_rate(region: str, building_type: str, auction_rates: dict) -> float:
    """지역·건물유형 → 낙찰가율. 지역표 우선, 없으면 default, 그것도 없으면 최저값.

    테이블에 없는 유형에 낙찰가율을 높게 잡으면 회수 예상액이 부풀려져 LGD가
    과소평가된다 — 그래서 미지 유형은 가장 보수적(최저)으로 떨어뜨린다.
    """
    rates = auction_rates["rates"]
    region_table = rates.get(region, rates["default"])
    if building_type in region_table:
        return region_table[building_type]
    if building_type in rates["default"]:
        return rates["default"][building_type]
    return min(rates["default"].values())


def lgd(
    *,
    market_price: int,
    auction_rate: float,
    senior_claims: int,
    deposit: int,
    insured: bool = False,
    priority_krw: int = 0,
) -> float:
    """LGD = 1 − (경매 회수 예상액 / 보증금), [0, 1] 클램프.

    배당 순서:
        낙찰가 = 시세 × 낙찰가율
        ① priority_krw  — 소액임차인 최우선변제. 선순위 근저당보다 **먼저** 배당된다
                          (주택임대차보호법 §8). 0이면 없는 것과 같다.
        ② senior_claims — 선순위 근저당 등
        ③ 남은 금액이 대상 임차인의 배당
        회수액은 보증금을 넘지 않는다(초과 배당은 임차인 몫이 아니다).

    최우선변제를 빼면 소액 보증금(주로 월세)의 위험이 과대평가된다 — 낙찰가를
    선순위가 거의 다 먹는 상황에서 실제로는 전액 보호되는데 LGD가 1.0으로 나온다.
    한도·기준액은 룰 데이터이며 `l3.risk.priority_amount`가 계산한다.

    보증보험 가입 매물은 0.0 (MVP 가정 — [확인] 부분 보전 조건 반영 필요).
    """
    if deposit <= 0:
        raise ValueError("deposit은 1원 이상이어야 한다")
    if insured:
        return 0.0
    expected_auction = market_price * auction_rate
    priority = min(max(priority_krw, 0), deposit, expected_auction)
    remainder = max(expected_auction - priority - senior_claims, 0.0)
    recovery = min(priority + remainder, deposit)
    return 1.0 - recovery / deposit


def expected_loss(p_accident: float, lgd_value: float, deposit: int) -> int:
    """E[Loss] = P(사고) × LGD × 보증금 (docs/design.md §4)."""
    return round(p_accident * lgd_value * deposit)
