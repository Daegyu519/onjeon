"""L3 보증금 미회수 위험 — 피처 구성 → P(사고) → LGD → E[Loss]의 단일 정의.

왜 별도 모듈인가: `compare.py`(Streamlit 3안 비교)와 `decision.py`(배포 경로)가
각각 같은 계산을 따로 구현하고 있었다. 같은 제품이 두 경로에서 다른 답을 낼 수 있는
구조였고, 실제로 `compare.py`는 월세 E[Loss]를 0으로 하드코딩했다. 이제 둘 다 여기를 쓴다.

순수 함수 — IO 없음, LLM 없음. 모델은 주입받는다(l2.RiskModel 또는 같은 인터페이스).
금액은 원(₩) 정수.
"""

from __future__ import annotations

from onjeon.l3 import engine


def priority_amount(deposit: int, rule: dict | None) -> int:
    """소액임차인 최우선변제액 — 주택임대차보호법 §8, 시행령 §10·§11.

    보증금이 기준액(`threshold_krw`) 이하일 때만 소액임차인이고, 그때 한도
    (`limit_krw`)까지 선순위보다 먼저 배당받는다. 보증금이 한도보다 작으면 전액.

    룰이 없으면 **0** — 보호가 있다고 가정하지 않는다. 없는 보호를 가정하면
    위험을 과소평가하는데, 그건 이 제품이 가장 하면 안 되는 오류다.
    """
    if not rule:
        return 0
    threshold = rule.get("threshold_krw") or 0
    limit = rule.get("limit_krw") or 0
    if deposit > threshold:
        return 0
    return min(deposit, limit)


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
    priority = priority_amount(deposit, priority_rule)
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
    }
