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
