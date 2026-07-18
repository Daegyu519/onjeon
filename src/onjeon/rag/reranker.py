"""리랭커 — 검색 후보(top-N)를 Cross-Encoder로 재정렬해 top-k를 고른다.

설치된 fastembed의 TextCrossEncoder 지원 목록에는 BAAI/bge-reranker-base까지만
있다(bge-reranker-v2-m3·ko 변형 미지원, 2026-07 확인). 한국어 성능은 골든셋
실측으로 판단하며, 기본은 NoopReranker(재정렬 없음) — 측정 근거 없이 켜지 않는다.
"""

from __future__ import annotations

from typing import Protocol


class Reranker(Protocol):
    def rerank(self, query: str, results: list[dict], top_k: int) -> list[dict]: ...


class NoopReranker:
    """재정렬 없이 상위 top_k만 자른다 — 기본값·폴백."""

    def rerank(self, query: str, results: list[dict], top_k: int) -> list[dict]:
        return results[:top_k]


class FastEmbedReranker:
    """fastembed TextCrossEncoder 기반 재정렬 (lazy load, CPU, API 비용 0)."""

    DEFAULT_MODEL = "BAAI/bge-reranker-base"

    def __init__(self, model_name: str | None = None):
        self.model_name = model_name or self.DEFAULT_MODEL
        self._model = None

    def _get_model(self):
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._model = TextCrossEncoder(model_name=self.model_name)
        return self._model

    def rerank(self, query: str, results: list[dict], top_k: int) -> list[dict]:
        if not results:
            return []
        scores = list(self._get_model().rerank(query, [r["text"] for r in results]))
        ranked = sorted(zip(results, scores), key=lambda pair: pair[1], reverse=True)
        return [
            {**result, "rerank_score": float(score)} for result, score in ranked[:top_k]
        ]
