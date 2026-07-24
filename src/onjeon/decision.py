"""주거 의사결정 오케스트레이터 — 적정 주거비 진단 + 청년 금융지원 추천.

프로필+매물 → affordability(RIR 적정선) + recommend(자격 랭킹/미자격 반증).
LLM 없음(결정론). 3안 비교(compare_options)는 전체 매물문서·리스크모델이 필요해
이번 슬라이스에선 제외한다(연결은 이후). 금액은 원(₩) 정수.
"""

from __future__ import annotations

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


def decide(profile: dict, listing: dict, *, products=None, market_params=None) -> dict:
    """프로필+매물 → {affordability, recommendations, sources}. 월소득 없으면 ValueError."""
    if not profile.get("monthly_income_krw"):
        raise ValueError("monthly_income_krw(월소득)이 필요합니다")
    market_params = market_params or load_rules("market_params")
    products = products if products is not None else load_products()

    affordability = diagnose(
        monthly_income=profile["monthly_income_krw"],
        monthly_rent=listing.get("monthly_rent_krw", 0),
        maintenance=listing.get("maintenance_krw", 0),
        deposit=listing.get("deposit_krw", 0),
        opportunity_rate=market_params["opportunity_rate"],
        rir_cap=market_params["rir_cap"],
    )
    return {
        "affordability": affordability,
        "recommendations": recommend(_eligibility_input(profile, listing), products),
        "sources": {
            "rir_cap": market_params["rir_cap"],
            "rir_cap_source": market_params.get("rir_cap_source", ""),
            "market_params_version": market_params["version"],
        },
    }
