"""KB국민은행 전세자금대출 **공시 상품** 수집 — 금융감독원 금융상품통합비교공시(Finlife).

무엇을 채우는가: `market_params.market_loan_product`의 **정식 상품명과 금리 구조**
(기준금리 유형·최저/최고/평균)다. 계산에 들어가는 금리는 여기서 오지 않는다 —
그건 HF 실행금리(`fetch_bank_rates.py`)가 담당한다. 둘은 성격이 다르다:

    공시(Finlife)  = 은행이 **내건** 상품 스펙. 상품명·금리유형·한도가 여기에만 있다.
    실행(HF API)   = 실제로 **나간** 대출의 금액가중평균. 우대가 반영된 뒤 숫자다.

비용 계산에는 실행금리를 쓴다(사용자가 실제로 낼 금리에 가깝다). 공시는 "어느
상품인지"를 대는 데 쓴다 — 상품명 없이 '시중대출'이라고만 하면 사용자가 어디를
찾아가야 하는지 알 수 없다.

    데이터: 금융감독원 금융상품 한눈에 — 전세자금대출
    https://finlife.fss.or.kr/finlife/api/fdrmDrctInsr/list  (인증키 무료 발급)

사용:
    # 1) https://finlife.fss.or.kr 에서 인증키 발급(무료)
    # 2) .env 에  FSS_API_KEY=<발급키>
    .venv/bin/python scripts/fetch_finlife_rates.py
    .venv/bin/python scripts/fetch_finlife_rates.py --all-banks   # 전 은행(대조용)
    .venv/bin/python scripts/fetch_finlife_rates.py --dry-run

결과: src/onjeon/rules/kb_loan_products_<YYYY-MM>.json
      + market_params_<버전>.json 의 market_loan_product 에 상품명·공시금리 반영

실측 함정(2026-07-29): 이 서버는 레거시 암호군을 쓴다. 기본 TLS 설정으로는 핸드셰이크가
**끝나지 않고 멈춘다**(curl HTTP 000, 10초 후에도 응답 없음). 예외도 안 난다 —
타임아웃만 난다. `SECLEVEL=1` 컨텍스트를 줘야 200이 온다. http:// 로 부르면 307로
https:// 에 돌려보내므로 우회로가 아니다.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from onjeon.config import load_env

ENDPOINT = "https://finlife.fss.or.kr/finlifeapi/rentHouseLoanProductsSearch.json"
TOP_FIN_GRP_NO = "020000"  # 은행
KB_FIN_CO_NO = "0010001"   # KB국민은행
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "src" / "onjeon" / "rules"
TIMEOUT = 30


def _ctx() -> ssl.SSLContext:
    """레거시 암호군을 허용하는 TLS 컨텍스트. 없으면 핸드셰이크가 멈춘다(상단 함정 참조)."""
    c = ssl.create_default_context()
    c.set_ciphers("DEFAULT@SECLEVEL=1")
    return c


def fetch(auth: str, *, page: int = 1) -> dict:
    """Finlife 전세자금대출 한 페이지. 오류는 result.err_cd로 온다(HTTP는 200)."""
    q = urllib.parse.urlencode({"auth": auth, "topFinGrpNo": TOP_FIN_GRP_NO, "pageNo": page})
    with urllib.request.urlopen(f"{ENDPOINT}?{q}", timeout=TIMEOUT, context=_ctx()) as resp:
        doc = json.loads(resp.read().decode("utf-8"))
    result = doc.get("result", {})
    # HTTP 200에 err_cd로 실패를 알린다 — 상태코드만 보면 빈 결과를 정상으로 읽는다.
    if result.get("err_cd") not in ("000", None):
        raise SystemExit(f"❌ Finlife 오류 {result.get('err_cd')}: {result.get('err_msg')}")
    return result


def fetch_all(auth: str) -> tuple[list[dict], list[dict]]:
    """전 페이지의 (상품, 금리옵션). 페이지를 안 돌면 뒤쪽 은행 상품이 통째로 빠진다."""
    base, opt = [], []
    page, last = 1, 1
    while page <= last:
        r = fetch(auth, page=page)
        base += r.get("baseList") or []
        opt += r.get("optionList") or []
        last = int(r.get("max_page_no") or 1)
        page += 1
    return base, opt


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def collect(base: list[dict], opt: list[dict], fin_co_no: str | None) -> list[dict]:
    """상품 + 금리옵션 결합. fin_co_no가 있으면 그 은행만."""
    rows = [b for b in base if not fin_co_no or b.get("fin_co_no") == fin_co_no]
    by_prdt: dict[str, list[dict]] = {}
    for o in opt:
        if fin_co_no and o.get("fin_co_no") != fin_co_no:
            continue
        by_prdt.setdefault(o.get("fin_prdt_cd"), []).append(o)

    out = []
    for b in rows:
        options = [
            {
                "rpay_type": o.get("rpay_type_nm"),
                "lend_rate_type": o.get("lend_rate_type_nm"),
                "lend_rate_min_pct": _num(o.get("lend_rate_min")),
                "lend_rate_max_pct": _num(o.get("lend_rate_max")),
                # 평균은 전월 취급 실적이 없으면 비어서 온다 — None을 0으로 바꾸면 공짜가 된다.
                "lend_rate_avg_pct": _num(o.get("lend_rate_avg")),
            }
            for o in by_prdt.get(b.get("fin_prdt_cd"), [])
        ]
        out.append({
            "provider": b.get("kor_co_nm"),
            "fin_co_no": b.get("fin_co_no"),
            "product_code": b.get("fin_prdt_cd"),
            "product_name": b.get("fin_prdt_nm"),
            "dcls_month": b.get("dcls_month"),
            "join_way": b.get("join_way"),
            "loan_limit": b.get("loan_lmt"),
            "incidental_expense": b.get("loan_inci_expn"),
            "early_repay": b.get("erly_rpay"),
            "options": options,
        })
    return out


def rate_span(products: list[dict]) -> tuple[float | None, float | None]:
    """상품 전체의 공시금리 최저~최고(%). 계산엔 안 쓰고 화면 대조용으로 남긴다."""
    lo = [o["lend_rate_min_pct"] for p in products for o in p["options"] if o["lend_rate_min_pct"]]
    hi = [o["lend_rate_max_pct"] for p in products for o in p["options"] if o["lend_rate_max_pct"]]
    return (min(lo) if lo else None, max(hi) if hi else None)


def patch_market_params(products: list[dict], version: str) -> Path | None:
    """market_params.market_loan_product에 상품명·공시금리를 채운다.

    **금리(rate)는 건드리지 않는다.** 그건 HF 실행금리이고, 공시금리로 갈아끼우면
    우대 전 숫자로 비용을 계산하게 된다 — 전세가 실제보다 비싸 보인다.
    """
    path = OUT_DIR / f"market_params_{version}.json"
    if not path.exists():
        print(f"⚠️  {path.name}이 없어 패치를 건너뜁니다.", file=sys.stderr)
        return None
    mp = json.loads(path.read_text(encoding="utf-8"))
    slot = mp.get("market_loan_product")
    if slot is None:
        print("⚠️  market_params에 market_loan_product가 없습니다 — 먼저 추가하세요.", file=sys.stderr)
        return None
    lo, hi = rate_span(products)
    # 공시 상품이 여럿이면 이름을 단정하지 않는다 — 목록을 남기고 사람이 고른다.
    slot["posted"] = {
        "queried_at": date.today().isoformat(),
        "dcls_month": products[0]["dcls_month"] if products else None,
        "product_names": [p["product_name"] for p in products],
        "posted_rate_min_pct": lo,
        "posted_rate_max_pct": hi,
        "source": {
            "name": "금융감독원 금융상품통합비교공시(Finlife) — 전세자금대출",
            "url": "https://finlife.fss.or.kr",
            "endpoint": ENDPOINT,
        },
    }
    if len(products) == 1:
        slot["product_name"] = products[0]["product_name"]
    path.write_text(json.dumps(mp, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Finlife KB 전세자금대출 공시 상품 수집")
    ap.add_argument("--all-banks", action="store_true", help="KB만이 아니라 전 은행(대조용)")
    ap.add_argument("--dry-run", action="store_true", help="호출만 하고 저장하지 않는다")
    args = ap.parse_args()

    load_env()
    auth = os.environ.get("FSS_API_KEY", "").strip()
    if not auth:
        print(
            "❌ FSS_API_KEY가 없습니다.\n"
            "   1) https://finlife.fss.or.kr 에서 인증키 신청(무료)\n"
            "   2) .env 에  FSS_API_KEY=<발급키>  를 추가",
            file=sys.stderr,
        )
        return 1

    print("📡 Finlife 전세자금대출 공시 조회")
    base, opt = fetch_all(auth)
    print(f"   전 은행 상품 {len(base)}건 · 금리옵션 {len(opt)}건")

    products = collect(base, opt, None if args.all_banks else KB_FIN_CO_NO)
    if not products:
        print(f"⚠️  KB(fin_co_no={KB_FIN_CO_NO}) 상품이 없습니다. --all-banks로 코드를 확인하세요.",
              file=sys.stderr)
        return 1

    for p in products:
        print(f"\n   [{p['provider']}] {p['product_name']}  (공시 {p['dcls_month']})")
        for o in p["options"]:
            avg = f"평균 {o['lend_rate_avg_pct']}%" if o["lend_rate_avg_pct"] else "평균 없음(실적 없음)"
            print(f"      {o['lend_rate_type']:<8} {o['rpay_type']:<12} "
                  f"{o['lend_rate_min_pct']}~{o['lend_rate_max_pct']}%  {avg}")

    if args.dry_run:
        print("\n(dry-run — 저장하지 않았습니다)")
        return 0

    stamp = date.today()
    doc = {
        "version": stamp.strftime("%Y-%m"),
        "queried_at": stamp.isoformat(),  # 조회 기준일 필수 (CLAUDE.md 컨벤션)
        "source": {
            "name": "금융감독원 금융상품통합비교공시(Finlife) — 전세자금대출",
            "url": "https://finlife.fss.or.kr",
            "endpoint": ENDPOINT,
            "note": "은행이 공시한 상품 스펙(상품명·금리유형·최저/최고). 실제 실행 금리는 "
                    "HF API(15082044)로 따로 받는다 — 우대 반영 여부가 다르다.",
        },
        "unit": "percent",
        "products": products,
    }
    out = OUT_DIR / f"kb_loan_products_{doc['version']}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n💾 저장: {out.relative_to(ROOT)}")

    patched = patch_market_params(products, doc["version"])
    if patched:
        print(f"💾 패치: {patched.relative_to(ROOT)} → market_loan_product.posted")
        print("   (계산 금리 rate는 그대로 둡니다 — 공시가 아니라 실행금리를 씁니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
