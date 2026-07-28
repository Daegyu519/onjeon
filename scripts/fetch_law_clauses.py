"""법령 조문 수집 — 국가법령정보 공동활용 OPEN API (법제처).

왜 필요한가: 룰 JSON의 법령 근거가 2차 출처(블로그·은행 안내)에 기대고 있었다.
소액임차인 최우선변제는 **서울 값만** 들어 있어서 비서울 매물에 서울 기준을 적용했다.
시행령 제10·11조는 지역을 4구간으로 나눈다 — 그 밖의 지역은 서울의 절반도 안 된다.

여기서 받는 것은 **법조문 원문**이다. CLAUDE.md 원칙 2(모든 출력에 원문 출처)를
2차 출처가 아니라 법령 원문으로 채운다.

    API: https://open.law.go.kr/LSO/openApi/guideList.do
    OC(신청ID)는 open.law.go.kr 가입 후 발급되는 이메일 앞부분이다.
    법제처가 시범용 OC=test 를 열어두고 있어 키 없이도 동작한다 —
    운영에 쓰려면 자기 OC를 발급받아 ONJEON_LAW_OC 로 넣을 것(호출자 IP 등록 필요).

사용:
    .venv/bin/python scripts/fetch_law_clauses.py            # 수집 후 저장
    .venv/bin/python scripts/fetch_law_clauses.py --dry-run  # 출력만
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "onjeon" / "rules" / "law_clauses_{version}.json"
BASE = "https://www.law.go.kr/DRF"
TIMEOUT = 25

# 수집 대상. 룰 JSON이 [확인]으로 남겨둔 법령 근거들이다.
TARGETS = [
    {
        "key": "주택임대차보호법 시행령",
        "query": "주택임대차보호법 시행령",
        "kind": "대통령령",
        "articles": ["10", "11"],
        "why": "소액임차인 최우선변제 — 지역 4구간별 금액. engine의 priority_krw 입력",
    },
    {
        "key": "주택임대차보호법",
        "query": "주택임대차보호법",
        "kind": "법률",  # 이걸 안 걸면 검색어가 시행령에도 걸려 엉뚱한 조문이 온다(실측)
        "articles": ["8"],
        "why": "최우선변제권의 근거 조항 (시행령 제10·11조가 위임받는다)",
    },
]


def call(path: str, **params) -> dict:
    oc = os.environ.get("ONJEON_LAW_OC", "test").strip() or "test"
    url = f"{BASE}/{path}?" + urllib.parse.urlencode({"OC": oc, "type": "JSON", **params})
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.URLError as exc:
        raise SystemExit(f"❌ 법령 API 호출 실패: {exc}") from exc
    doc = json.loads(raw)
    # 인증 실패도 HTTP 200으로 온다 — 조용히 빈 결과로 흘리면 원인을 못 찾는다.
    if isinstance(doc, dict) and doc.get("result"):
        raise SystemExit(
            f"❌ 법령 API 인증 실패: {doc['result']}\n"
            f"   {doc.get('msg','')}\n"
            "   OC를 쓰려면 open.law.go.kr에 호출 서버 IP를 등록해야 합니다. "
            "등록 전이면 ONJEON_LAW_OC를 비워 시범용 OC=test로 도세요."
        )
    return doc


def _flat(v):
    """법령 API는 항목이 1개면 dict, 여러 개면 list로 준다 — 항상 list로 만든다."""
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def latest_mst(query: str, kind: str | None = None) -> dict:
    """법령명 검색 → 현행 최신본. kind로 법률/대통령령을 반드시 갈라야 한다.

    '주택임대차보호법'으로 검색하면 시행령도 함께 걸린다. 구분 없이 첫 결과를 쓰면
    법률 제8조 대신 **시행령 제8조(차임 증액청구)**를 가져온다 — 조문 번호는 같고
    내용은 전혀 다르므로 예외 없이 조용히 틀린다(실측으로 밟았다).
    """
    d = call("lawSearch.do", target="law", query=query, display=20)
    laws = _flat(d.get("LawSearch", {}).get("law"))
    if kind:
        laws = [x for x in laws if x.get("법령구분명") == kind]
    # 법령명이 정확히 일치하는 것 우선 — '주택임대차보호법'에 '…시행규칙'이 섞인다
    exact = [x for x in laws if x.get("법령명한글", "").strip() == query.strip()]
    laws = exact or laws
    cur = [x for x in laws if x.get("현행연혁코드") == "현행"] or laws
    if not cur:
        raise SystemExit(f"❌ 법령을 찾지 못했습니다: {query} (구분={kind})")
    return max(cur, key=lambda x: str(x.get("시행일자", "")))


def articles(mst: str, wanted: list[str]) -> list[dict]:
    d = call("lawService.do", target="law", MST=mst)
    out = []
    for a in _flat(d.get("법령", {}).get("조문", {}).get("조문단위")):
        if str(a.get("조문번호")) not in wanted:
            continue
        # 제8조와 제8조의2는 조문번호가 둘 다 '8'이고 가지번호로만 갈린다.
        # 안 거르면 '보증금 중 일정액의 보호'를 찾다가 '주택임대차위원회'가 딸려온다(실측).
        if str(a.get("조문가지번호") or "").strip():
            continue
        items = []
        for h in _flat(a.get("항")):
            if not isinstance(h, dict):
                continue
            for x in _flat(h.get("호")):
                if isinstance(x, dict) and x.get("호내용"):
                    items.append(_clean(x["호내용"]))
        out.append({
            "article": f"제{a.get('조문번호')}조",
            "title": a.get("조문제목"),
            "text": _clean(a.get("조문내용", "")),
            "paragraphs": [_clean(str(h.get("항내용", ""))) for h in _flat(a.get("항"))
                           if isinstance(h, dict) and h.get("항내용")],
            "items": items,
        })
    return out


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


_AMOUNT = re.compile(r"(?:(\d+)억)?\s*(?:(\d[\d,]*)천)?\s*(?:(\d[\d,]*)백)?\s*(?:([\d,]+)만)?원")


def parse_krw(text: str) -> int | None:
    """'1억6천500만원' → 165000000. 한글 단위 표기를 원 정수로.

    금액을 손으로 옮겨 적으면 자릿수를 틀린다 — 조문 문자열에서 직접 뽑는다.
    """
    m = _AMOUNT.search(text.replace(" ", ""))
    if not m or not any(m.groups()):
        return None
    eok, cheon, baek, man = (int(g.replace(",", "")) if g else 0 for g in m.groups())
    return eok * 100_000_000 + (cheon * 1000 + baek * 100 + man) * 10_000


def main() -> int:
    ap = argparse.ArgumentParser(description="법제처 법령 조문 수집")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    collected, stamp = {}, date.today()
    for t in TARGETS:
        law = latest_mst(t["query"], t.get("kind"))
        arts = articles(law["법령일련번호"], t["articles"])
        print(f"📖 {law['법령명한글']} (시행 {law['시행일자']}, 공포 {law['공포일자']})")
        for a in arts:
            print(f"   {a['article']} {a['title']} — 호 {len(a['items'])}개")
            for it in a["items"]:
                won = parse_krw(it)
                print(f"      · {it[:74]}{'' if len(it) <= 74 else '…'}"
                      + (f"   → {won:,}원" if won else ""))
        collected[t["key"]] = {
            "law_name": law["법령명한글"],
            "mst": law["법령일련번호"],
            "enforced_at": law["시행일자"],
            "promulgated_at": law["공포일자"],
            "ministry": law.get("소관부처명"),
            "link": "https://www.law.go.kr" + law.get("법령상세링크", "").replace("&type=HTML", ""),
            "why": t["why"],
            "articles": arts,
        }
        print()

    if args.dry_run:
        print("(dry-run — 저장하지 않았습니다)")
        return 0

    doc = {
        "version": stamp.strftime("%Y-%m"),
        "queried_at": stamp.isoformat(),
        "source": {
            "name": "국가법령정보 공동활용 OPEN API (법제처)",
            "url": "https://open.law.go.kr/LSO/openApi/guideList.do",
            "oc": os.environ.get("ONJEON_LAW_OC", "test"),
            "note": "법조문 **원문**이다. 2차 출처(블로그·은행 안내)가 아니라 법령 원문을 인용한다.",
        },
        "laws": collected,
    }
    path = Path(str(OUT).format(version=doc["version"]))
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"💾 저장: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
