"""L4 what-if 에이전트 — "연봉 500 오르면?" → 파라미터 변경 → L3 재실행 → 차이 해석.

LLM은 계산하지 않는다 (CLAUDE.md 원칙 1). LLM의 역할은
① 자연어 질문 → 엔진 파라미터 패치(JSON 액션), ② 엔진 결과의 해석뿐이다.
해석 프롬프트에 엔진 결과를 그대로 넣어, 답변 속 숫자가 tool 결과에서
왔음을 구조적으로 강제한다.
"""

from __future__ import annotations

import json
import re

from onjeon.llm import LLMClient

SYSTEM_PROMPT = """너는 주거 의사결정 서비스의 what-if 조작기다.
너는 절대 직접 계산하지 않는다. 할 수 있는 행동은 두 가지뿐이다:

1. 계산 엔진 호출 (파라미터를 바꿔 재실행):
   {"action": "call_tool", "tool": "run_comparison", "params_patch": {바꿀 파라미터}}
2. 엔진 결과를 근거로 한 최종 해석:
   {"action": "final", "answer": "..."}

답변의 모든 숫자는 반드시 엔진 결과에서 인용하라. JSON만 출력한다."""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _parse_action(text: str) -> dict:
    match = _FENCE_RE.search(text)
    payload = match.group(1) if match else text.strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 액션이 JSON이 아니다: {text[:80]!r}") from exc


class WhatIfAgent:
    def __init__(
        self,
        llm: LLMClient,
        base_params: dict,
        tools: dict[str, callable],
        *,
        max_steps: int = 5,
    ):
        self.llm = llm
        self.base_params = base_params
        self.tools = tools
        self.max_steps = max_steps

    def ask(self, question: str) -> dict:
        """자연어 what-if 질문 → 엔진 재실행 → 해석.

        complete()는 무상태이므로 모든 후속 프롬프트에 사용자 질문을 다시 싣는다.
        엔진 미호출 final은 한 번 교정 재요청하고, 그래도 미호출이면
        grounded=False로 표시해 호출측이 '엔진 근거 없음'을 알 수 있게 한다.
        """
        prompt = (
            f"기본 파라미터: {json.dumps(self.base_params, ensure_ascii=False)}\n"
            f"사용자 질문: {question}"
        )
        tool_calls: list[dict] = []
        tool_results: list[dict] = []
        corrected = False

        for _ in range(self.max_steps):
            action = _parse_action(self.llm.complete(prompt, system=SYSTEM_PROMPT))

            if action.get("action") == "final":
                if not tool_results and not corrected:
                    corrected = True
                    prompt = (
                        f"사용자 질문: {question}\n"
                        "아직 계산 엔진을 호출하지 않았다. 너는 직접 계산할 수 없다 — "
                        "먼저 run_comparison tool을 호출해 엔진 결과를 얻은 뒤에만 "
                        "final을 반환하라."
                    )
                    continue
                return {
                    "answer": action.get("answer", ""),
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "grounded": bool(tool_results),
                }

            if action.get("action") == "call_tool":
                tool_name = action.get("tool")
                if tool_name not in self.tools:
                    raise ValueError(f"등록되지 않은 tool: {tool_name!r}")
                params = {**self.base_params, **action.get("params_patch", {})}
                result = self.tools[tool_name](params)
                tool_calls.append({"tool": tool_name, "params": params})
                tool_results.append(result)
                prompt = (
                    f"엔진 결과: {json.dumps(result, ensure_ascii=False)}\n"
                    f"사용자 질문: {question}\n"
                    "이 결과만 근거로 사용자 질문에 답하라. "
                    "숫자는 엔진 결과에서 그대로 인용하라."
                )
                continue

            raise ValueError(f"알 수 없는 액션: {action!r}")

        raise RuntimeError(f"최대 반복({self.max_steps}) 초과 — tool 루프 가드")
