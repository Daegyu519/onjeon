"""은행별 전세자금대출 실측 금리 수집 — 한국주택금융공사(HF) 공개 API.

왜 은행 사이트를 긁지 않는가: `obank.kbstar.com/robots.txt`가 `User-agent: * / Disallow: /`이고
은행연합회 소비자포털도 마찬가지다. 크롤링 금지 사이트를 긁은 데이터로 KB 출품작을
돌리면 그 사실 하나가 탈락 사유다. HF API는 공공데이터포털 정식 개방분이라 그 문제가 없고,
HTML 구조 변경에도 안 깨진다.

무엇이 좋아지는가: `market_params.loan_rate_jeonse`가 "데모 대표값 3.5% [확인]"이었다.
이 API는 HF 전세자금보증 담보 대출의 **실제 실행 금리**(은행별 가중평균)를 준다 —
가정값이 실측으로 바뀐다.

    데이터: 한국주택금융공사_전세자금대출 고객 특성별 금리 정보
    https://www.data.go.kr/data/15082044/openapi.do   (무료·자동승인)

사용:
    # 1) 위 링크에서 '활용신청' (자동승인, 즉시 발급)
    # 2) .env 에  HF_API_KEY=<발급받은 디코딩 키>
    .venv/bin/python scripts/fetch_bank_rates.py            # 최근 1개월
    .venv/bin/python scripts/fetch_bank_rates.py --loan-ym 202606
    .venv/bin/python scripts/fetch_bank_rates.py --dry-run  # 호출만 하고 저장 안 함

결과: src/onjeon/rules/bank_rates_<YYYY-MM>.json (조회 기준일 포함 — CLAUDE.md 컨벤션)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from onjeon.config import load_env

ENDPOINT = "http://apis.data.go.kr/B551408/rent-loan-rate-multi-dimensional-info/dimensional-list"
ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "src" / "onjeon" / "rules"
# loanYm은 YYYYMM 또는 L1M(최근1개월)·L3M·L1Y를 받는다. 기본은 최근 1개월.
DEFAULT_LOAN_YM = "L1M"
TIMEOUT = 20


def fetch(service_key: str, loan_ym: str, *, rows: int = 100) -> list[dict]:
    """HF API 호출 → 은행별 금리 레코드 목록.

    serviceKey는 이미 URL 인코딩된 값이 배포되기도 해서, quote를 한 번 더 걸면
    이중 인코딩으로 401이 난다. 디코딩 키를 받아 여기서 한 번만 인코딩한다.
    """
    params = {
        "serviceKey": service_key,
        "pageNo": 1,
        "numOfRows": rows,
        "loanYm": loan_ym,
        "dataType": "JSON",
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise SystemExit(
            f"❌ HTTP {exc.code} — 활용신청이 안 됐거나 키가 틀렸습니다.\n"
            f"   {ENDPOINT}\n   응답: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"❌ 네트워크 오류: {exc.reason}") from exc

    # 공공데이터포털은 오류를 200 + XML로 돌려주기도 한다(JSON 요청이어도).
    if raw.lstrip().startswith("<"):
        raise SystemExit(
            "❌ XML 오류 응답이 왔습니다 — 대개 활용신청 미승인 또는 키 오류입니다.\n"
            f"   응답 앞부분: {raw[:300]}"
        )
    doc = json.loads(raw)
    # 공공데이터포털은 기관마다 래핑이 다르다. HF는 {"header":..,"body":..}로 오고
    # 국토부(MOLIT)는 {"response":{"header":..,"body":..}}로 온다. 둘 다 받는다 —
    # 한쪽만 가정하면 200 OK인데 items가 빈 채로 조용히 넘어간다(실제로 그랬다).
    root = doc.get("response", doc)
    header = root.get("header", {})
    code = str(header.get("resultCode", "")).lstrip("0") or "0"
    if code != "0":
        raise SystemExit(f"❌ API 오류 {header.get('resultCode')}: {header.get('resultMsg')}")
    items = root.get("body", {}).get("items", [])
    if isinstance(items, dict):  # 단건이면 dict로 온다
        items = items.get("item", [])
    if isinstance(items, dict):
        items = [items]
    return [i for i in items if isinstance(i, dict)]


def summarize(items: list[dict]) -> dict:
    """은행별 가중평균금리 정리 + 전체 대표값 산출.

    대표값은 **대출실행금액 가중평균**이다. 은행 단순평균을 쓰면 취급액이 미미한
    은행이 큰 은행과 같은 무게를 갖는다.
    """
    banks: dict[str, dict] = {}
    for it in items:
        name = (it.get("bankNm") or "").strip()
        if not name:
            continue
        rate = _num(it.get("avgLoanRat2")) or _num(it.get("avgLoanRat"))
        amt = _num(it.get("loanAmt")) or 0.0
        cnt = _num(it.get("cnt")) or 0.0
        if rate is None:
            continue
        b = banks.setdefault(name, {"rate_sum": 0.0, "amt": 0.0, "cnt": 0.0,
                                    "min": None, "max": None})
        b["rate_sum"] += rate * (amt or 1.0)
        b["amt"] += amt or 1.0
        b["cnt"] += cnt
        for key, field in (("min", "minLoanRat"), ("max", "maxLoanRat")):
            v = _num(it.get(field))
            if v is None:
                continue
            cur = b[key]
            b[key] = v if cur is None else (min(cur, v) if key == "min" else max(cur, v))

    out = {}
    for name, b in banks.items():
        out[name] = {
            "weighted_avg_pct": round(b["rate_sum"] / b["amt"], 3) if b["amt"] else None,
            "min_pct": b["min"], "max_pct": b["max"],
            "loan_count": int(b["cnt"]), "loan_amount": round(b["amt"]),
        }
    total_amt = sum(v["loan_amount"] for v in out.values() if v["weighted_avg_pct"] is not None)
    overall = (
        round(sum(v["weighted_avg_pct"] * v["loan_amount"] for v in out.values()
                  if v["weighted_avg_pct"] is not None) / total_amt, 3)
        if total_amt else None
    )
    return {"banks": dict(sorted(out.items())), "overall_weighted_avg_pct": overall}


def _num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="HF 전세자금대출 은행별 금리 수집")
    ap.add_argument("--loan-ym", default=DEFAULT_LOAN_YM,
                    help="YYYYMM 또는 L1M/L3M/L1Y (기본 L1M=최근 1개월)")
    ap.add_argument("--rows", type=int, default=100)
    ap.add_argument("--dry-run", action="store_true", help="호출만 하고 파일로 저장하지 않는다")
    args = ap.parse_args()

    load_env()
    key = os.environ.get("HF_API_KEY", "").strip()
    if not key:
        print(
            "❌ HF_API_KEY가 없습니다.\n"
            "   1) https://www.data.go.kr/data/15082044/openapi.do 에서 '활용신청'\n"
            "      (무료·자동승인이라 즉시 발급됩니다)\n"
            "   2) .env 에  HF_API_KEY=<디코딩 키>  를 추가\n"
            "   ※ '인코딩 키'가 아니라 '디코딩 키'를 넣으세요 — 이중 인코딩되면 401이 납니다.",
            file=sys.stderr,
        )
        return 1

    print(f"📡 HF 전세자금대출 금리 조회 — loanYm={args.loan_ym}")
    items = fetch(key, args.loan_ym, rows=args.rows)
    if not items:
        print("⚠️  응답에 레코드가 없습니다. loanYm을 바꿔보세요(예: --loan-ym L3M).", file=sys.stderr)
        return 1

    summary = summarize(items)
    banks = summary["banks"]
    print(f"✅ {len(banks)}개 은행 · 레코드 {len(items)}건")
    for name, v in list(banks.items())[:12]:
        print(f"   {name:14} 가중평균 {v['weighted_avg_pct']}%  "
              f"({v['min_pct']}~{v['max_pct']}%, {v['loan_count']:,}건)")
    print(f"   {'전체':14} 가중평균 {summary['overall_weighted_avg_pct']}%")

    kb = next((v for k, v in banks.items() if "국민" in k or "KB" in k.upper()), None)
    if kb:
        print(f"   → KB국민은행 가중평균 {kb['weighted_avg_pct']}%")

    if args.dry_run:
        print("\n(dry-run — 저장하지 않았습니다)")
        return 0

    stamp = date.today()
    doc = {
        "version": stamp.strftime("%Y-%m"),
        "queried_at": stamp.isoformat(),   # 조회 기준일 필수 (CLAUDE.md 컨벤션)
        "loan_ym": args.loan_ym,
        "source": {
            "name": "한국주택금융공사_전세자금대출 고객 특성별 금리 정보",
            "url": "https://www.data.go.kr/data/15082044/openapi.do",
            "endpoint": ENDPOINT,
            "note": "HF 전세자금보증 담보 시중은행 대출의 실제 실행 금리. "
                    "은행 자체 홈페이지는 robots.txt가 크롤링을 금지하므로 공개 API만 쓴다.",
        },
        "unit": "percent",
        **summary,
    }
    out = OUT_DIR / f"bank_rates_{doc['version']}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n💾 저장: {out.relative_to(ROOT)}")
    print("   다음: market_params의 loan_rate_jeonse를 이 실측치로 교체할지 검토하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
