"""L0 정책 룰 자동화 파이프라인 — 공고 원문 → 자격요건 JSON 룰.

원칙 (CLAUDE.md 4): 추출 LLM과 검증 LLM은 반드시 분리하고,
경계값 테스트를 통과해야 룰 DB에 반영한다. 저신뢰 항목은 사람 승인 큐로.
상시 크롤러·검수 큐는 데모 범위 밖 (다이어그램으로 제시 — docs/workflow.md).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from jsonschema import Draft202012Validator

from onjeon.l3.eligibility import check_criterion
from onjeon.llm import LLMClient

EXTRACT_SYSTEM = "너는 한국 주거 정책 공고에서 자격요건을 구조화하는 추출기다. JSON만 출력한다."

EXTRACT_PROMPT_TEMPLATE = """다음 정책 공고에서 자격요건을 JSON 룰로 추출하라.

규칙:
1. 각 조건(criteria)에 공고 원문의 조항 출처(clause)를 기록하라.
2. 각 조건마다 경계값 테스트(boundary_tests)를 생성하라
   (예: "만 34세 이하" → 34는 통과, 35는 탈락).
3. 나이·금액은 정수로. 확실하지 않은 항목은 만들지 마라.

출력 스키마:
{{
  "rule_id": "kebab-case-id",
  "product_name": "상품명",
  "version": "YYYY-MM 기준",
  "source": {{"url": "...", "clause_refs": ["제1호", ...]}},
  "criteria": [{{"field": "age|annual_income_krw|assets_krw|deposit_krw",
                "op": "<=|>=|==|in", "value": ..., "clause": "제N호",
                "boundary_tests": [{{"input": ..., "expect": true}}, ...]}}],
  "alternatives": []
}}

공고 원문:
{announcement}

JSON만 출력하라."""

VERIFY_SYSTEM = "너는 추출된 룰이 공고 원문과 일치하는지 교차 검증하는 감사자다. JSON만 출력한다."

VERIFY_PROMPT_TEMPLATE = """추출된 룰이 공고 원문과 일치하는지 검증하라.
숫자·단위·경계(이하/미만)의 불일치를 특히 확인하라.

출력: {{"consistent": true|false, "confidence": "high"|"low", "issues": ["..."]}}

공고 원문:
{announcement}

추출된 룰:
{rule}

JSON만 출력하라."""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

# 추출 룰의 스키마 게이트 — CLAUDE.md 컨벤션: LLM 추출 결과는 스키마 검증 후에만 사용
RULE_SCHEMA = {
    "type": "object",
    "required": ["rule_id", "product_name", "version", "criteria"],
    "properties": {
        "rule_id": {"type": "string", "minLength": 1},
        "product_name": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "criteria": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["field", "op", "value", "clause", "boundary_tests"],
                "properties": {
                    "field": {"type": "string", "minLength": 1},
                    "op": {"enum": ["<=", ">=", "==", "in"]},
                    "clause": {"type": "string", "minLength": 1},
                    "boundary_tests": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "object", "required": ["input", "expect"]},
                    },
                },
            },
        },
    },
}
_RULE_VALIDATOR = Draft202012Validator(RULE_SCHEMA)


def validate_rule(rule: dict) -> list[str]:
    """추출 룰을 스키마에 대조한다. 빈 목록 = 통과."""
    return [
        f"{'/'.join(str(p) for p in error.absolute_path) or '<root>'}: {error.message}"
        for error in _RULE_VALIDATOR.iter_errors(rule)
    ]


def _parse_json(text: str) -> dict:
    match = _FENCE_RE.search(text)
    payload = match.group(1) if match else text.strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 응답이 JSON이 아니다: {text[:80]!r}") from exc


def extract_rule(announcement: str, llm: LLMClient) -> dict:
    """공고 원문 → 자격요건 룰 JSON (추출 단계)."""
    raw = llm.complete(
        EXTRACT_PROMPT_TEMPLATE.format(announcement=announcement), system=EXTRACT_SYSTEM
    )
    return _parse_json(raw)


def verify_rule(rule: dict, announcement: str, llm: LLMClient) -> dict:
    """추출과 분리된 LLM이 룰-원문 일치 여부를 교차 검증한다."""
    raw = llm.complete(
        VERIFY_PROMPT_TEMPLATE.format(
            announcement=announcement, rule=json.dumps(rule, ensure_ascii=False)
        ),
        system=VERIFY_SYSTEM,
    )
    return _parse_json(raw)


def run_boundary_tests(rule: dict) -> list[str]:
    """룰에 내장된 경계값 테스트를 결정론 엔진(check_criterion)으로 실행."""
    failures = []
    for criterion in rule["criteria"]:
        for test in criterion.get("boundary_tests", []):
            actual = check_criterion(test["input"], criterion["op"], criterion["value"])
            if actual != test["expect"]:
                failures.append(
                    f"{criterion['field']}: input={test['input']} expect={test['expect']} got={actual}"
                )
    return failures


@dataclass
class RulePipelineResult:
    rule: dict
    approved: bool
    needs_human: bool
    reasons: list[str] = field(default_factory=list)


def pipeline(
    announcement: str, *, extract_llm: LLMClient, verify_llm: LLMClient
) -> RulePipelineResult:
    """공고 → 추출 → 교차 검증 → 경계값 테스트 → 승인/사람 큐."""
    if extract_llm is verify_llm:
        raise ValueError("추출 LLM과 검증 LLM은 분리해야 한다 (CLAUDE.md 원칙 4)")

    rule = extract_rule(announcement, extract_llm)

    schema_errors = validate_rule(rule)
    if schema_errors:
        # 형태가 깨진 룰은 검증·경계값 단계로 보내지 않고 즉시 거부
        return RulePipelineResult(
            rule=rule,
            approved=False,
            needs_human=False,
            reasons=[f"룰 스키마 위반: {schema_errors}"],
        )

    reasons: list[str] = []

    verdict = verify_rule(rule, announcement, verify_llm)
    if not verdict.get("consistent", False):
        reasons.append(f"검증 LLM 불일치 판정: {verdict.get('issues', [])}")

    boundary_failures = run_boundary_tests(rule)
    if boundary_failures:
        reasons.append(f"경계값 테스트 실패: {boundary_failures}")

    needs_human = verdict.get("confidence") == "low"
    if needs_human:
        reasons.append("신뢰도 low — 사람 승인 큐로")

    return RulePipelineResult(
        rule=rule,
        approved=not reasons,
        needs_human=needs_human,
        reasons=reasons,
    )
