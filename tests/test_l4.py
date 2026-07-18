"""L4 what-if 에이전트 테스트 — LLM은 계산하지 않고 파라미터 조작·해석만 한다."""

import json

import pytest

from onjeon.l4.agent import WhatIfAgent
from onjeon.llm import MockLLM

BASE_PARAMS = {"annual_income_krw": 36_000_000, "assets_krw": 30_000_000}

TOOL_CALL = json.dumps(
    {
        "action": "call_tool",
        "tool": "run_comparison",
        "params_patch": {"annual_income_krw": 41_000_000},
    }
)
FINAL = json.dumps(
    {"action": "final", "answer": "연봉이 4,100만원이 되어도 월세가 여전히 유리합니다."}
)


@pytest.fixture
def tool_recorder():
    calls = []

    def run_comparison(params: dict) -> dict:
        calls.append(params)
        return {"jeonse_total": 8_130_000, "wolse_total": 6_874_000, "best": "월세"}

    return calls, {"run_comparison": run_comparison}


class TestWhatIfAgent:
    def test_patches_params_and_calls_tool(self, tool_recorder):
        calls, tools = tool_recorder
        agent = WhatIfAgent(MockLLM([TOOL_CALL, FINAL]), BASE_PARAMS, tools)
        agent.ask("연봉 500만원 오르면?")
        [params] = calls
        assert params["annual_income_krw"] == 41_000_000  # 패치 적용
        assert params["assets_krw"] == 30_000_000  # 나머지 보존

    def test_base_params_not_mutated(self, tool_recorder):
        _, tools = tool_recorder
        agent = WhatIfAgent(MockLLM([TOOL_CALL, FINAL]), BASE_PARAMS, tools)
        agent.ask("연봉 500만원 오르면?")
        assert BASE_PARAMS["annual_income_krw"] == 36_000_000

    def test_final_answer_returned_with_tool_results(self, tool_recorder):
        _, tools = tool_recorder
        agent = WhatIfAgent(MockLLM([TOOL_CALL, FINAL]), BASE_PARAMS, tools)
        result = agent.ask("연봉 500만원 오르면?")
        assert "월세" in result["answer"]
        assert result["tool_results"][0]["wolse_total"] == 6_874_000

    def test_interpretation_grounded_in_tool_result(self, tool_recorder):
        # 해석 요청 프롬프트에 엔진 결과가 포함되어야 한다 — LLM이 계산하지 않는 근거
        _, tools = tool_recorder
        llm = MockLLM([TOOL_CALL, FINAL])
        WhatIfAgent(llm, BASE_PARAMS, tools).ask("연봉 500만원 오르면?")
        assert "6874000" in llm.calls[1]["prompt"].replace(",", "")

    def test_followup_prompt_keeps_user_question(self, tool_recorder):
        # complete()는 무상태 — 후속 프롬프트에 질문이 없으면 LLM은 무엇에 답할지 모른다
        _, tools = tool_recorder
        llm = MockLLM([TOOL_CALL, FINAL])
        WhatIfAgent(llm, BASE_PARAMS, tools).ask("연봉 500만원 오르면?")
        assert "연봉 500만원 오르면?" in llm.calls[1]["prompt"]

    def test_direct_final_gets_corrective_retry(self, tool_recorder):
        # 엔진 미호출 final은 한 번 교정 재요청 — '계산 금지' 원칙의 구조적 강제
        calls, tools = tool_recorder
        llm = MockLLM([FINAL, TOOL_CALL, FINAL])
        result = WhatIfAgent(llm, BASE_PARAMS, tools).ask("연봉 500만원 오르면?")
        assert result["grounded"] is True
        assert len(result["tool_results"]) == 1
        assert "tool" in llm.calls[1]["prompt"]  # 교정 프롬프트가 tool 호출을 지시

    def test_persistent_direct_final_marked_ungrounded(self, tool_recorder):
        _, tools = tool_recorder
        llm = MockLLM([FINAL, FINAL])
        result = WhatIfAgent(llm, BASE_PARAMS, tools).ask("질문")
        assert result["grounded"] is False
        assert result["tool_results"] == []

    def test_post_tool_prompt_demands_final_format(self, tool_recorder):
        # 실 Gemini가 tool을 무한 반복한 실사고 — 결과 수신 후엔 final 형식을 명시 요구
        _, tools = tool_recorder
        llm = MockLLM([TOOL_CALL, FINAL])
        WhatIfAgent(llm, BASE_PARAMS, tools).ask("연봉 500만원 오르면?")
        assert '"final"' in llm.calls[1]["prompt"]

    def test_duplicate_tool_call_not_reexecuted(self, tool_recorder):
        # 동일 (tool, params) 반복 호출은 재실행하지 않고 final을 강제한다
        calls, tools = tool_recorder
        llm = MockLLM([TOOL_CALL, TOOL_CALL, FINAL])
        result = WhatIfAgent(llm, BASE_PARAMS, tools).ask("연봉 500만원 오르면?")
        assert len(calls) == 1  # 엔진은 한 번만 실행
        assert result["grounded"] is True
        assert "final" in llm.calls[2]["prompt"]

    def test_unknown_tool_raises(self, tool_recorder):
        _, tools = tool_recorder
        bad_call = json.dumps({"action": "call_tool", "tool": "no_such", "params_patch": {}})
        agent = WhatIfAgent(MockLLM([bad_call]), BASE_PARAMS, tools)
        with pytest.raises(ValueError):
            agent.ask("질문")

    def test_infinite_tool_loop_guarded(self, tool_recorder):
        _, tools = tool_recorder
        agent = WhatIfAgent(MockLLM([TOOL_CALL] * 10), BASE_PARAMS, tools, max_steps=3)
        with pytest.raises(RuntimeError):
            agent.ask("질문")
