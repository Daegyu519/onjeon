"""RAG 골든셋 평가 하네스 — 검색 품질을 recall@k·MRR로 수치화한다.

골든셋(data/golden_queries.json)의 expect_payload가 top_k 결과의
payload에 부분일치(모든 k:v 포함)하면 정답. 임베더 교체(FastEmbed↔Hash)나
코퍼스 개편 시 품질 회귀를 이 하네스로 측정한다.

사용: .venv/bin/python -m onjeon.rag.eval
"""

from __future__ import annotations

import json
from pathlib import Path

from onjeon.rag.index import ClauseIndex

GOLDEN_PATH = Path(__file__).resolve().parents[3] / "data" / "golden_queries.json"


def payload_matches(payload: dict, expect: dict) -> bool:
    """expect의 모든 k:v가 payload에 그대로 있으면 부분일치 (payload의 여분 키는 무시)."""
    return all(payload.get(k) == v for k, v in expect.items())


def load_golden(path: Path | str = GOLDEN_PATH) -> list[dict]:
    """골든셋 로드 — [{"query": str, "expect_payload": dict}, ...]."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate(index: ClauseIndex, golden: list[dict], top_k: int = 5) -> dict:
    """골든셋 전체를 검색해 recall@k·MRR을 계산한다 (순수 평가 — 부작용 없음).

    - hit: top_k 결과 중 expect_payload 부분일치가 존재
    - MRR: 첫 매칭 랭크의 역수 평균 (미스는 0)
    """
    if not golden:
        raise ValueError("골든셋이 비어 있다 — 평가 불가")
    per_query = []
    hits = 0
    reciprocal_sum = 0.0
    for item in golden:
        results = index.search(item["query"], top_k=top_k)
        rank = next(
            (
                position
                for position, result in enumerate(results, start=1)
                if payload_matches(result["payload"], item["expect_payload"])
            ),
            None,
        )
        if rank is not None:
            hits += 1
            reciprocal_sum += 1.0 / rank
        per_query.append({"query": item["query"], "hit": rank is not None, "rank": rank})
    n = len(golden)
    return {
        "recall_at_k": hits / n,
        "mrr": reciprocal_sum / n,
        "n": n,
        "per_query": per_query,
    }


def main() -> None:
    from onjeon.rag.documents import collect_documents
    from onjeon.rag.embedder import HashEmbedder

    index = ClauseIndex(location=":memory:", embedder=HashEmbedder())
    count = index.index_documents(collect_documents())
    report = evaluate(index, load_golden(), top_k=5)
    print(f"코퍼스 {count}개 문서 · 골든셋 {report['n']}건 · HashEmbedder(폴백) 기준")
    print(f"recall@5 = {report['recall_at_k']:.2f}   MRR = {report['mrr']:.3f}")
    for row in report["per_query"]:
        mark = "hit " if row["hit"] else "MISS"
        rank = row["rank"] if row["rank"] is not None else "-"
        print(f"  [{mark}] rank={rank:<2} {row['query']}")


if __name__ == "__main__":
    main()
