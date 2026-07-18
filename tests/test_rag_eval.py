"""RAG 골든셋 평가 하네스 테스트 — recall@k·MRR 계산과 골든셋 무결성.

1) 합성 코퍼스 + HashEmbedder(결정론)로 지표 기대값을 고정 검증한다.
2) data/golden_queries.json의 모든 expect_payload가 실제 코퍼스와
   매칭되는지 강제한다 — 죽은 골든셋(코퍼스에 없는 기대값) 금지.
"""

import json
from pathlib import Path

import pytest

from onjeon.rag.documents import collect_documents
from onjeon.rag.embedder import HashEmbedder
from onjeon.rag.eval import evaluate, load_golden, payload_matches
from onjeon.rag.index import ClauseIndex

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "data" / "golden_queries.json"

# 합성 코퍼스 — income_a 질의 원문 재사용 시 rank 1(코사인 1.0),
# income_b는 토큰 7개 중 6개 공유로 rank 2가 보장된다(결정론 임베더).
SYNTH_DOCS = [
    {
        "text": "청년 전세 대출 연소득 기준 오천만원 이하",
        "payload": {"source_type": "synth", "field": "income_a"},
    },
    {
        "text": "청년 전세 대출 연소득 기준 삼천오백만원 이하",
        "payload": {"source_type": "synth", "field": "income_b"},
    },
    {
        "text": "서울특별시 관악구 봉천동 오피스텔 주소 안내",
        "payload": {"source_type": "synth", "field": "address"},
    },
]

Q_RANK1 = {"query": "청년 전세 대출 연소득 기준 오천만원 이하", "expect_payload": {"field": "income_a"}}
Q_RANK2 = {"query": "청년 전세 대출 연소득 기준 오천만원 이하", "expect_payload": {"field": "income_b"}}
Q_MISS = {"query": "완전히 무관한 질의", "expect_payload": {"field": "존재하지않는필드"}}


@pytest.fixture
def synth_index():
    idx = ClauseIndex(location=":memory:", embedder=HashEmbedder(dim=256))
    idx.index_documents(SYNTH_DOCS)
    return idx


class TestPayloadMatches:
    def test_subset_matches_ignoring_extra_keys(self):
        payload = {"field": "age", "rule_id": "r1", "text": "본문", "score_extra": 1}
        assert payload_matches(payload, {"field": "age"})
        assert payload_matches(payload, {"field": "age", "rule_id": "r1"})

    def test_value_mismatch_or_missing_key_fails(self):
        payload = {"field": "age"}
        assert not payload_matches(payload, {"field": "annual_income_krw"})
        assert not payload_matches(payload, {"rule_id": "r1"})


class TestEvaluate:
    def test_exact_query_hits_rank1(self, synth_index):
        report = evaluate(synth_index, [Q_RANK1], top_k=3)
        assert report["recall_at_k"] == 1.0
        assert report["mrr"] == 1.0
        assert report["n"] == 1
        assert report["per_query"] == [{"query": Q_RANK1["query"], "hit": True, "rank": 1}]

    def test_rank2_hit_gives_half_reciprocal(self, synth_index):
        report = evaluate(synth_index, [Q_RANK2], top_k=3)
        assert report["recall_at_k"] == 1.0
        assert report["mrr"] == 0.5
        assert report["per_query"][0]["rank"] == 2

    def test_miss_scores_zero(self, synth_index):
        report = evaluate(synth_index, [Q_MISS], top_k=3)
        assert report["recall_at_k"] == 0.0
        assert report["mrr"] == 0.0
        assert report["per_query"] == [{"query": Q_MISS["query"], "hit": False, "rank": None}]

    def test_mixed_aggregate(self, synth_index):
        # rank1(1.0) + rank2(0.5) + miss(0) → recall 2/3, MRR 0.5
        report = evaluate(synth_index, [Q_RANK1, Q_RANK2, Q_MISS], top_k=3)
        assert report["n"] == 3
        assert report["recall_at_k"] == pytest.approx(2 / 3)
        assert report["mrr"] == pytest.approx(0.5)

    def test_top_k_limits_search_window(self, synth_index):
        # top_k=1이면 rank2 문서는 검색창 밖 → 미스
        report = evaluate(synth_index, [Q_RANK2], top_k=1)
        assert report["recall_at_k"] == 0.0
        assert report["per_query"][0]["hit"] is False

    def test_empty_golden_raises(self, synth_index):
        with pytest.raises(ValueError):
            evaluate(synth_index, [], top_k=3)


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus():
    return collect_documents()


class TestGoldenSet:
    def test_load_golden_reads_default_path(self, golden):
        assert load_golden() == golden

    def test_at_least_30_queries_with_nonempty_expects(self, golden):
        assert len(golden) >= 30
        for item in golden:
            assert item["query"].strip()
            assert isinstance(item["expect_payload"], dict)
            assert item["expect_payload"], "빈 expect_payload는 모든 문서와 매칭 — 금지"

    def test_every_expect_matches_at_least_one_corpus_doc(self, golden, corpus):
        for item in golden:
            assert any(
                payload_matches(doc["payload"], item["expect_payload"]) for doc in corpus
            ), f"코퍼스에 없는 기대값: {item['query']} → {item['expect_payload']}"

    def test_golden_covers_corpus_surface(self, golden, corpus):
        # 골든셋이 매칭하는 문서들의 합집합이 코퍼스 전 영역을 덮어야 한다
        matched = [
            doc
            for item in golden
            for doc in corpus
            if payload_matches(doc["payload"], item["expect_payload"])
        ]
        source_types = {d["payload"]["source_type"] for d in matched}
        assert {"product_rule", "tax_rule", "announcement", "product_note"} <= source_types
        fields = {d["payload"].get("field") for d in matched}
        assert {"age", "annual_income_krw", "assets_krw", "deposit_krw"} <= fields
        rule_ids = {d["payload"].get("rule_id") for d in matched}
        assert {"sme-youth-jeonse-2026-07", "youth-jeonse-loan-2026-07"} <= rule_ids

    def test_evaluate_runs_on_real_corpus(self, golden, corpus):
        index = ClauseIndex(location=":memory:", embedder=HashEmbedder(dim=256))
        index.index_documents(corpus)
        report = evaluate(index, golden, top_k=5)
        assert report["n"] == len(golden)
        assert len(report["per_query"]) == report["n"]
        # MRR ≤ recall@k ≤ 1 (항상 성립하는 불변식 — 임베더 품질과 무관)
        assert 0.0 <= report["mrr"] <= report["recall_at_k"] <= 1.0
