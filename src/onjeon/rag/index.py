"""조항 색인 — Qdrant 임베디드 로컬 모드 + 주입식 임베더.

비용·성능 결정 (2026-07 기준):
- 임베디드 로컬(:memory:/path) → 서버·클라우드 비용 0. 코드 그대로
  Qdrant Cloud URL로 승격 가능.
- 콘텐츠 해시(uuid5) ID → 재실행해도 중복 없음(멱등 ingest).
- 수백 벡터 규모 → HNSW 튜닝·양자화 불필요 (측정 없는 최적화 금지).
"""

from __future__ import annotations

import uuid

from qdrant_client import QdrantClient, models

from onjeon.rag.documents import rule_documents
from onjeon.rag.embedder import Embedder, default_embedder

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "onjeon-clauses")


class ClauseIndex:
    def __init__(
        self,
        location: str = ":memory:",
        *,
        path: str | None = None,
        embedder: Embedder | None = None,
        collection: str = "onjeon_clauses",
    ):
        self.client = QdrantClient(path=path) if path else QdrantClient(location)
        self.embedder = embedder or default_embedder()
        self.collection = collection
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if not self.client.collection_exists(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=self.embedder.dim, distance=models.Distance.COSINE
                ),
            )

    def index_documents(self, docs: list[dict]) -> int:
        """문서 목록을 색인한다. 같은 텍스트는 같은 ID — 멱등."""
        if not docs:
            return 0
        vectors = self.embedder.embed([d["text"] for d in docs])
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(_NAMESPACE, doc["text"])),
                vector=vector,
                payload={**doc["payload"], "text": doc["text"]},
            )
            for doc, vector in zip(docs, vectors)
        ]
        self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    def index_rule(self, rule: dict) -> int:
        """L0 승인 룰을 즉시 색인 — '정책이 바뀌면 검색도 바뀐다' 훅."""
        return self.index_documents(rule_documents(rule))

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    def search(self, query: str, *, top_k: int = 5, source_type: str | None = None) -> list[dict]:
        """조항 검색 — 결과는 항상 출처 payload를 동반한다."""
        [vector] = self.embedder.embed([query])
        query_filter = None
        if source_type:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type", match=models.MatchValue(value=source_type)
                    )
                ]
            )
        points = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=top_k,
            query_filter=query_filter,
        ).points
        return [
            {"score": float(p.score), "text": p.payload.get("text", ""), "payload": p.payload}
            for p in points
        ]
