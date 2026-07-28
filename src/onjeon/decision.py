"""주거 의사결정 오케스트레이터 — 배포 경로(api.main)가 쓰는 진입점.

프로필+매물 → 전세 vs 월세 **리스크 조정** 연비용 비교(주업무)
             + affordability(RIR 적정선) + recommend(자격 랭킹/미자격 반증)
             + 임차 vs 매수(시세가 있을 때만).
LLM 없음(결정론). 금액은 원(₩) 정수.

미회수 기대손실(E[Loss] = P(사고) × LGD × 보증금)은 `_risk()`가 계산해
`breakdown["미회수기대손실"]`로 넣는다. 시세·선순위가 없으면 0으로 계산하지 않고
`risk.adjusted=False` + 사유를 남긴다.

`compare.py`와의 관계: 그쪽은 Streamlit(app.py) 전용 3안 비교이고 월세 E[Loss]를
0으로 하드코딩한다. 이 모듈은 배포 경로이고 월세도 대칭으로 계산한다 —
두 경로가 다른 답을 낼 수 있다는 걸 알고 있는 부채다(계획서 §9.1 참조).
"""

from __future__ import annotations

from onjeon.l2.model import load_risk_model
from onjeon.l3 import engine
from onjeon.l3.affordability import diagnose
from onjeon.l3.recommend import recommend
from onjeon.l3.risk import deposit_risk
from onjeon.rules_io import load_products, load_rules


