"""L0 룰 파이프라인 테스트 — 추출↔검증 LLM 분리 + 경계값 테스트 게이트."""

import json

import pytest

from onjeon.l0.rule_pipeline import (
    extract_rule,
    pipeline,
    run_boundary_tests,
    verify_rule,
)
from onjeon.llm import MockLLM

GOOD_RULE = {
    "rule_id": "youth-wolse-loan-2026-07",
    "product_name": "청년 주거안정 월세대출",
    "version": "2026-07 기준",
    "source": {"url": "https://example.gov", "clause_refs": ["제1호", "제2호"]},
    "criteria": [
        {
            "field": "age",
            "op": "<=",
            "value": 34,
            "clause": "대출대상 제1호",
            "boundary_tests": [
                {"input": 34, "expect": True},
                {"input": 35, "expect": False},
            ],
        }
    ],
    "alternatives": [],
}

VERIFY_OK = json.dumps({"consistent": True, "confidence": "high", "issues": []})
VERIFY_LOW = json.dumps({"consistent": True, "confidence": "low", "issues": ["소득 기준 모호"]})
VERIFY_BAD = json.dumps({"consistent": False, "confidence": "high", "issues": ["나이 상한 불일치"]})


def rule_response(rule: dict) -> str:
    return "```json\n" + json.dumps(rule, ensure_ascii=False) + "\n```"


class TestExtractRule:
    def test_parses_fenced_json(self):
        llm = MockLLM([rule_response(GOOD_RULE)])
        rule = extract_rule("공고 원문…", llm)
        assert rule["rule_id"] == "youth-wolse-loan-2026-07"
        assert "공고 원문…" in llm.calls[0]["prompt"]


class TestVerifyRule:
    def test_returns_verdict(self):
        llm = MockLLM([VERIFY_OK])
        verdict = verify_rule(GOOD_RULE, "공고 원문…", llm)
        assert verdict["consistent"] is True
        assert verdict["confidence"] == "high"


class TestBoundaryTests:
    def test_good_rule_passes(self):
        assert run_boundary_tests(GOOD_RULE) == []

    def test_wrong_expectation_fails(self):
        bad = json.loads(json.dumps(GOOD_RULE))
        bad["criteria"][0]["boundary_tests"][1]["expect"] = True  # 35세 통과를 기대 — 오류
        failures = run_boundary_tests(bad)
        assert failures and "age" in failures[0]


class TestPipeline:
    def test_same_llm_object_rejected(self):
        llm = MockLLM([rule_response(GOOD_RULE), VERIFY_OK])
        with pytest.raises(ValueError):
            pipeline("공고", extract_llm=llm, verify_llm=llm)

    def test_happy_path_approved(self):
        result = pipeline(
            "공고",
            extract_llm=MockLLM([rule_response(GOOD_RULE)]),
            verify_llm=MockLLM([VERIFY_OK]),
        )
        assert result.approved is True
        assert result.needs_human is False
        assert result.rule["rule_id"] == "youth-wolse-loan-2026-07"

    def test_low_confidence_needs_human(self):
        result = pipeline(
            "공고",
            extract_llm=MockLLM([rule_response(GOOD_RULE)]),
            verify_llm=MockLLM([VERIFY_LOW]),
        )
        assert result.approved is False
        assert result.needs_human is True

    def test_inconsistent_rejected(self):
        result = pipeline(
            "공고",
            extract_llm=MockLLM([rule_response(GOOD_RULE)]),
            verify_llm=MockLLM([VERIFY_BAD]),
        )
        assert result.approved is False
        assert any("불일치" in r or "검증" in r for r in result.reasons)

    def test_malformed_rule_rejected_without_crash(self):
        # 추출 LLM이 criteria 없는 JSON을 반환해도 크래시가 아니라 반영 거부여야 한다
        result = pipeline(
            "공고",
            extract_llm=MockLLM([rule_response({"rule_id": "broken"})]),
            verify_llm=MockLLM([VERIFY_OK]),
        )
        assert result.approved is False
        assert any("스키마" in r for r in result.reasons)

    def test_criterion_without_boundary_tests_rejected(self):
        # 경계값 테스트가 없는 룰은 '통과'가 아니라 반영 거부 (CLAUDE.md 원칙 4)
        rule = json.loads(json.dumps(GOOD_RULE))
        del rule["criteria"][0]["boundary_tests"]
        result = pipeline(
            "공고",
            extract_llm=MockLLM([rule_response(rule)]),
            verify_llm=MockLLM([VERIFY_OK]),
        )
        assert result.approved is False
        assert any("스키마" in r or "경계값" in r for r in result.reasons)

    def test_boundary_failure_rejected(self):
        bad = json.loads(json.dumps(GOOD_RULE))
        bad["criteria"][0]["boundary_tests"][0]["expect"] = False
        result = pipeline(
            "공고",
            extract_llm=MockLLM([rule_response(bad)]),
            verify_llm=MockLLM([VERIFY_OK]),
        )
        assert result.approved is False
        assert any("경계값" in r for r in result.reasons)
