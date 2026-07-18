"""룰 DB 로더 — 룰은 코드가 아니라 데이터 (CLAUDE.md 원칙 3).

파일명에 버전 태그(YYYY-MM)가 붙는다. 로더는 최신 버전 파일을 찾는다.
"""

from __future__ import annotations

import json
from pathlib import Path

RULES_DIR = Path(__file__).resolve().parent / "rules"


def load_rules(name: str) -> dict:
    """이름(예: 'tax_rules')으로 최신 버전 룰 JSON을 로드한다."""
    candidates = sorted(RULES_DIR.glob(f"{name}_*.json"))
    if not candidates:
        raise FileNotFoundError(f"룰 파일 없음: {name} ({RULES_DIR})")
    return json.loads(candidates[-1].read_text(encoding="utf-8"))


def load_products() -> list[dict]:
    """정책상품 룰 전체를 로드한다 (products/*.json)."""
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((RULES_DIR / "products").glob("*.json"))
    ]