def _eligibility_input(profile: dict, listing: dict) -> dict:
    """프로필+매물 → 자격판정 입력. 소득은 연소득(월×12), 보증금은 매물에서.

    가구 형태(혼인·자녀)는 여기서 **판정 가능한 형태로 파생**시킨다. 룰 엔진은
    단순 field-op-value 비교만 하므로, "혼인 7년 이내"·"막내가 2살 미만" 같은
    조건은 불리언으로 미리 계산해서 넘긴다.
    """
    children = profile.get("children_count") or 0
    youngest = profile.get("youngest_child_age")
    marriage_years = profile.get("marriage_years")
    return {
        "age": profile.get("age"),
        "assets_krw": profile.get("assets_krw"),
        "is_homeless": profile.get("is_homeless"),
        "is_household_head": profile.get("is_household_head"),
        "works_at_sme": profile.get("works_at_sme"),
        "annual_income_krw": profile["monthly_income_krw"] * 12,
        "deposit_krw": listing.get("deposit_krw", 0),
        # 신혼가구 = 혼인 7년 이내(3개월 내 결혼 예정자 포함은 미수집이라 제외).
        # 혼인기간을 안 넣었으면 기혼이어도 신혼 판정을 못 한다 — None이 아니라
        # False로 두면 "신혼이 아니다"라고 단정하게 되므로 입력값이 있을 때만 True.
        "is_newlywed": bool(profile.get("is_married")) and marriage_years is not None
                       and marriage_years <= 7,
        "is_married": bool(profile.get("is_married")),
        "children_count": children,
        # 신생아 특례 = 출산 후 2년 이내. 막내 나이(만)가 0~1이면 해당.
        "has_newborn": youngest is not None and youngest <= 1 and children > 0,
        # 기금 대출은 신용'점수' 커트라인이 아니라 신용도판단정보(연체·대위변제·부도)
        # 등록 여부로 거른다. 그래서 점수가 아니라 불리언이다.
        "no_credit_delinquency": not profile.get("has_credit_delinquency", False),
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


def _cite(product: dict) -> dict:
    """상품 룰 → 화면이 인용할 출처. 모든 출력에 원문 출처 (CLAUDE.md 원칙 2).

    `clause_refs`와 `url`은 모든 상품 룰에 있고 `interest_rate_note`는 일부에만
    있다(중기청엔 없고 버팀목엔 있다). 조항이 인용의 기본이고 note는 덧붙이는 단서다.
    """
    source = product.get("source", {})
    return {
        "rule_id": product["rule_id"],
        "version": product.get("version", ""),
        "clause_refs": source.get("clause_refs", []),
        "url": source.get("url", ""),
        "note": product["terms"].get("interest_rate_note") or product["terms"].get("note", ""),
    }


def _best_policy_loan(kind: str, eligible: list[dict], market_rate: float) -> dict:
    """이 용도(jeonse|wolse)에 쓸 수 있는 최선 정책대출 → {rate, limit, product_name, source}.

    `source`는 화면이 인용할 조항·원문 링크다(원칙 2). 두 반환 경로 모두 이 키를 담는다 —
    빠뜨리면 대출 근거의 인용이 조용히 사라지고 테스트는 통과한다.

    `applies_to`로 용도를 걸러야 한다. 이 필터가 없으면 자격 상품 중 최저금리를 그냥
    집어가서, 매수 전용인 '내집마련 디딤돌대출'(주택 구입자금) 금리가 전세보증금에
    적용된다(실측: 중소기업 재직 해제 시 2.85%가 전세에 붙어 결론이 뒤집혔다).

    쓸 상품이 없으면 한도 0 · 시장금리 — 정책 혜택 없음을 뜻한다.
    """
    usable = [
        e for e in eligible
        if e.get("product_type") == "loan"
        and kind in (e.get("applies_to") or [])
        and e["terms"].get("interest_rate") is not None
    ]
    if not usable:
        return {"rate": market_rate, "limit": 0, "product_name": None, "source": None}
    best = min(usable, key=lambda e: e["terms"]["interest_rate"])
    return {
        "rate": best["terms"]["interest_rate"],
        "limit": best["terms"].get("limit_krw") or 0,
        "product_name": best["product_name"],
        # 모든 출력에 원문 출처 (CLAUDE.md 원칙 2) — 어느 상품·어느 버전·어느 조항인지.
        # clause_refs·url은 모든 상품 룰에 있고 interest_rate_note는 일부에만 있다.
        # 인용의 기본은 조항이고 note는 있을 때 덧붙이는 단서다.
        "source": _cite(best),
    }


def _funding_breakdown(deposit, assets, policy, market_rate, opportunity_rate):
    """보증금 조달비용을 (정책대출이자, 시장대출이자, 기회비용)으로 분해한다.

    → (비용 dict, 산정근거 dict). 근거를 같이 내는 이유: 화면에 "얼마"만 있고
    "무엇에 몇 %를 곱했는지"가 없으면 사용자가 숫자를 검증할 수 없다. 금리는
    전부 가정값이고 일부는 아직 `[확인]`이라 더더욱 드러내야 한다(CLAUDE.md 원칙 2·5).
    """
    own, policy_amt, market_amt = engine.split_funding_policy(deposit, assets, policy["limit"])
    costs = {
        "정책대출이자": round(policy_amt * policy["rate"]),
        "시장대출이자": round(market_amt * market_rate),
        "보증금기회비용": round(own * opportunity_rate),
    }
    basis = {
        "own_krw": own, "policy_krw": policy_amt, "market_krw": market_amt,
        "policy_rate": policy["rate"], "market_rate": market_rate,
        "opportunity_rate": opportunity_rate,
    }
    return costs, basis


def _price_band(listing: dict, uncertainty_rule: dict | None) -> float:
    """시세 추정의 불확실성 폭 → ±비율. 사용자가 직접 넣은 매매가면 0(추정이 아니다).

    집계 단위(지번/동/구)마다 다르다 — 구 평균은 이 매물과 다를 여지가 훨씬 크다.
    폭은 룰 데이터이며 아직 판단값이다(`[확인]` — 실측 분산으로 대체 필요).
    """
    if not listing.get("price_level") or not uncertainty_rule:
        return 0.0
    level = listing["price_level"]
    return float(uncertainty_rule.get(level, uncertainty_rule.get("default", 0.0)))


def _risk(
    deposit: int, listing: dict, profile: dict, *, auction_rates, model,
    priority_rule=None, uncertainty_rule=None,
) -> dict:
    """보증금 미회수 기대손실 산출. 반영했으면 e_loss_krw를, 아니면 사유를 담는다.

    E[Loss] = P(사고) × LGD × 보증금 (docs/design.md §4). P는 **연간** 확률이라
    연비용에 그대로 더한다(l2.model.predict_proba 독스트링 참조).

    시세와 선순위 둘 다 필요하다. 없을 때 0으로 계산하면 "위험 없음"으로 읽히므로
    반드시 adjusted=False와 사유를 남긴다 (CLAUDE.md 원칙 5 — 한계를 먼저 말한다).

    시세가 추정치일 때는 jeonse_ratio·lien_ratio(→P)와 LGD 양쪽에 들어가 오차가
    증폭되므로 점추정만 주지 않고 밴드를 함께 낸다. 밴드 폭은 `listing["price_level"]`
    (지번/동/구)에 따라 달라진다 — 구 평균에 지번 단위와 같은 폭을 붙이면 거짓 정밀도다.
    사용자가 매매가를 직접 입력했으면 `price_level`이 없으므로 밴드도 없다.
    """
    price = listing.get("market_price_krw")
    senior = listing.get("senior_claims_krw")
    missing = []
    if not price:
        missing.append("시세(예상 매매가)")
    if senior is None:
        missing.append("선순위 채권최고액")
    if missing or deposit <= 0:
        # '정보가'로 받아 조사(이/가) 문제를 피한다 — 앞 단어의 받침에 따라 달라진다.
        reason = (
            f"{' · '.join(missing)} 정보가 없어 미회수 위험을 반영하지 못했어요"
            if missing
            else "보증금이 0이라 미회수 위험이 없어요"
        )
        return {"adjusted": False, "reason": reason}

    # 낙찰가율은 **매물이 있는 지역**의 통계다. profile.region은 사용자의 희망지역이라
    # 매물 소재지와 다를 수 있다(등기부 없이 채권최고액만 넣거나, 업로드 후 희망지역을
    # 바꾼 경우). listing.region을 우선하고 없을 때만 희망지역으로 떨어진다.
    # 매물 소재지. 낙찰가율과 최우선변제 둘 다 **매물이 있는 지역** 기준이다.
    region = listing.get("region") or profile.get("region", "default")
    rate = engine.auction_rate(region, listing.get("building_type", "기타"), auction_rates)

    def at(p: int) -> dict:
        """시세 p에서의 위험 — 민감도 밴드도 같은 경로로 만든다(l3.risk 단일 정의)."""
        return deposit_risk(
            deposit=deposit, market_price=p, senior_claims=senior,
            building_type=listing.get("building_type"), auction_rate=rate,
            model=model, insured=bool(listing.get("insured", False)),
            priority_rule=priority_rule, region=region,
        )

    base = at(price)
    # 불확실성이 두 갈래다 — 둘 다 반영해야 범위가 정직하다.
    #  (1) 시세 추정 오차: 집계 단위가 넓을수록 크다. 사용자가 직접 넣었으면 0.
    #  (2) 사고확률의 시점 변동: 보증사고율이 해마다 크게 움직인다(전국 8.1% → 1.0%).
    band = _price_band(listing, uncertainty_rule)
    low, high = base["e_loss_from_p_range"]
    if band:
        # 시세가 높으면 회수액이 커져 손실이 준다 → 상단 시세가 하한, 하단 시세가 상한
        low = min(low, at(round(price * (1 + band)))["e_loss_from_p_range"][0])
        high = max(high, at(round(price * (1 - band)))["e_loss_from_p_range"][1])
    return {
        "adjusted": True,
        "price_band": band,
        "price_level": listing.get("price_level"),
        "p_accident": base["p_accident"],
        "p_accident_range": base["p_accident_range"],
        "lgd": base["lgd"],
        "e_loss_krw": base["e_loss_krw"],
        "e_loss_range_krw": [low, high],
        "market_price_krw": price,
        "senior_claims_krw": senior,
        "auction_rate": rate,
        "insured": bool(listing.get("insured", False)),
        # 소액임차인 최우선변제로 선순위보다 먼저 배당받는 금액(0이면 해당 없음)
        "priority_krw": base["priority_krw"],
        # 0인 이유가 "해당 없음"인지 "지역 미지원"인지 화면이 구분해야 한다.
        # 지금은 서울만 지원하고, 서울 밖은 보호를 얹지 않아 기대손실이 크게 잡힌다.
        "priority_supported": base["priority_supported"],
        "priority_region_scope": base["priority_region_scope"],
        "data_note": model.data_note,
    }


def _annual_support(
    eligible: list[dict], stay_years: int, kind: str = "wolse"
) -> tuple[int, str | None, dict | None]:
    """이 용도의 지원금 연평균액 → (연액, 상품명, 출처). 룰에서 읽는다(금액 하드코딩 금지).

    `applies_to`로 용도를 걸러야 한다 — `_best_policy_loan`과 같은 이유다. 지금은
    지원 상품이 월세용 하나뿐이라 필터가 없어도 같은 결과가 나오지만, 전세용·매수용
    지원이 추가되면 월세 비용에서 조용히 차감된다(결함 F와 동일한 구조).

    한시 지원(예: 24개월)을 매년 반복 차감하면 과대 계상이다 — 4년 거주 시 총 960만원을
    빼는데 실제 상한은 480만원이다. 총지원액을 거주기간으로 나눠 연평균화한다.
    거주가 지원기간보다 짧으면 실제로 받은 개월분만 인정한다.
    """
    years = max(stay_years, 1)
    for e in eligible:
        if e.get("product_type") != "subsidy" or kind not in (e.get("applies_to") or []):
            continue
        monthly = e["terms"].get("monthly_support_krw")
        if not monthly:
            continue
        total = monthly * min(e["terms"].get("support_months") or 0, years * 12)
        return round(total / years), e["product_name"], _cite(e)
    return 0, None, None


def compare_jeonse_wolse(
    profile, jeonse, wolse, *, products, market_params, tax_rules,
    auction_rates=None, risk_model=None, listing=None,
) -> dict:
    """전세 vs 월세 연비용 비교 — 혜택 반영. jeonse={deposit_krw}, wolse={deposit_krw, monthly_rent_krw}.

    각 안의 `breakdown`이 단일 진실 원천이고 `annual_krw`는 그 합이다 — 화면의 항목별 표가
    헤드라인과 어긋날 수 없다. 정책대출은 용도(`applies_to`)와 한도를 모두 반영한다.
    """
    assets = profile["assets_krw"]
    opp = market_params["opportunity_rate"]
    market_rate = market_params["loan_rate_jeonse"]
    stay_years = profile.get("expected_stay_years", 4)
    auction_rates = auction_rates or load_rules("auction_rates")
    risk_model = risk_model or load_risk_model()
    # 시세·선순위는 매물 정보라 listing에 있다. 두 안이 같은 매물을 다르게 계약하는
    # 비교이므로 위험 입력도 공유한다(전세 2억이든 월세 2천만이든 같은 집·같은 선순위).
    risk_src = listing if listing is not None else {}

    # 전세 — 전세용 정책대출을 한도까지만, 초과분은 시장금리
    jz_elig = recommend(_eligibility_input(profile, jeonse), products)["eligible"]
    jz_loan = _best_policy_loan("jeonse", jz_elig, market_rate)
    jz_break, jz_basis = _funding_breakdown(
        jeonse["deposit_krw"], assets, jz_loan, market_rate, opp
    )
    jz_risk = _risk(
        jeonse["deposit_krw"], risk_src, profile,
        auction_rates=auction_rates, model=risk_model,
        priority_rule=market_params.get("small_deposit_priority"),
        uncertainty_rule=market_params.get("price_uncertainty_by_level"),
    )
    jz_break["미회수기대손실"] = jz_risk.get("e_loss_krw", 0)
    jz_cost = sum(jz_break.values())

    # 월세 — 보증금에도 같은 정책대출을 적용(전세만 혜택받던 편향 제거)
    ws_deposit = wolse.get("deposit_krw", 0)
    ws_elig = recommend(_eligibility_input(profile, wolse), products)["eligible"]
    ws_loan = _best_policy_loan("wolse", ws_elig, market_rate)
    annual_rent = wolse["monthly_rent_krw"] * 12
    support, support_name, support_source = _annual_support(ws_elig, stay_years, "wolse")
    # 월세 보증금에도 같은 위험 기계를 돌린다. compare.py(Streamlit)는 월세 E[Loss]를
    # 0으로 하드코딩하는데, 여기선 대칭으로 계산한다 — 보증금이 작으면 전세가율이
    # 낮아 모델이 자연히 낮은 P를 내므로(실측 0.16%) 비대칭 하드코딩보다 방어하기 쉽다.
    # 한계: 소액임차인 최우선변제는 미반영이라 월세 위험이 다소 과대일 수 있다.
    ws_risk = _risk(
        ws_deposit, risk_src, profile,
        auction_rates=auction_rates, model=risk_model,
        priority_rule=market_params.get("small_deposit_priority"),
        uncertainty_rule=market_params.get("price_uncertainty_by_level"),
    )
    ws_funding, ws_basis = _funding_breakdown(ws_deposit, assets, ws_loan, market_rate, opp)
    ws_break = {
        "연월세": annual_rent,
        "월세세액공제": -engine.wolse_tax_credit(
            annual_rent, profile["monthly_income_krw"] * 12, tax_rules
        ),
        **ws_funding,
        "청년월세지원": -support,
        "미회수기대손실": ws_risk.get("e_loss_krw", 0),
    }
    ws_cost = sum(ws_break.values())

    return {
        "jeonse": {
            "annual_krw": jz_cost,
            "breakdown": jz_break,
            "loan_rate": jz_loan["rate"],
            "loan_limit_krw": jz_loan["limit"],
            "product_name": jz_loan["product_name"],
            "loan_benefit": jz_loan["product_name"] is not None,
            "loan_source": jz_loan["source"],
            "funding": jz_basis,
            "risk": jz_risk,
        },
        "wolse": {
            "annual_krw": ws_cost,
            "breakdown": ws_break,
            "loan_rate": ws_loan["rate"],
            "loan_limit_krw": ws_loan["limit"],
            "product_name": ws_loan["product_name"],
            "loan_benefit": ws_loan["product_name"] is not None,
            "loan_source": ws_loan["source"],
            "support_annual_krw": support,
            "support_name": support_name,
            "support_source": support_source,
            "support_stay_years": stay_years,
            "monthly_support": support > 0,
            "funding": ws_basis,
            "risk": ws_risk,
        },
        "cheaper": "전세" if jz_cost < ws_cost else "월세",
        "diff_krw": abs(jz_cost - ws_cost),
        # 두 안이 공유하는 금리와 그 근거. 정책금리는 상품마다 달라 각 안의 loan_rate에 있다.
        # 전부 가정값이고 일부는 아직 검증 전(`[확인]`)이라 화면이 감추면 안 된다.
        "rates": {
            "market_loan": market_rate,
            "opportunity": opp,
            "market_loan_source": market_params.get("loan_rate_source", ""),
            "opportunity_source": market_params.get("opportunity_source", ""),
        },
    }


def decide(
    profile: dict, listing: dict, *, products=None, market_params=None, tax_rules=None,
    auction_rates=None, risk_model=None,
) -> dict:
    """프로필+매물 → {affordability, recommendations, comparison?, sources}.

    **월소득 0을 거절하지 않는다.** 무소득 청년(학생·구직자·프리랜서 준비기)은 이
    서비스가 답해야 할 대상이다. 청년전용 버팀목전세자금대출은 소득 상한만 있고
    하한이 없어 무소득도 신청 대상이다 — 소득 때문에 못 받는 상품이 있으면 그건
    에러가 아니라 recommend()의 미자격 반증으로 나와야 한다.
    RIR만 분모가 소득이라 산출이 불가능한데, 그건 affordability.available=False로 말한다.
    """
    if profile.get("monthly_income_krw", 0) < 0:
        raise ValueError("monthly_income_krw(월소득)이 음수입니다")
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
            auction_rates=auction_rates, risk_model=risk_model, listing=listing,
        )
    return result
