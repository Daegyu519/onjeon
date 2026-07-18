"""임베더 — 주입 가능한 인터페이스로 비용·환경에 따라 교체한다.

- FastEmbedEmbedder: 운영 기본. ONNX·CPU 로컬 실행(무료, torch 불필요).
- HashEmbedder: 폴백·테스트. 모델 다운로드 0, 결정론 — 토큰 겹침 기반이라
  의미 검색 품질은 낮지만 오프라인 데모·CI가 절대 죽지 않게 한다.
"""

from __future__ import annotations

import math
import os
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


class SparseHashEncoder:
    """결정론 sparse 인코더 — 토큰 crc32 인덱스 + 등장 횟수 값.

    한국어 형태소 분석기 없이 언어 중립으로 동작한다. IDF 가중은
    Qdrant 컬렉션의 Modifier.IDF가 서버측에서 수행하므로 이 인코더는
    무상태·프로세스 경계 안전(crc32)이다.
    """

    def encode(self, text: str) -> tuple[list[int], list[float]]:
        counts: dict[int, float] = {}
        for token in _TOKEN_RE.findall(text.lower()):
            idx = zlib.crc32(token.encode("utf-8"))
            counts[idx] = counts.get(idx, 0.0) + 1.0
        return list(counts.keys()), list(counts.values())


class FastEmbedEmbedder:
    """FastEmbed(ONNX) 다국어 모델 — CPU, API 비용 0.

    모델은 ONJEON_EMBED_MODEL 환경변수로 교체 가능. 차원은 fastembed
    지원 목록 메타에서 자동 결정한다(하드코딩 금지).
    기본값은 소형 MiniLM 유지 — Streamlit Cloud 무료 티어 메모리 제약 때문.
    상위 후보는 intfloat/multilingual-e5-large(1024d, ~2.2GB): 골든셋 실측
    수치로 전환을 결정한다. bge-m3는 설치된 fastembed 버전 미지원(2026-07 확인).
    e5 계열은 query/passage 프리픽스가 필요하므로 fastembed의
    query_embed/passage_embed를 사용한다.
    """

    DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or os.environ.get("ONJEON_EMBED_MODEL", self.DEFAULT_MODEL)
        self.dim = self._resolve_dim(self.model_name)
        self._model = None

    @staticmethod
    def _resolve_dim(model_name: str) -> int:
        from fastembed import TextEmbedding

        for meta in TextEmbedding.list_supported_models():
            if meta["model"] == model_name:
                return int(meta["dim"])
        raise ValueError(f"fastembed 미지원 모델: {model_name!r}")

    def _get_model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """문서(passage) 임베딩 — e5 계열 프리픽스는 fastembed가 처리."""
        return [list(map(float, v)) for v in self._get_model().passage_embed(texts)]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """질의(query) 임베딩 — 문서와 다른 프리픽스가 필요한 모델 대응."""
        return [list(map(float, v)) for v in self._get_model().query_embed(texts)]


def default_embedder() -> Embedder:
    """fastembed 사용 가능하면 FastEmbed, 아니면 해시 폴백 (조용히 강등 금지 — 호출측이 라벨 표시)."""
    try:
        import fastembed  # noqa: F401

        return FastEmbedEmbedder()
    except ImportError:
        return HashEmbedder()
