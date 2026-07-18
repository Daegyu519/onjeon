"""L1 추출 결과 스키마 게이트.

LLM 추출 JSON은 이 게이트를 통과한 뒤에만 L2/L3로 전달된다 (CLAUDE.md 원칙 4).
모든 갑구/을구 항목에 원문 좌표(source_loc)가 있어야 인용·하이라이트가 가능하다.
스키마 정의: docs/design.md §2.
"""

from __future__ import annotations

from jsonschema import Draft202012Validator

_SOURCE_LOC = {
    "type": "object",
    "required": ["page", "section", "entry_no"],
    "properties": {
        "page": {"type": "integer"},
        "section": {"type": "string"},
        "entry_no": {"type": "integer"},
    },
}

REGISTER_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["property", "register"],
    "properties": {
        "property": {
            "type": "object",
            "required": ["address", "building_type", "market_price_krw", "price_source"],
            "properties": {
                "address": {"type": "string", "minLength": 1},
                "building_type": {"enum": ["빌라", "오피스텔", "아파트", "기타"]},
                "market_price_krw": {"type": "integer", "minimum": 0},
                "price_source": {
                    "type": "object",
                    "required": ["api", "queried_at"],
                    "properties": {
                        "api": {"type": "string"},
                        "queried_at": {"type": "string"},
                    },
                },
            },
        },
        "register": {
            "type": "object",
            "required": ["title_section", "gap_section", "eul_section", "senior_lease_deposits_krw"],
            "properties": {
                "title_section": {
                    "type": "object",
                    "required": ["owner"],
                    "properties": {"owner": {"type": "string"}},
                },
                "gap_section": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["rank", "type", "date", "cancelled", "source_loc"],
                        "properties": {
                            "rank": {"type": "integer"},
                            "type": {"type": "string"},
                            "date": {"type": "string"},
                            "cancelled": {"type": "boolean"},
                            "source_loc": _SOURCE_LOC,
                        },
                    },
                },
                "eul_section": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["rank", "type", "max_claim_krw", "set_date", "cancelled", "source_loc"],
                        "properties": {
                            "rank": {"type": "integer"},
                            "type": {"type": "string"},
                            "max_claim_krw": {"type": "integer", "minimum": 0},
                            "set_date": {"type": "string"},
                            "cancelled": {"type": "boolean"},
                            "source_loc": _SOURCE_LOC,
                        },
                    },
                },
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
    liens = sum(
        entry["max_claim_krw"]
        for entry in register["eul_section"]
        if not entry["cancelled"]
    )
    return liens + register["senior_lease_deposits_krw"]
