"""전 레이어 오케스트레이터 — 게이트(L1) → P(사고)(L2) → 3안 비용(L3) → 리포트.

L4 에이전트와 Streamlit UI가 공유하는 단일 진입점. LLM 호출 없음 —
여기서 나온 숫자만이 화면·에이전트 답변에 인용될 수 있다.
"""

from __future__ import annotations

from onjeon.l1.schema import gate, senior_claims
from onjeon.l2.model import RiskModel
from onjeon.l3 import engine
from onjeon.rules_io import load_rules


def _auction_rate(doc: dict, auction_rates: dict) -> float:
    region = doc["property"].get("region", "default")
    building = doc["property"]["building_type"]
    table = auction_rates["rates"].get(region, auction_rates["rates"]["default"])
    return table[building]


def _features(doc: dict, deposit: int, auction_rate: float) -> dict:
    price = doc["property"]["market_price_krw"]
    return {
        "jeonse_ratio": deposit / price,
        "lien_ratio": senior_claims(doc["register"]) / price,
        "is_villa": 1 if doc["property"]["building_type"] == "빌라" else 0,
        "auction_rate": auction_rate,
    }


def _citations(doc: dict) -> list[dict]:
    register = doc["register"]
    return [
        entry["source_loc"] | {"type": entry["type"], "amount_krw": entry.get("max_claim_krw")}
        for section in ("gap_section", "eul_section")
        for entry in register[section]
    ]


def run_comparison(
    *,
    persona: dict,
    villa_doc: dict,
    officetel_doc: dict,
    model: RiskModel,
    tax_rules: dict | None = None,
    market_params: dict | None = None,
    auction_rates: dict | None = None,
) -> dict:
    """전세(빌라)/월세(오피스텔)/매수(빌라) 3안 리스크 조정 연간 비용 리포트."""
    tax_rules = tax_rules or load_rules("tax_rules")
    market_params = market_params or load_rules("market_params")
    auction_rates = auction_rates or load_rules("auction_rates")

    villa = gate(villa_doc)
    officetel = gate(officetel_doc)

    assets = persona["assets_krw"]
    income = persona["annual_income_krw"]
    stay_years = persona.get("expected_stay_years", 4)
    opp = market_params["opportunity_rate"]

    # ── 전세 (위험 빌라) ──────────────────────────────────────────────
    jeonse_deposit = villa["offer"]["jeonse_deposit_krw"]
    villa_rate = _auction_rate(villa, auction_rates)
    villa_features = _features(villa, jeonse_deposit, villa_rate)
    p_villa = model.predict_proba(villa_features)
    villa_lgd = engine.lgd(
        market_price=villa["property"]["market_price_krw"],
        auction_rate=villa_rate,
        senior_claims=senior_claims(villa["register"]),
        deposit=jeonse_deposit,
        insured=villa["offer"].get("insured", False),
    )
    e_loss = engine.expected_loss(p_villa, villa_lgd, jeonse_deposit)
    jeonse_nominal = engine.annual_cost_jeonse(
        deposit=jeonse_deposit,
        user_assets=assets,
        loan_rate=market_params["loan_rate_jeonse"],
        opportunity_rate=opp,
        e_loss=0,
    )

    # ── 월세 (안전 오피스텔) ──────────────────────────────────────────
    wolse_deposit = officetel["offer"]["wolse_deposit_krw"]
    officetel_rate = _auction_rate(officetel, auction_rates)
    officetel_features = _features(officetel, wolse_deposit, officetel_rate)
    p_officetel = model.predict_proba(officetel_features)
    wolse_total = engine.annual_cost_wolse(
        deposit=wolse_deposit,
        monthly_rent=officetel["offer"]["monthly_rent_krw"],
        annual_income=income,
        user_assets=assets,
        loan_rate=market_params["loan_rate_jeonse"],
        opportunity_rate=opp,
        tax_rules=tax_rules,
    )

    # ── 매수 (빌라) ───────────────────────────────────────────────────
    buy_total = engine.annual_cost_buy(
        price=villa["offer"].get("sale_price_krw", villa["property"]["market_price_krw"]),
        user_assets=assets,
        loan_rate=market_params["loan_rate_buy"],
        opportunity_rate=opp,
        stay_years=stay_years,
        tax_rules=tax_rules,
    )

    options = {
        "jeonse": {
            "label": "전세 (빌라)",
            "nominal": jeonse_nominal,
            "e_loss": e_loss,
            "total": jeonse_nominal + e_loss,
            "p_accident": p_villa,
            "lgd": villa_lgd,
            "explain": model.explain(villa_features),
            "citations": _citations(villa),
        },
        "wolse": {
            "label": "월세 (오피스텔)",
            "nominal": wolse_total,
            "e_loss": 0,
            "total": wolse_total,
            "p_accident": p_officetel,
            "lgd": 0.0,
            "explain": model.explain(officetel_features),
            "citations": _citations(officetel),
        },
        "buy": {
            "label": "매수 (빌라)",
            "nominal": buy_total,
            "e_loss": 0,
            "total": buy_total,
            "p_accident": None,
            "lgd": None,
            "explain": None,
            "citations": _citations(villa),
        },
    }
    best_key = min(options, key=lambda k: options[k]["total"])
    best_names = {"jeonse": "전세", "wolse": "월세", "buy": "매수"}

    return {
        **options,
        "best": best_names[best_key],
        "sources": {
            "market_price_queried_at": villa["property"]["price_source"]["queried_at"],
            "tax_rules_version": tax_rules["version"],
            "market_params_version": market_params["version"],
            "auction_rates_source": auction_rates.get("source", ""),
            "auction_rates_queried_at": auction_rates.get("queried_at", ""),
            "risk_model_note": model.data_note,
        },
    }
