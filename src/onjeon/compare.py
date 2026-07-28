"""전 레이어 오케스트레이터 — 게이트(L1) → P(사고)(L2) → 3안 비용(L3) → 리포트.

L4 에이전트와 Streamlit UI가 공유하는 단일 진입점. LLM 호출 없음 —
여기서 나온 숫자만이 화면·에이전트 답변에 인용될 수 있다.

보증금 미회수 위험은 `l3.risk.deposit_risk`가 계산한다 — 배포 경로(decision.py)와
같은 정의다. 예전엔 두 모듈이 각자 구현했고 이쪽은 월세 E[Loss]를 0으로 하드코딩했다.
"""

from __future__ import annotations

from onjeon.l1.schema import gate, senior_claims
from onjeon.l2.model import RiskModel
from onjeon.l3 import engine
from onjeon.l3.risk import deposit_risk
from onjeon.rules_io import load_rules


def _auction_rate(doc: dict, auction_rates: dict) -> float:
    """매물문서에서 지역·유형을 꺼내 engine.auction_rate에 위임(조회 규칙은 한 곳에)."""
    return engine.auction_rate(
        doc["property"].get("region", "default"),
        doc["property"]["building_type"],
        auction_rates,
    )


def _risk_of(doc: dict, deposit: int, *, model, auction_rates, market_params) -> dict:
    """매물문서 → 보증금 미회수 위험. 계산은 l3.risk가 한다(배포 경로와 같은 정의).

    예전엔 이 모듈이 피처 구성·LGD·E[Loss]를 따로 구현했고 월세는 0으로 하드코딩했다.
    같은 제품이 두 경로에서 다른 답을 내던 부채를 l3.risk로 합쳤다.
    """
    return deposit_risk(
        deposit=deposit,
        market_price=doc["property"]["market_price_krw"],
        senior_claims=senior_claims(doc["register"]),
        building_type=doc["property"]["building_type"],
        auction_rate=_auction_rate(doc, auction_rates),
        model=model,
        insured=doc["offer"].get("insured", False),
        priority_rule=market_params.get("small_deposit_priority"),
        # 최우선변제는 지역별 금액이 2배 이상 갈린다 — 안 넘기면 서울 매물도 보호가 0이 된다.
        # address를 함께 보는 건 region이 '관악구'처럼 시군구만 담기기 때문이다.
        region=doc["property"].get("region") or doc["property"].get("address"),
    )


def _citations(doc: dict) -> list[dict]:
    register = doc["register"]
    return [
        # source_loc 누락(실물 추출) 시 빈 dict로 안전 처리 — 인용 위치만 비고 나머지 유지
        {"page": None, "section": None, "entry_no": None}
        | entry.get("source_loc", {})
        | {
            "type": entry.get("type", ""),
            "amount_krw": entry.get("max_claim_krw"),
            "cancelled": entry.get("cancelled", False),
        }
        for section in ("gap_section", "eul_section")
        for entry in register.get(section, [])
    ]


_KIND_BEST = {"jeonse": "전세", "wolse": "월세", "buy": "매수"}


def _opt_jeonse(gated, label, *, profile, model, market_params, tax_rules, auction_rates):
    """전세 안 — 보증금 미회수 위험(E[Loss])을 반영한 리스크조정 연간비용."""
    deposit = gated["offer"]["jeonse_deposit_krw"]
    risk = _risk_of(gated, deposit, model=model, auction_rates=auction_rates,
                    market_params=market_params)
    nominal = engine.annual_cost_jeonse(
        deposit=deposit,
        user_assets=profile["assets_krw"],
        loan_rate=market_params["loan_rate_jeonse"],
        opportunity_rate=market_params["opportunity_rate"],
        e_loss=0,
    )
    return {
        "label": label,
        "nominal": nominal,
        "e_loss": risk["e_loss_krw"],
        "total": nominal + risk["e_loss_krw"],
        "p_accident": risk["p_accident"],
        "lgd": risk["lgd"],
        "explain": model.explain(risk["features"]),
        "citations": _citations(gated),
    }


