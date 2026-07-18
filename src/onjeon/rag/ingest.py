"""RAG 인입 CLI — 룰 DB·공고를 조항 단위로 색인한다.

사용: .venv/bin/python -m onjeon.rag.ingest [저장 경로]
  기본 경로 data/qdrant (ONJEON_QDRANT_PATH로 재정의).
  :memory: 대신 디스크 경로를 쓰면 앱 재시작 간 색인이 유지된다.
"""

from __future__ import annotations

import os
import sys

from onjeon.rag.documents import collect_documents
from onjeon.rag.index import ClauseIndex


def build_index(*, path: str | None = None, embedder=None) -> tuple[ClauseIndex, int]:
    index = ClauseIndex(path=path, embedder=embedder) if path else ClauseIndex(embedder=embedder)
    count = index.index_documents(collect_documents())
    return index, count


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("ONJEON_QDRANT_PATH", "data/qdrant")
    index, count = build_index(path=path)
    print(f"색인 완료: {count}개 문서 → {path} (총 {index.count()} 포인트, "
          f"임베더 {type(index.embedder).__name__})")


if __name__ == "__main__":
    main()
