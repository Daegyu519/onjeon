"""법정동 중심좌표 배치 지오코딩 — 지도(/api/market-map)의 좌표 공급원.

캐시에 있는 (구, 법정동) 쌍만 1회 지오코딩해서 dong_geo에 저장한다. 런타임 API는
이 테이블을 읽기만 하므로 공개 배포의 "외부 호출 0회" 자세가 유지된다
(ONJEON_PUBLIC_READONLY와 같은 이유 — api/main.py 상단 주석 참조).

Nominatim(OSM)을 쓰는 이유: 키·가입·카드가 전부 불필요하다. 대신 이용약관상
초당 1회 제한이 있어 417개 동에 약 8분 걸린다. 한 번만 돌리면 되는 작업이라
그 정도는 감수한다. 이미 저장된 동은 건너뛰므로 중간에 끊겨도 재실행이 싸다.

동 이름은 구 사이에서 중복된다(신사동=강남구·관악구, 사당동=동작구·관악구).
그래서 질의에 구를 붙이고, 응답 display_name에 그 구가 들어있는지 검증한 뒤에만
저장한다 — 검증 없이 저장하면 다른 구의 좌표가 섞인다.

사용:
  .venv/bin/python scripts/geocode_dongs.py            # 미저장 동만
  .venv/bin/python scripts/geocode_dongs.py --limit 20 # 맛보기
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from onjeon.data_pipeline.regions import SEOUL_LAWD_CD
from onjeon.market.cache import load_dong_geo, open_cache, save_dong_geo

_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim 이용약관: 식별 가능한 User-Agent 필수, 초당 1회 이하.
_UA = {"User-Agent": "onjeon-market-map/0.1 (KB AI Challenge; odg5845@gmail.com)"}
_DELAY = 1.1
_CODE_TO_GU = {code: gu for gu, code in SEOUL_LAWD_CD.items()}


def geocode(gu: str, dong: str, *, opener=urllib.request.urlopen) -> tuple[float, float] | None:
    """'서울특별시 {구} {동}' → (lat, lng). 응답의 구가 다르면 None(오매칭 방어)."""
    url = f"{_URL}?" + urllib.parse.urlencode(
        {"q": f"대한민국 서울특별시 {gu} {dong}", "format": "json", "limit": 1})
    with opener(urllib.request.Request(url, headers=_UA), timeout=15) as resp:
        hits = json.load(resp)
    if not hits or gu not in hits[0].get("display_name", ""):
        return None
    return float(hits[0]["lat"]), float(hits[0]["lon"])


def main() -> None:
    ap = argparse.ArgumentParser(description="법정동 중심좌표 배치 지오코딩")
    ap.add_argument("--cache", default="data/cache.db")
    ap.add_argument("--limit", type=int, help="이번 실행에서 처리할 최대 개수")
    args = ap.parse_args()

    conn = open_cache(Path(args.cache))
    have = load_dong_geo(conn)
    todo = [(r, d) for r, d in
            conn.execute("SELECT DISTINCT region_code, dong FROM deal_cache ORDER BY 1, 2")
            if (r, d) not in have]
    if args.limit:
        todo = todo[:args.limit]

    print(f"저장됨 {len(have)}개 / 이번 대상 {len(todo)}개 (약 {len(todo) * _DELAY / 60:.1f}분)")
    today = date.today().isoformat()
    ok = failed = 0
    for i, (code, dong) in enumerate(todo, 1):
        gu = _CODE_TO_GU.get(code)
        if gu is None:  # 서울 25구 밖 — regions.py가 커버하지 않는 코드
            failed += 1
            continue
        try:
            hit = geocode(gu, dong)
        except Exception as exc:  # 네트워크·과금·형식 오류 전부 — 한 건 실패로 배치를 죽이지 않는다
            print(f"  [{i}/{len(todo)}] {gu} {dong} 오류: {exc!r}", file=sys.stderr)
            hit = None
        if hit is None:
            failed += 1
            print(f"  [{i}/{len(todo)}] {gu} {dong} 미해상", file=sys.stderr)
        else:
            save_dong_geo(conn, code, dong, hit[0], hit[1], today)
            ok += 1
        if i % 25 == 0:
            print(f"  [{i}/{len(todo)}] 성공 {ok} 실패 {failed}")
        time.sleep(_DELAY)

    print(f"완료 — 성공 {ok}, 실패 {failed}. 실패분은 지도에서 빠지고 missing_geo로 집계된다.")
    conn.close()


if __name__ == "__main__":
    main()