def _opt_wolse(gated, label, *, profile, model, market_params, tax_rules, auction_rates):
    """월세 안 — 보증금 미회수 위험을 전세와 **같은 기계로** 계산한다.

    예전엔 E[Loss]=0으로 하드코딩했다. 지금은 l3.risk를 공유하므로, 보증금이 작아
    낙찰 회수액이 이를 덮거나 소액임차인 최우선변제에 걸리면 자연히 0이 나온다 —
    하드코딩보다 방어하기 쉽고 위험한 월세(선순위가 낙찰가를 다 먹는 경우)를 놓치지 않는다.
    """
    deposit = gated["offer"]["wolse_deposit_krw"]
    risk = _risk_of(gated, deposit, model=model, auction_rates=auction_rates,
                    market_params=market_params)
    nominal = engine.annual_cost_wolse(
        deposit=deposit,
        monthly_rent=gated["offer"]["monthly_rent_krw"],
        annual_income=profile["annual_income_krw"],
        user_assets=profile["assets_krw"],
        loan_rate=market_params["loan_rate_jeonse"],
        opportunity_rate=market_params["opportunity_rate"],
        tax_rules=tax_rules,
    )
    return {
        "label": label,
        "nominal": nominal,
        "e_loss": risk["e_loss_krw"],
        "total": nominal + risk["e_loss_krw"],
        "p_accident": risk["p_accident"],
        "lgd": risk["lgd"],
        "explain": model.explain(risk["features"]),
        "citations": _citations(gated),
    }


def _opt_buy(gated, label, *, profile, model, market_params, tax_rules, auction_rates):
    """매수 안 — 임차 리스크 없음(p/lgd/explain None)."""
    total = engine.annual_cost_buy(
        price=gated["offer"].get("sale_price_krw", gated["property"]["market_price_krw"]),
        user_assets=profile["assets_krw"],
        loan_rate=market_params["loan_rate_buy"],
        opportunity_rate=market_params["opportunity_rate"],
        stay_years=profile.get("expected_stay_years", 4),
        tax_rules=tax_rules,
    )
    return {
        "label": label,
        "nominal": total,
        "e_loss": 0,
        "total": total,
        "p_accident": None,
        "lgd": None,
        "explain": None,
        "citations": _citations(gated),
    }


_OPT_FN = {"jeonse": _opt_jeonse, "wolse": _opt_wolse, "buy": _opt_buy}


def compare_options(
    *,
    profile: dict,
    options: list[dict],
    model: RiskModel,
    tax_rules: dict | None = None,
    market_params: dict | None = None,
    auction_rates: dict | None = None,
) -> dict:
    """임의 프로필·매물 안들의 리스크조정 연간비용 비교(범용 3안 엔진).

    options: 각 항목 {"key", "kind"(jeonse|wolse|buy), "label", "doc"(raw)}.
    반환: {<key>: 안결과, ..., "best": 최저비용 안의 한글명, "sources": 출처}.
    LLM 없음 — 여기 숫자만 화면·에이전트에 인용 가능.
    """
    tax_rules = tax_rules or load_rules("tax_rules")
    market_params = market_params or load_rules("market_params")
    auction_rates = auction_rates or load_rules("auction_rates")

    results, kinds, first_gated = {}, {}, None
    for opt in options:
        gated = gate(opt["doc"])
        first_gated = first_gated or gated
        results[opt["key"]] = _OPT_FN[opt["kind"]](
            gated, opt["label"], profile=profile, model=model,
            market_params=market_params, tax_rules=tax_rules, auction_rates=auction_rates,
        )
        kinds[opt["key"]] = opt["kind"]

    best_key = min(results, key=lambda k: results[k]["total"])
    return {
        **results,
        "best": _KIND_BEST[kinds[best_key]],
        "sources": {
            "market_price_queried_at": first_gated["property"].get("price_source", {}).get("queried_at", ""),
            "tax_rules_version": tax_rules["version"],
            "market_params_version": market_params["version"],
            "auction_rates_source": auction_rates.get("source", ""),
            "auction_rates_queried_at": auction_rates.get("queried_at", ""),
            "risk_model_note": model.data_note,
        },
    }


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
    """전세(빌라)/월세(오피스텔)/매수(빌라) 3안 비교 — compare_options의 데모 어댑터."""
    return compare_options(
        profile=persona,
        options=[
            {"key": "jeonse", "kind": "jeonse", "label": "전세 (빌라)", "doc": villa_doc},
            {"key": "wolse", "kind": "wolse", "label": "월세 (오피스텔)", "doc": officetel_doc},
            {"key": "buy", "kind": "buy", "label": "매수 (빌라)", "doc": villa_doc},
        ],
        model=model,
        tax_rules=tax_rules,
        market_params=market_params,
        auction_rates=auction_rates,
    )
