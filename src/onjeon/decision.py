"""주거 의사결정 오케스트레이터 — 적정 주거비 진단 + 청년 금융지원 추천.

프로필+매물 → affordability(RIR 적정선) + recommend(자격 랭킹/미자격 반증).
LLM 없음(결정론). 3안 비교(compare_options)는 전체 매물문서·리스크모델이 필요해
이번 슬라이스에선 제외한다(연결은 이후). 금액은 원(₩) 정수.
"""

from __future__ import annotations

from onjeon.l3 import engine
from onjeon.l3.affordability import diagnose
from onjeon.l3.recommend import recommend
from onjeon.rules_io import load_products, load_rules


def _eligibility_input(profile: dict, listing: dict) -> dict:
    """프로필+매물 → 자격판정 입력. 소득은 연소득(월×12), 보증금은 매물에서."""
    return {
        "age": profile.get("age"),
        "assets_krw": profile.get("assets_krw"),
        "is_homeless": profile.get("is_homeless"),
        "is_household_head": profile.get("is_household_head"),
        "works_at_sme": profile.get("works_at_sme"),
        "annual_income_krw": profile["monthly_income_krw"] * 12,
        "deposit_krw": listing.get("deposit_krw", 0),
    }


def _rental_annual_cost(listing, profile, mp, tax_rules) -> int:
    """후보 임차(전세/월세)의 연 실질비용 — engine 결정론 계산."""
    assets = profile["assets_krw"]
    if listing.get("kind") == "jeonse":
        return engine.annual_cost_jeonse(
            deposit=listing.get("deposit_krw", 0), user_assets=assets,
            loan_rate=mp["loan_rate_jeonse"], opportunity_rate=mp["opportunity_rate"], e_loss=0,
        )
    return engine.annual_cost_wolse(
        deposit=listing.get("deposit_krw", 0), monthly_rent=listing.get("monthly_rent_krw", 0),
        annual_income=profile["monthly_income_krw"] * 12, user_assets=assets,
        loan_rate=mp["loan_rate_jeonse"], opportunity_rate=mp["opportunity_rate"], tax_rules=tax_rules,
    )


def _buy_vs_rent(listing, profile, mp, tax_rules) -> dict | None:
    """매물 예상 매매가(market_price_krw)가 있으면 임차 vs 매수 연비용 비교. 없으면 None(허구 금지)."""
    price = listing.get("market_price_krw")
    if not price:
        return None
    rental = _rental_annual_cost(listing, profile, mp, tax_rules)
    buy = engine.annual_cost_buy(
        price=price, user_assets=profile["assets_krw"], loan_rate=mp["loan_rate_buy"],
        opportunity_rate=mp["opportunity_rate"],
        stay_years=profile.get("expected_stay_years", 4), tax_rules=tax_rules,
    )
    rental_label = "전세" if listing.get("kind") == "jeonse" else "월세"
    return {
        "rental": {"kind": rental_label, "annual_krw": rental},
        "buy": {"annual_krw": buy, "market_price_krw": price},
        "cheaper": rental_label if rental < buy else "매수",
    }


def compare_jeonse_wolse(profile, jeonse, wolse, *, products, market_params, tax_rules) -> dict:
    """전세 vs 월세 연비용 비교 — 혜택 반영. jeonse={deposit_krw}, wolse={deposit_krw, monthly_rent_krw}.

    전세: 자격 있는 전세대출 '최저금리'를 적용(없으면 시장금리). 월세: 청년월세지원 자격이면
    연 240만(20만/월×12) 차감. engine 결정론 계산.
    """
    assets = profile["assets_krw"]
    opp = market_params["opportunity_rate"]

    # 전세 — 자격 있는 대출 최저금리
    jz_elig = recommend(_eligibility_input(profile, jeonse), products)["eligible"]
    rates = [e["terms"]["interest_rate"] for e in jz_elig
             if e.get("product_type") == "loan" and e["terms"].get("interest_rate")]
    jz_rate = min(rates) if rates else market_params["loan_rate_jeonse"]
    jz_cost = engine.annual_cost_jeonse(
        deposit=jeonse["deposit_krw"], user_assets=assets,
        loan_rate=jz_rate, opportunity_rate=opp, e_loss=0,
    )

    # 월세 — 청년월세지원 자격이면 연 240만 차감(20만/월×12, rule: youth-monthly-rent-support)
    ws_elig = recommend(_eligibility_input(profile, wolse), products)["eligible"]
    has_support = any(e["rule_id"] == "youth-monthly-rent-support-2026-07" for e in ws_elig)
    ws_before = engine.annual_cost_wolse(
        deposit=wolse.get("deposit_krw", 0), monthly_rent=wolse["monthly_rent_krw"],
        annual_income=profile["monthly_income_krw"] * 12, user_assets=assets,
        loan_rate=market_params["loan_rate_jeonse"], opportunity_rate=opp, tax_rules=tax_rules,
    )
    support = 2_400_000 if has_support else 0
    ws_cost = ws_before - support
    return {
        "jeonse": {"annual_krw": jz_cost, "loan_rate": jz_rate, "loan_benefit": bool(rates)},
        "wolse": {"annual_krw": ws_cost, "before_support_krw": ws_before, "monthly_support": has_support},
        "cheaper": "전세" if jz_cost < ws_cost else "월세",
    }


def decide(profile: dict, listing: dict, *, products=None, market_params=None, tax_rules=None) -> dict:
    """프로필+매물 → {affordability, recommendations, comparison?, sources}. 월소득 없으면 ValueError."""
    if not profile.get("monthly_income_krw"):
        raise ValueError("monthly_income_krw(월소득)이 필요합니다")
    market_params = market_params or load_rules("market_params")
    tax_rules = tax_rules or load_rules("tax_rules")
    products = products if products is not None else load_products()

    affordability = diagnose(
        monthly_income=profile["monthly_income_krw"],
        monthly_rent=listing.get("monthly_rent_krw", 0),
        maintenance=listing.get("maintenance_krw", 0),
        deposit=listing.get("deposit_krw", 0),
        opportunity_rate=market_params["opportunity_rate"],
        rir_cap=market_params["rir_cap"],
    )
    result = {
        "affordability": affordability,
        "recommendations": recommend(_eligibility_input(profile, listing), products),
        "sources": {
            "rir_cap": market_params["rir_cap"],
            "rir_cap_source": market_params.get("rir_cap_source", ""),
            "market_params_version": market_params["version"],
            "tax_rules_version": tax_rules["version"],
        },
    }
    comparison = _buy_vs_rent(listing, profile, market_params, tax_rules)
    if comparison:
        result["comparison"] = comparison
    # 전세 vs 월세(혜택 반영) — 두 조건 다 주면 산출
    jz, ws_rent = listing.get("jeonse_deposit_krw"), listing.get("wolse_monthly_rent_krw")
    if jz and ws_rent:
        result["jeonse_vs_wolse"] = compare_jeonse_wolse(
            profile,
            {"deposit_krw": jz},
            {"deposit_krw": listing.get("wolse_deposit_krw", 0), "monthly_rent_krw": ws_rent},
            products=products, market_params=market_params, tax_rules=tax_rules,
        )
    return result
