"""LLM 추상화 테스트 — MockLLM은 API 키 없이 전체 데모를 돌리는 기반."""

import pytest

from onjeon.llm import AnthropicLLM, GeminiLLM, MockLLM, default_llm, make_llm

ALL_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY")


class TestProviderSelection:
    def test_gemini_key_selects_gemini(self, monkeypatch):
        for key in ALL_KEYS:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        assert isinstance(default_llm(), GeminiLLM)

    def test_gemini_priority_over_anthropic(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "g-key")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")
        assert isinstance(default_llm(), GeminiLLM)

    def test_anthropic_fallback(self, monkeypatch):
        for key in ALL_KEYS:
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")
        assert isinstance(default_llm(), AnthropicLLM)

    def test_no_key_returns_none(self, monkeypatch):
        for key in ALL_KEYS:
            monkeypatch.delenv(key, raising=False)
        assert default_llm() is None

    def test_make_llm_returns_fresh_instances(self, monkeypatch):
        # L0 추출↔검증 분리 원칙: 매 호출 새 인스턴스여야 한다
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        assert make_llm() is not make_llm()

    def test_gemini_default_model(self, monkeypatch):
        monkeypatch.delenv("ONJEON_MODEL", raising=False)
        assert GeminiLLM().model == "gemini-2.5-flash"

    def test_gemini_model_env_override(self, monkeypatch):
        monkeypatch.setenv("ONJEON_MODEL", "gemini-2.5-pro")
        assert GeminiLLM().model == "gemini-2.5-pro"


class TestMockLLM:
    def test_returns_responses_in_order(self):
        llm = MockLLM(["첫번째", "두번째"])
        assert llm.complete("q1") == "첫번째"
        assert llm.complete("q2") == "두번째"

    def test_records_calls(self):
        llm = MockLLM(["ok"])
        llm.complete("질문", system="시스템", images=["img-bytes"])
        [call] = llm.calls
        assert call["prompt"] == "질문"
        assert call["system"] == "시스템"
        assert call["images"] == ["img-bytes"]

    def test_exhausted_responses_raises(self):
        llm = MockLLM(["only-one"])
        llm.complete("q1")
        with pytest.raises(RuntimeError):
            llm.complete("q2")
