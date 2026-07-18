"""RAG 인입 파이프라인 테스트 — 조항 단위 색인·검색 (네트워크·모델 다운로드 0).

Qdrant는 :memory: 임베디드 모드, 임베더는 해시 폴백(결정론)으로 검증한다.
운영 경로(FastEmbed)는 동일 인터페이스에 주입만 달라진다.
"""

import math

import pytest

from onjeon.rag.documents import collect_documents, rule_documents
from onjeon.rag.embedder import HashEmbedder
from onjeon.rag.index import ClauseIndex


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b))


class TestHashEmbedder:
    def test_deterministic_and_normalized(self):
        emb = HashEmbedder(dim=256)
        [v1], [v2] = emb.embed(["연소득 5천만원 이하"]), emb.embed(["연소득 5천만원 이하"])
        assert v1 == v2
        assert math.isclose(sum(x * x for x in v1), 1.0, rel_tol=1e-6)

    def test_token_overlap_similarity(self):
        emb = HashEmbedder(dim=256)
        [income_a] = emb.embed(["연소득 5천만원 이하"])
        [income_b] = emb.embed(["연소득 기준 확인"])
        [address] = emb.embed(["서울특별시 관악구 주소"])
        assert cosine(income_a, income_b) > cosine(income_a, address)


class TestCollectDocuments:
    def test_collects_rule_tax_and_announcement(self):
        docs = collect_documents()
        source_types = {d["payload"]["source_type"] for d in docs}
        assert {"product_rule", "tax_rule", "announcement"} <= source_types
        assert all(d["text"].strip() for d in docs)

    def test_income_clause_document_has_traceable_payload(self):
        docs = collect_documents()
        income = [
            d for d in docs
            if d["payload"].get("field") == "annual_income_krw"
            and d["payload"].get("rule_id") == "sme-youth-jeonse-2026-07"
        ]
        assert income, "중기청 연소득 조항 문서가 있어야 한다"
        payload = income[0]["payload"]
        assert payload["clause"]  # 원문 출처 인용 가능해야 함 (CLAUDE.md 원칙 2)
        assert payload["version"]


@pytest.fixture
def index():
    idx = ClauseIndex(location=":memory:", embedder=HashEmbedder(dim=256))
    idx.index_documents(collect_documents())
    return idx


class TestClauseIndex:
    def test_ingest_counts_documents(self, index):
        assert index.count() >= 10

    def test_ingest_is_idempotent(self, index):
        before = index.count()
        index.index_documents(collect_documents())
        assert index.count() == before

    def test_search_income_returns_income_clauses(self, index):
        results = index.search("연소득 기준", top_k=3, source_type="product_rule")
        assert results
        assert results[0]["payload"]["field"] == "annual_income_krw"

    def test_search_result_carries_citation(self, index):
        [top] = index.search("월세 세액공제", top_k=1)
        assert top["payload"]["source_type"] in {"tax_rule", "announcement", "product_rule"}
        assert top["text"]
        assert top["score"] > 0

    def test_index_rule_makes_new_rule_searchable(self, index):
        new_rule = {
            "rule_id": "test-newlywed-2026-08",
            "product_name": "신혼부부 전용 전세자금대출",
            "version": "2026-08 기준",
            "source": {"url": "https://example.gov"},
            "criteria": [
                {"field": "marriage_years", "op": "<=", "value": 7,
                 "clause": "대출대상 제1호 (혼인 7년 이내)"}
            ],
        }
        index.index_rule(new_rule)
        results = index.search("신혼부부 혼인 기간", top_k=2)
        assert any(r["payload"].get("rule_id") == "test-newlywed-2026-08" for r in results)


class TestRuleDocuments:
    def test_clause_text_is_human_readable(self):
        rule = {
            "rule_id": "r", "product_name": "테스트 상품", "version": "v",
            "source": {"url": "u"},
            "criteria": [{"field": "annual_income_krw", "op": "<=",
                          "value": 35_000_000, "clause": "제2호"}],
        }
        [doc] = [d for d in rule_documents(rule) if d["payload"].get("field")]
        assert "연소득" in doc["text"]          # 필드명이 아니라 사람이 읽는 라벨
        assert "35,000,000" in doc["text"]
        assert "이하" in doc["text"]
