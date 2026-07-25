"""실거래가 캐시 워밍 — 외부 국토부 API를 호출하는 유일한 경로.

공개 배포(ONJEON_PUBLIC_READONLY=1)에서 API는 캐시만 읽으므로, 배포 전에 이걸로
캐시를 채워둔다. 이미 받은 달은 건너뛰므로(cache.is_month_fetched) 재실행이 싸다.

쿼터 주의: 호출 수 = 지역 × 유형 × 개월 × 3종(매매·전세·월세). 전체 25구×4유형×5년은
약 1.8만 회로 일일 한도를 넘긴다 — 기본값을 좁게 두고 필요한 만큼만 넓혀라.

사용:
  .venv/bin/python scripts/warm_cache.py                      # 기본: 관악구·빌라 1년
  .venv/bin/python scripts/warm_cache.py --regions 관악구 강남구 --types rh apt --period 1y
  .venv/bin/python scripts/warm_cache.py --all --period 1y    # 25구×4유형(호출량 확인 후)
  .venv/bin/python scripts/warm_cache.py --all --period 5y --yes
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from onjeon.config import load_env
from onjeon.data_pipeline.molit import BUILDING_OPS
from onjeon.data_pipeline.regions import SEOUL_LAWD_CD
from onjeon.market.cache import open_cache
from onjeon.market.period import period_months
from onjeon.market.trends import market_trends

_KINDS = 3  # 매매·전세·월세 — 호출량 추정용


def main() -> None:
    ap = argparse.ArgumentParser(description="실거래가 캐시 워밍")
    ap.add_argument("--regions", nargs="+", default=["관악구"], help="서울 구 이름")
    ap.add_argument("--types", nargs="+", default=["rh"], choices=list(BUILDING_OPS))
    ap.add_argument("--period", default="1y", help="1m|6m|1y|3y|5y (긴 기간이 짧은 기간을 덮는다)")
    ap.add_argument("--all", action="store_true", help="서울 25구 × 전체 유형")
    ap.add_argument("--cache", default="data/cache.db")
    ap.add_argument("--yes", action="store_true", help="호출량 확인 없이 진행")
    args = ap.parse_args()

    regions = sorted(SEOUL_LAWD_CD) if args.all else args.regions
    types = list(BUILDING_OPS) if args.all else args.types
    unknown = [r for r in regions if r not in SEOUL_LAWD_CD]
    if unknown:
        raise SystemExit(f"지원하지 않는 지역: {unknown} (서울 25구만)")

    months = len(period_months(args.period))
    worst = len(regions) * len(types) * months * _KINDS
    print(f"대상 {len(regions)}지역 × {len(types)}유형 × {months}개월 × {_KINDS}종 "
          f"→ 최대 {worst:,}회 호출(이미 캐시된 달은 건너뜀)")
    if not args.yes and worst > 1000:
        raise SystemExit("일일 한도(데이터셋당 1,000회 수준)를 넘길 수 있다 — 확인 후 --yes")

    load_env()  # MOLIT_API_KEY
    conn = open_cache(Path(args.cache))
    today = date.today().isoformat()
    try:
        for region in regions:
            for btype in types:
                res = market_trends(region, btype, args.period, cache=conn,
                                    queried_at=today, allow_fetch=True)
                filled = sum(1 for v in res["mae_price"] if v is not None)
                print(f"  {region} {btype}: {len(res['dates'])}구간 "
                      f"(매매 {filled}) {'· 미승인 ' + ','.join(res['unavailable']) if res['unavailable'] else ''}")
    finally:
        conn.close()
    print("완료 — 공개 배포는 ONJEON_PUBLIC_READONLY=1 로 기동하라(캐시만 읽음)")


if __name__ == "__main__":
    main()
