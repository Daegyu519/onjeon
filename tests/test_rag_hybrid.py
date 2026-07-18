"""하이브리드 검색(dense+sparse RRF)·차원 마이그레이션·리랭커 테스트.

전부 오프라인·결정론: HashEmbedder + SparseHashEncoder + :memory: Qdrant.
IDF 가중은 Qdrant 서버측(Modifier.IDF)이 수행하므로 인코더는 무상태다.
"""

import pytest

from onjeon.rag.documents import collect_documents
from onjeon.rag.embedder import HashEmbedder, SparseHashEncoder
from onjeon.rag.index import ClauseIndex
from onjeon.rag.reranker import NoopReranker


class TestSparseHashEncoder:
    def test_deterministic_across_instances(self):
        a = SparseHashEncoder().encode("조세특례제한법 제95조의2 월세 세액공제")
        b = SparseHashEncoder().encode("조세특례제한법 제95조의2 월세 세액공제")
        assert a == b

    def test_term_counts_as_values(self):
        indices, values = SparseHashEncoder().encode("월세 월세 한도")
        assert len(indices) == 2  # 고유 토큰 2개
        assert sorted(values, reverse=True) == [2.0, 1.0]

    def test_empty_text_empty_vector(self):
        indices, values = SparseHashEncoder().encode("   ")
        assert indices == [] and values == []


@pytest.fixture
def hybrid_index():
    idx = ClauseIndex(location=":memory:", embedder=HashEmbedder(dim=256))
    idx.index_documents(collect_documents())
    return idx


class TestHybridSearch:
    def test_default_mode_is_hybrid_and_returns_results(self, hybrid_index):
        results = hybrid_index.search("연소득 기준이 얼마인가요?", top_k=3)
        assert results
        assert {"score", "text", "payload"} <= set(results[0])

    def test_literal_statute_number_query(self, hybrid_index):
        # 조문 리터럴 질의 — sparse 정확 매칭이 기여해야 하는 대표 케이스
        [top] = hybrid_index.search("조세특례제한법", top_k=1)
        assert top["payload"]["source_type"] == "tax_rule"

    def test_dense_mode_still_available(self, hybrid_index):
        results = hybrid_index.search("연소득", top_k=3, mode="dense")
        assert results

    def test_source_type_filter_applies_in_hybrid(self, hybrid_index):
        results = hybrid_index.search("연소득", top_k=5, source_type="product_rule")
        assert results
        assert all(r["payload"]["source_type"] == "product_rule" for r in results)

    def test_unknown_mode_raises(self, hybrid_index):
        with pytest.raises(ValueError):
            hybrid_index.search("질의", mode="colbert")

    def test_reindex_idempotent(self, hybrid_index):
        before = hybrid_index.count()
        hybrid_index.index_documents(collect_documents())
        assert hybrid_index.count() == before


class TestDimensionMigration:
    def test_reopen_with_different_dim_recreates_collection(self, tmp_path):
        path = str(tmp_path / "qdrant")
        idx = ClauseIndex(path=path, embedder=HashEmbedder(dim=256))
        idx.index_documents(collect_documents())
        assert idx.count() > 0
        idx.client.close()

        migrated = ClauseIndex(path=path, embedder=HashEmbedder(dim=64))
        assert migrated.count() == 0  # 차원 변경 → 재생성 (재적재는 호출측 책임)
        migrated.index_documents(collect_documents())
        assert migrated.search("연소득", top_k=1)
        migrated.client.close()


class TestReranker:
    def test_noop_truncates_only(self):
        results = [{"score": 0.9, "text": "a", "payload": {}}, {"score": 0.8, "text": "b", "payload": {}}]
        assert NoopReranker().rerank("q", results, top_k=1) == results[:1]

    def test_index_accepts_reranker(self):
        idx = ClauseIndex(
            location=":memory:", embedder=HashEmbedder(dim=256), reranker=NoopReranker()
        )
        idx.index_documents(collect_documents())
        assert idx.search("연소득 기준", top_k=3)
