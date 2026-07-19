"""L1 등기부등본 파서 — LLM 비전 추출 → JSON → 스키마 게이트.

게이트(schema.gate)를 통과한 결과만 반환한다. 원문 좌표(source_loc)를
모든 항목에 요구하는 이유: 출력 인용·하이라이트 (CLAUDE.md 원칙 2).
"""

from __future__ import annotations

import json
import re

from onjeon.l1.schema import gate
from onjeon.llm import LLMClient

SYSTEM_PROMPT = "너는 한국 부동산 등기부등본을 구조화하는 문서 추출기다. 반드시 JSON만 출력한다."

EXTRACT_PROMPT = """다음 등기부등본 이미지에서 아래 JSON 스키마에 맞춰 정보를 추출하라.

등기부등본 구조:
- 표제부: 부동산 표시 (소재지, 건물 내역)
- 갑구: 소유권에 관한 사항 (소유권 이전, 압류, 가압류)
- 을구: 소유권 이외의 권리 (근저당권 — 채권최고액, 전세권, 임차권)

규칙:
1. 모든 항목에 원문 위치(source_loc: page, section, entry_no)를 기록하라.
2. 말소된 등기는 cancelled: true로 표시하되 누락하지 마라.
3. 금액은 원(₩) 정수로 변환하라 (예: "금240,000,000원" → 240000000).
4. 확인 불가능한 값은 추측하지 말고 해당 항목을 비워라.

출력 JSON 스키마:
{
  "property": {"address": str, "building_type": "빌라|오피스텔|아파트|기타",
               "market_price_krw": int, "price_source": {"api": str, "queried_at": "YYYY-MM-DD"}},
  "register": {
    "title_section": {"owner": str, "ownership_changes": []},
    "gap_section": [{"rank": int, "type": str, "date": "YYYY-MM-DD", "cancelled": bool,
                     "source_loc": {"page": int, "section": "갑구", "entry_no": int}}],
    "eul_section": [{"rank": int, "type": str, "max_claim_krw": int, "set_date": "YYYY-MM-DD",
                     "cancelled": bool, "source_loc": {"page": int, "section": "을구", "entry_no": int}}],
    "senior_lease_deposits_krw": int
  }
}

JSON만 출력하라."""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _extract_json(text: str) -> dict:
    match = _FENCE_RE.search(text)
    payload = match.group(1) if match else text.strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 응답이 JSON이 아니다: {text[:80]!r}") from exc


def parse_register(
    images: list,
    llm: LLMClient,
    *,
    market_price_krw: int | None = None,
    price_queried_at: str | None = None,
) -> dict:
    """등기부 페이지 이미지 → 구조화 JSON. 스키마 게이트 통과분만 반환.

    시세는 등기부에 없다 — 실제 LLM은 알 수 없으므로 사용자 입력/실거래가
    API 값을 market_price_krw로 주입한다(게이트 전에 채워 넣음).
    주입이 없으면 기존 게이트 규칙 그대로(시세 누락 문서 차단).
    """
    raw = llm.complete(EXTRACT_PROMPT, system=SYSTEM_PROMPT, images=images)
    doc = _extract_json(raw)
    if market_price_krw is not None:
        from datetime import date

        doc.setdefault("property", {})["market_price_krw"] = int(market_price_krw)
        doc["property"]["price_source"] = {
            "api": "사용자 입력(수동)",
            "queried_at": price_queried_at or date.today().isoformat(),
        }
    return gate(doc)
