"""등기부에 **적힌** 권리 제한 → 위험 등급. 룰 테이블 lookup, LLM 아님(원칙 1).

`l3/risk.py`에 넣지 않는 이유: 그 모듈은 P(사고)→LGD→E[Loss]의 단일 정의다.
여기는 **다른 축**이다 — 갑구·을구가 깨끗해도 전세가율이 높으면 기대손실은 크고,
그 반대도 성립한다. 한 모듈에 섞으면 두 번째 정의가 생기고, 화면이 둘을 하나의
'위험도'로 읽게 만든다.

순수 함수 — IO는 룰 JSON 로드뿐.
"""

from __future__ import annotations

from datetime import date as _date

from onjeon.rules_io import load_rules


def grade_register(fields: dict) -> dict:
    """파서 결과(`register.parse.extract_fields`) → {grade, label, items, note}.

    등급은 항목의 최댓값이다: high 하나라도 있으면 high, caution만 있으면 caution.

    **못 읽은 문서는 🟢로 내보내지 않는다**(원칙 5). OCR이거나 채권최고액을 못 읽은
    상태에서 아무 항목도 안 잡혔다면, 그건 "권리 제한이 없다"가 아니라 "못 봤다"다
    → `unknown`. 반대로 그 상태에서도 가압류·경매개시가 **잡혔다면** 등급을 내리지
    않는다 — 저신뢰라는 이유로 진짜 적신호를 '판정 보류'에 묻으면 안 된다.
    """
    rules = load_rules("register_risk")
    items = [
        dict(right)
        for right in fields.get("rights") or []
        if right.get("grade") and not right.get("cancelled")
    ]
    items += _derived(fields, rules["derived"])
    grade = "high" if any(i["grade"] == "high" for i in items) else "caution" if items else "low"

    note = None
    if fields.get("ocr"):
        note = (
            "스캔·촬영본을 글자 인식으로 읽어서 항목을 놓쳤을 수 있어요 — "
            "등기부 원본의 갑구·을구를 직접 대조해 주세요."
        )
    elif fields.get("senior_claims_krw") is None:
        note = (
            "을구의 채권최고액을 읽지 못했어요. 을구를 제대로 못 읽었다면 "
            "여기 안 잡힌 권리도 있을 수 있습니다."
        )
    if grade == "low" and note:
        grade = "unknown"

    return {
        "grade": grade,
        "label": rules["grades"][grade],
        "items": items,
        "note": note,
        "rules_version": rules["version"],
    }


def _derived(fields: dict, rules: dict) -> list[dict]:
    """항목 하나로는 안 보이고 **여러 건의 관계**에서 나오는 신호.

    근저당 건수는 파서가 이미 세어 뒀고(`senior_claims_count`), 소유권 이전 빈도는
    갑구에서 읽은 접수일로 센다. 둘 다 문서에 적힌 사실이지 추정이 아니다.
    """
    out = []
    many = rules["many_liens"]
    count = fields.get("senior_claims_count") or 0
    if count >= many["threshold"]:
        out.append(_entry(f"근저당 {count}건", "을구", f"근저당권 {count}건", many))

    freq = rules["frequent_transfer"]
    dates = sorted(
        right["date"]
        for right in fields.get("rights") or []
        if right.get("key") == "소유권이전" and right.get("date") and not right.get("cancelled")
    )
    if _clustered(dates, freq["count"], freq["within_days"]):
        out.append(
            _entry("잦은 소유권 이전", "갑구", f"소유권이전 접수일 {', '.join(dates)}", freq)
        )
    return out


def _entry(key: str, section: str, quote: str, rule: dict) -> dict:
    return {
        "key": key,
        "section": section,
        "rank": None,
        "date": None,
        "quote": quote,
        "grade": rule["grade"],
        "why": rule["why"],
        "action": rule["action"],
        "cancelled": False,
    }


def _clustered(dates: list[str], count: int, days: int) -> bool:
    """정렬된 날짜 중 `count`건이 `days` 안에 몰려 있는가.

    OCR이 날짜를 '2024년13월45일'로 읽으면 `fromisoformat`이 던진다 — 그 문서는
    이 신호를 못 내는 게 맞지, 전체 판정을 죽일 일이 아니다.
    """
    try:
        parsed = [_date.fromisoformat(d) for d in dates]
    except ValueError:
        return False
    return any(
        (parsed[i + count - 1] - parsed[i]).days <= days for i in range(len(parsed) - count + 1)
    )
