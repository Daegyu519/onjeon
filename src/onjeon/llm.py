"""LLM 클라이언트 추상화.

LLM은 추출(L1)·조작(L4)·해석만 담당한다 — 계산은 L3 (CLAUDE.md 원칙 1).
MockLLM만으로 API 키 없이 데모 전 구간이 동작해야 한다.
"""

from __future__ import annotations

import base64
import os
from typing import Protocol


class LLMClient(Protocol):
    def complete(self, prompt: str, *, system: str | None = None, images: list | None = None) -> str: ...


class MockLLM:
    """준비된 응답을 순서대로 돌려주는 테스트/오프라인 데모용 클라이언트."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def complete(self, prompt: str, *, system: str | None = None, images: list | None = None) -> str:
        self.calls.append({"prompt": prompt, "system": system, "images": images})
        if not self._responses:
            raise RuntimeError("MockLLM 응답 소진 — 시나리오에 응답을 추가하라")
        return self._responses.pop(0)


class AnthropicLLM:
    """Anthropic Claude API 클라이언트 (ANTHROPIC_API_KEY 필요, lazy import)."""

    def __init__(self, model: str | None = None, max_tokens: int = 4096):
        self.model = model or os.environ.get("ONJEON_MODEL", "claude-sonnet-5")
        self.max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, prompt: str, *, system: str | None = None, images: list | None = None) -> str:
        content: list[dict] = []
        for image in images or []:
            if isinstance(image, dict):  # 이미 Anthropic 형식이면 그대로
                content.append(image)
            else:  # raw bytes → base64 (PNG 가정)
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.b64encode(image).decode(),
                        },
                    }
                )
        content.append({"type": "text", "text": prompt})
        message = self._get_client().messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system or "",
            messages=[{"role": "user", "content": content}],
        )
        return "".join(block.text for block in message.content if block.type == "text")


class GeminiLLM:
    """Google Gemini API 클라이언트 (GEMINI_API_KEY 또는 GOOGLE_API_KEY, lazy import)."""

    def __init__(self, model: str | None = None, max_tokens: int = 4096):
        self.model = model or os.environ.get("ONJEON_MODEL", "gemini-3.1-flash-lite")
        self.max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client()  # 환경변수 키 자동 인식
        return self._client

    def complete(self, prompt: str, *, system: str | None = None, images: list | None = None) -> str:
        from google.genai import types

        parts: list = []
        for image in images or []:
            data = image if isinstance(image, bytes) else str(image).encode()
            parts.append(types.Part.from_bytes(data=data, mime_type="image/png"))
        parts.append(prompt)
        response = self._get_client().models.generate_content(
            model=self.model,
            contents=parts,
            config=types.GenerateContentConfig(
                system_instruction=system or None,
                max_output_tokens=self.max_tokens,
            ),
        )
        return response.text or ""


def make_llm() -> LLMClient | None:
    """키 우선순위대로 새 클라이언트 생성: Gemini → Anthropic → None.

    매 호출 새 인스턴스를 돌려준다 — L0의 추출↔검증 분리 원칙에 필요.
    """
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return GeminiLLM()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return AnthropicLLM()
    return None


def default_llm() -> LLMClient | None:
    """키가 있으면 해당 공급자 클라이언트, 없으면 None (호출측이 Mock 데모로 폴백)."""
    return make_llm()
