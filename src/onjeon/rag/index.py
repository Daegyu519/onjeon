"""조항 색인 — Qdrant 임베디드 로컬 모드, 하이브리드(dense+sparse RRF) 검색.

비용·성능 결정 (2026-07 기준):
- 임베디드 로컬(:memory:/path) → 서버·클라우드 비용 0. 코드 그대로
  Qdrant Cloud URL로 승격 가능.
- named vectors(dense) + sparse(Modifier.IDF 서버측 가중) + Query API
  prefetch/RRF 융합 — 전부 Qdrant 내장, 추가 인프라 0.
- 콘텐츠 해시(uuid5) ID → 재실행해도 중복 없음(멱등 ingest).
- 컬렉션 dense 차원이 임베더와 다르면 자동 재생성(모델 교체 마이그레이션).
- 리랭커는 주입식(기본 None) — 골든셋 실측 근거 없이 켜지 않는다.
"""

from __future__ import annotations

import uuid

from qdrant_client import QdrantClient, models

from onjeon.rag.documents import rule_documents
from onjeon.rag.embedder import Embedder, SparseHashEncoder, default_embedder
from onjeon.rag.reranker import Reranker

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "onjeon-clauses")

# v2: named dense + sparse. (v1 'onjeon_clauses'는 dense 단일 — 병행 잔존해도 무해)
DEFAULT_COLLECTION = "onjeon_clauses_v2"

DENSE = "dense"
SPARSE = "sparse"


class ClauseIndex:
    def __init__(
        self,
        location: str = ":memory:",
        *,
        path: str | None = None,
        embedder: Embedder | None = None,
        sparse_encoder: SparseHashEncoder | None = None,
        reranker: Reranker | None = None,
        collection: str = DEFAULT_COLLECTION,
    ):
        self.client = QdrantClient(path=path) if path else QdrantClient(location)
        self.embedder = embedder or default_embedder()
        self.sparse_encoder = sparse_encoder or SparseHashEncoder()
        self.reranker = reranker
        self.collection = collection
        self._ensure_collection()

    # ── 컬렉션 관리 ────────────────────────────────────────────────
    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            info = self.client.get_collection(self.collection)
            dense = info.config.params.vectors.get(DENSE)
            if dense is not None and dense.size == self.embedder.dim:
                return
            # 임베딩 모델(차원) 교체 → 재생성. 재적재는 호출측(ingest) 책임.
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                DENSE: models.VectorParams(
                    size=self.embedder.dim, distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )

    # ── 인입 ───────────────────────────────────────────────────────
    def index_documents(self, docs: list[dict]) -> int:
        """문서 목록을 색인한다. 같은 텍스트는 같은 ID — 멱등."""
        if not docs:
            return 0
        dense_vectors = self.embedder.embed([d["text"] for d in docs])
        points = []
        for doc, dense_vec in zip(docs, dense_vectors):
            indices, values = self.sparse_encoder.encode(doc["text"])
            points.append(
                models.PointStruct(
                    id=str(uuid.uuid5(_NAMESPACE, doc["text"])),
                    vector={
                        DENSE: dense_vec,
                        SPARSE: models.SparseVector(indices=indices, values=values),
                    },
                    payload={**doc["payload"], "text": doc["text"]},
                )
            )
        self.client.upsert(collection_name=self.collection, points=points)
        return len(points)

    def index_rule(self, rule: dict) -> int:
        """L0 승인 룰을 즉시 색인 — '정책이 바뀌면 검색도 바뀐다' 훅."""
        return self.index_documents(rule_documents(rule))

    def count(self) -> int:
        return self.client.count(self.collection, exact=True).count

    # ── 검색 ───────────────────────────────────────────────────────
    def _embed_query(self, query: str) -> list[float]:
        embed_queries = getattr(self.embedder, "embed_queries", None)
        if callable(embed_queries):
            return embed_queries([query])[0]
        return self.embedder.embed([query])[0]

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        source_type: str | None = None,
        mode: str = "hybrid",
    ) -> list[dict]:
        """조항 검색 — 결과는 항상 출처 payload를 동반한다.

        mode="hybrid"(기본): dense+sparse RRF 융합. "dense": 단일 벡터 검색.
        리랭커가 주입된 경우 후보(top_k×4)를 재정렬해 top_k를 낸다.
        """
        if mode not in ("hybrid", "dense"):
            raise ValueError(f"지원하지 않는 검색 모드: {mode!r} — 'hybrid' 또는 'dense'")

        query_filter = None
        if source_type:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_type", match=models.MatchValue(value=source_type)
                    )
                ]
            )

        fetch_n = top_k * 4 if self.reranker else top_k
        dense_vec = self._embed_query(query)
        indices, values = self.sparse_encoder.encode(query)

        if mode == "hybrid" and indices:
            prefetch_limit = max(fetch_n * 4, 20)
            points = self.client.query_points(
                collection_name=self.collection,
                prefetch=[
                    models.Prefetch(
                        query=dense_vec, using=DENSE, limit=prefetch_limit, filter=query_filter
                    ),
                    models.Prefetch(
                        query=models.SparseVector(indices=indices, values=values),
                        using=SPARSE,
                        limit=prefetch_limit,
                        filter=query_filter,
                    ),
                ],
                query=models.FusionQuery(fusion=models.Fusion.RRF),
                limit=fetch_n,
            ).points
        else:
            points = self.client.query_points(
                collection_name=self.collection,
                query=dense_vec,
                using=DENSE,
                limit=fetch_n,
                query_filter=query_filter,
            ).points

        results = [
            {"score": float(p.score), "text": p.payload.get("text", ""), "payload": p.payload}
            for p in points
        ]
        if self.reranker:
            return self.reranker.rerank(query, results, top_k)
        return results[:top_k]
