"""임베더 — 주입 가능한 인터페이스로 비용·환경에 따라 교체한다.

- FastEmbedEmbedder: 운영 기본. ONNX·CPU 로컬 실행(무료, torch 불필요).
- HashEmbedder: 폴백·테스트. 모델 다운로드 0, 결정론 — 토큰 겹침 기반이라
  의미 검색 품질은 낮지만 오프라인 데모·CI가 절대 죽지 않게 한다.
"""

from __future__ import annotations

import math
import re
import zlib
from typing import Protocol

_TOKEN_RE = re.compile(r"[\w가-힣]+")


class Embedder(Protocol):
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """토큰 해시 bag-of-words 임베딩 (L2 정규화). 폴백·테스트 전용.

    버킷은 crc32 기반 — 내장 hash()는 PYTHONHASHSEED로 프로세스마다 달라져
    '결정론' 계약과 디스크 영속 색인(프로세스 재시작 후 질의)을 깨뜨린다.
    """

    def __init__(self, dim: int = 256):
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            for token in _TOKEN_RE.findall(text.lower()):
                vec[zlib.crc32(token.encode("utf-8")) % self.dim] += 1.0
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vectors.append([x / norm for x in vec])
        return vectors


class FastEmbedEmbedder:
    """FastEmbed(ONNX) 다국어 소형 모델 — 한국어 지원, CPU, API 비용 0."""

    DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self.dim = 384
        self._model = None

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._get_model().embed(texts)]


def default_embedder() -> Embedder:
    """fastembed 사용 가능하면 FastEmbed, 아니면 해시 폴백 (조용히 강등 금지 — 호출측이 라벨 표시)."""
    try:
        import fastembed  # noqa: F401

        return FastEmbedEmbedder()
    except ImportError:
        return HashEmbedder()
