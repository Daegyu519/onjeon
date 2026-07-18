"""낙찰가율 룰 생성기 — 수집한 통계를 버전 태그 룰 JSON으로 변환.

법원경매정보는 공개 API가 없어 통계표를 수동/반자동 수집한다
(docs/data-pipeline.md 참조). 이 모듈은 수집 결과(rows)를 검증해
L3가 소비하는 rules/auction_rates_{version}.json 형식으로 만든다.
"""

from __future__ import annotations

import json
from pathlib import Path

from onjeon.rules_io import RULES_DIR


def build_auction_rates(
    rows: list[dict], *, version: str, source: str, queried_at: str
) -> dict:
    """수집 행 [{region, building_type, rate}] → 룰 dict.

    'default' 지역은 필수 — 미커버 지역의 폴백이므로 없으면 실패시킨다.
    """
    rates: dict[str, dict[str, float]] = {}
    for row in rows:
        rates.setdefault(row["region"], {})[row["building_type"]] = float(row["rate"])
    if "default" not in rates:
        raise ValueError("'default' 지역 행이 없다 — 미커버 지역 폴백에 필수")
    return {
        "version": version,
        "source": source,
        "queried_at": queried_at,
        "rates": rates,
    }


def write_auction_rules(rules: dict, rules_dir: Path | None = None) -> Path:
    """룰 dict를 버전 태그 파일로 저장한다 (rules_io.load_rules가 최신본을 집는다)."""
    target_dir = Path(rules_dir) if rules_dir else RULES_DIR
    path = target_dir / f"auction_rates_{rules['version']}.json"
    path.write_text(
        json.dumps(rules, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path
