"""L1 추출 결과 스키마 게이트.

LLM 추출 JSON은 이 게이트를 통과한 뒤에만 L2/L3로 전달된다 (CLAUDE.md 원칙 4).
모든 갑구/을구 항목에 원문 좌표(source_loc)가 있어야 인용·하이라이트가 가능하다.
스키마 정의: docs/design.md §2.
"""

from __future__ import annotations

from jsonschema import Draft202012Validator

# source_loc는 있으면 형식 검증하되 필수 아님 — 인용용 부가 정보(계산엔 불필요)
_SOURCE_LOC = {
    "type": "object",
    "properties": {
        "page": {"type": "integer"},
        "section": {"type": "string"},
        "entry_no": {"type": "integer"},
    },
}

# 등기 항목: '무엇인지(type)'만 필수. 실물 등기부에서 Gemini가 rank·cancelled·
# source_loc을 항상 채우지는 못하므로 나머지는 모두 선택. 없으면 하위 코드가
# 보수적 기본값(말소 안 됨 등)으로 처리한다.
_GAP_ITEM = {
    "type": "object",
    "required": ["type"],
    "properties": {
        "rank": {"type": "integer"},
        "type": {"type": "string"},
        "date": {"type": "string"},
        "cancelled": {"type": "boolean"},
        "source_loc": _SOURCE_LOC,
    },
}
_EUL_ITEM = {
    "type": "object",
    "required": ["type"],
    "properties": {
        "rank": {"type": "integer"},
        "type": {"type": "string"},
        "max_claim_krw": {"type": "integer", "minimum": 0},
        "set_date": {"type": "string"},
        "cancelled": {"type": "boolean"},
        "source_loc": _SOURCE_LOC,
    },
}

REGISTER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["property", "register"],
    "properties": {
        "property": {
            "type": "object",
            # 계산에 실제로 쓰는 것만 필수. building_type은 enum 제거(실물은
            # '다세대주택'·'공동주택' 등 다양) — _auction_rate가 미지 유형을 폴백 처리.
            "required": ["address", "building_type", "market_price_krw", "price_source"],
            "properties": {
                "address": {"type": "string", "minLength": 1},
                "building_type": {"type": "string", "minLength": 1},
                "market_price_krw": {"type": "integer", "minimum": 0},
                "price_source": {
                    "type": "object",
                    "required": ["queried_at"],
                    "properties": {
                        "api": {"type": "string"},
                        "queried_at": {"type": "string"},
                    },
                },
            },
        },
        "register": {
            "type": "object",
            # 계산 대상 2섹션만 필수. title_section·senior_lease_deposits_krw는
            # 선택(senior_claims가 .get으로 안전 처리).
            "required": ["gap_section", "eul_section"],
            "properties": {
                "title_section": {"type": "object"},
                "gap_section": {"type": "array", "items": _GAP_ITEM},
                "eul_section": {"type": "array", "items": _EUL_ITEM},
                "senior_lease_deposits_krw": {"type": "integer", "minimum": 0},
            },
        },
    },
}

_VALIDATOR = Draft202012Validator(REGISTER_SCHEMA)


class ExtractionInvalid(Exception):
    """스키마 게이트 실패 — 하위 레이어 전달 금지."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_extraction(doc: dict) -> list[str]:
    """추출 JSON을 스키마에 대조해 오류 목록을 돌려준다. 빈 목록 = 통과."""
    return [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in _VALIDATOR.iter_errors(doc)
    ]


def gate(doc: dict) -> dict:
    """통과 시 문서 반환, 실패 시 ExtractionInvalid — L2/L3 진입 차단."""
    errors = validate_extraction(doc)
    if errors:
        raise ExtractionInvalid(errors)
    return doc


def senior_claims(register: dict) -> int:
    """선순위 채권 합계 = 말소되지 않은 을구 채권최고액 + 선순위 임차보증금.

    채권최고액 기준(실채권 아님)의 보수적 추정 — 한계는 리포트에 명시한다.
    """
    # cancelled 누락 시 '말소 안 됨'으로 보수적 처리(위험 과소평가 방지).
    # senior_lease_deposits_krw 누락 시 0. 실물 추출의 필드 결손에 안전.
    liens = sum(
        entry.get("max_claim_krw") or 0
        for entry in register.get("eul_section", [])
        if not entry.get("cancelled", False)
    )
    return liens + (register.get("senior_lease_deposits_krw") or 0)
