"""실거래가 월단위 캐시(SQLite). 원(₩) 정수·조회기준일 저장(CLAUDE.md)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fetched_months (
  region_code TEXT, building_type TEXT, deal_kind TEXT, ym TEXT,
  n INTEGER NOT NULL, queried_at TEXT NOT NULL,
  PRIMARY KEY (region_code, building_type, deal_kind, ym)
);
CREATE TABLE IF NOT EXISTS deal_cache (
  region_code TEXT, building_type TEXT, deal_kind TEXT, ym TEXT,
  deal_date TEXT NOT NULL, pyeong_krw INTEGER NOT NULL,
  dong TEXT, jibun TEXT, area_m2 REAL
);
CREATE INDEX IF NOT EXISTS idx_deal_lookup
  ON deal_cache (region_code, building_type, deal_kind, ym);
"""


def open_cache(path) -> sqlite3.Connection:
    """캐시 DB 연결(+스키마 보장). path 디렉터리는 미리 존재해야 함."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def is_month_fetched(conn, region, btype, kind, ym) -> bool:
    row = conn.execute(
        "SELECT 1 FROM fetched_months WHERE region_code=? AND building_type=? AND deal_kind=? AND ym=?",
        (region, btype, kind, ym),
    ).fetchone()
    return row is not None


def save_month(conn, region, btype, kind, ym, deals, queried_at) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO fetched_months VALUES (?,?,?,?,?,?)",
        (region, btype, kind, ym, len(deals), queried_at),
    )
    conn.execute(
        "DELETE FROM deal_cache WHERE region_code=? AND building_type=? AND deal_kind=? AND ym=?",
        (region, btype, kind, ym),
    )
    conn.executemany(
        "INSERT INTO deal_cache VALUES (?,?,?,?,?,?,?,?,?)",
        [
            (region, btype, kind, ym, d["deal_date"], d["pyeong_krw"],
             d.get("dong"), d.get("jibun"), d.get("area_m2"))
            for d in deals
        ],
    )
    conn.commit()


def load_deals(conn, region, btype, kind, months) -> list[dict]:
    if not months:
        return []
    qs = ",".join("?" * len(months))
    rows = conn.execute(
        f"SELECT deal_date, pyeong_krw, dong, jibun, area_m2 FROM deal_cache "
        f"WHERE region_code=? AND building_type=? AND deal_kind=? AND ym IN ({qs}) "
        f"ORDER BY deal_date",
        (region, btype, kind, *months),
    ).fetchall()
    return [
        {"deal_date": d, "pyeong_krw": p, "dong": dong, "jibun": jibun, "area_m2": area}
        for d, p, dong, jibun, area in rows
    ]
