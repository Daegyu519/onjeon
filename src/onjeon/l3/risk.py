"""L3 보증금 미회수 위험 — 피처 구성 → P(사고) → LGD → E[Loss]의 단일 정의.

왜 별도 모듈인가: `compare.py`(Streamlit 3안 비교)와 `decision.py`(배포 경로)가
각각 같은 계산을 따로 구현하고 있었다. 같은 제품이 두 경로에서 다른 답을 낼 수 있는
구조였고, 실제로 `compare.py`는 월세 E[Loss]를 0으로 하드코딩했다. 이제 둘 다 여기를 쓴다.

순수 함수 — IO 없음, LLM 없음. 모델은 주입받는다(l2.RiskModel 또는 같은 인터페이스).
금액은 원(₩) 정수.
"""

from __future__ import annotations

from onjeon.l3 import engine


def priority_amount(deposit: int, rule: dict | None, region: str | None = None) -> int:
    """소액임차인 최우선변제액 — 주택임대차보호법 §8, 시행령 §10·§11.

    보증금이 기준액(`threshold_krw`) 이하일 때만 소액임차인이고, 그때 한도
    (`limit_krw`)까지 선순위보다 먼저 배당받는다. 보증금이 한도보다 작으면 전액.

    **서울 밖이면 0을 낸다.** 시행령은 지역을 4구간으로 나누고 금액이 2배 이상
    벌어진다(서울 5,500만 / 그 밖의 지역 2,500만, 기준액 1억6,500만 / 7,500만).
    전국에 서울 값을 쓰면 비서울 매물이 받지도 못할 보호를 받은 것으로 계산돼
    **위험이 과소평가된다** — 위험한 집이 안전해 보이는 방향이다.

    지금은 서울만 지원한다. 비서울은 보호를 0으로 두고(과대평가 방향이라 안전)
    호출측이 `priority_supported=False`로 사용자에게 사실을 말한다.

    룰이 없어도 **0** — 없는 보호를 가정하지 않는다.
    """
    if not rule or not _region_supported(rule, region):
        return 0
    threshold = rule.get("threshold_krw") or 0
    limit = rule.get("limit_krw") or 0
    if deposit > threshold:
        return 0
    return min(deposit, limit)


def _region_supported(rule: dict, region: str | None) -> bool:
    """이 매물 지역에 룰의 금액을 적용해도 되는가.

    region이 None이면 어디인지 모르는 것이다 — 모를 때 적용하면 비서울에 서울 값을
    쓰게 되므로 적용하지 않는다(모름 ≠ 서울).

    판정 토큰은 룰 데이터(`region_match`)에 있다. region이 '관악구'처럼 시군구만
    오기도 하고 '서울특별시 관악구 …'처럼 주소로 오기도 해서 양쪽을 다 맞춰야 한다.
    코드에 지역명을 박으면 룰만 고쳐서는 지역을 못 늘린다(CLAUDE.md 원칙 3).
    """
    if not rule.get("region_scope"):  # 지역 제한이 없는 룰이면 그대로 적용
        return True
    if not region:
        return False
    return any(tok and tok in region for tok in rule.get("region_match") or [])


def deposit_risk(
    *,
    deposit: int,
    market_price: int,
    senior_claims: int,
    building_type: str | None,
    auction_rate: float,
    model,
    insured: bool = False,
    priority_rule: dict | None = None,
    region: str | None = None,
) -> dict:
    """보증금 미회수 위험 → {features, p_accident, lgd, e_loss_krw, priority_krw}.

    E[Loss] = P(사고) × LGD × 보증금 (docs/design.md §4).
    P는 **연간** 확률이므로 반환값도 연간 기대손실이다 — 연비용에 그대로 더한다
    (l2.model.RiskModel.predict_proba 독스트링 참조).
    """
    if market_price <= 0:
        raise ValueError(f"시세가 0 이하라 전세가율·근저당비율을 계산할 수 없다: {market_price!r}")
    features = {
        "jeonse_ratio": deposit / market_price,
        "lien_ratio": senior_claims / market_price,
        "is_villa": 1 if building_type == "빌라" else 0,
        "auction_rate": auction_rate,
    }
    priority = priority_amount(deposit, priority_rule, region)
    # 지역을 몰라서/서울이 아니라서 최우선변제를 못 적용했는가. 화면이 이걸 말해야
    # 사용자가 '왜 내 보증금은 보호가 0인가'를 알 수 있다.
    priority_supported = bool(priority_rule) and _region_supported(priority_rule, region)
    p_accident = model.predict_proba(features)
    loss_given = engine.lgd(
        market_price=market_price,
        auction_rate=auction_rate,
        senior_claims=senior_claims,
        deposit=deposit,
        insured=insured,
        priority_krw=priority,
    )
    # 사고확률 자체의 불확실성(시점 변동). 모델이 시점 데이터를 안 가지면 점추정 그대로.
    p_low, p_high = (model.predict_proba_band(features)
                     if hasattr(model, "predict_proba_band") else (p_accident, p_accident))
    return {
        "features": features,
        "p_accident": p_accident,
        "p_accident_range": [p_low, p_high],
        "lgd": loss_given,
        "e_loss_krw": engine.expected_loss(p_accident, loss_given, deposit),
        "e_loss_from_p_range": [
            engine.expected_loss(p_low, loss_given, deposit),
            engine.expected_loss(p_high, loss_given, deposit),
        ],
        "priority_krw": priority,
        "priority_supported": priority_supported,
        "priority_region_scope": (priority_rule or {}).get("region_scope"),
    }
