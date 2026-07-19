"""조항 단위 문서 수집 — 룰 DB·세제 룰·공고 원문 → RAG 인입 문서.

룰 DB가 이미 조항 단위로 구조화되어 있으므로 청크 전략이 필요 없다.
모든 문서의 payload에 출처(rule_id·clause·version·url)를 실어
검색 결과가 곧 인용이 되게 한다 (CLAUDE.md 원칙 2).
"""

from __future__ import annotations

import re
from pathlib import Path

from onjeon.rules_io import load_products, load_rules

_FIXTURES = Path(__file__).resolve().parents[3] / "data" / "fixtures"

FIELD_LABEL = {
    "age": "나이(만)",
    "annual_income_krw": "연소득",
    "assets_krw": "순자산",
    "deposit_krw": "임차보증금",
    "is_homeless": "무주택 여부",
    "is_household_head": "세대주 여부",
    "works_at_sme": "중소기업 재직 여부",
}

OP_LABEL = {"<=": "이하", ">=": "이상", "==": "일치", "in": "중 하나"}


def _fmt_value(value) -> str:
    if isinstance(value, bool):
        return "예" if value else "아니오"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def rule_documents(rule: dict) -> list[dict]:
    """정책상품 룰 1건 → 조항 문서들. L0 승인 직후 자동 색인에도 쓰인다."""
    base_payload = {
        "source_type": "product_rule",
        "rule_id": rule["rule_id"],
        "version": rule.get("version", ""),
        "url": rule.get("source", {}).get("url", ""),
        "verified_at": rule.get("verified_at", ""),
    }
    docs = []
    for criterion in rule["criteria"]:
        label = FIELD_LABEL.get(criterion["field"], criterion["field"])
        op = OP_LABEL.get(criterion["op"], criterion["op"])
        docs.append(
            {
                "text": (
                    f"{rule['product_name']} — {criterion['clause']}: "
                    f"{label} {_fmt_value(criterion['value'])} {op}"
                ),
                "payload": {
                    **base_payload,
                    "clause": criterion["clause"],
                    "field": criterion["field"],
                },
            }
        )
    if rule.get("verify_note"):
        docs.append(
            {
                "text": f"{rule['product_name']} 검증 메모: {rule['verify_note']}",
                "payload": {**base_payload, "source_type": "product_note", "clause": "verify_note"},
            }
        )
    return docs


def _tax_documents() -> list[dict]:
    tax = load_rules("tax_rules")
    credit = tax["wolse_tax_credit"]
    brackets = ", ".join(
        f"총급여 {_fmt_value(b['max_income_krw'])}원 이하 {b['rate']:.0%}"
        for b in credit["brackets"]
    )
    return [
        {
            "text": (
                f"월세 세액공제 ({credit['clause']}): {brackets}, "
                f"연 월세 한도 {_fmt_value(credit['annual_rent_cap_krw'])}원"
            ),
            "payload": {
                "source_type": "tax_rule",
                "rule_id": "tax-wolse-credit",
                "clause": credit["clause"],
                "version": tax.get("version", ""),
                "url": credit.get("source", ""),
                "verified_at": credit.get("verified_at", ""),
            },
        }
    ]


def _announcement_documents() -> list[dict]:
    path = _FIXTURES / "announcement_sample.txt"
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8")
    title = text.strip().splitlines()[0] if text.strip() else "공고"
    docs = []
    # 조항 단위(제N호) 라인만 문서화 — 제목·머리말은 노이즈
    for line in text.splitlines():
        line = line.strip()
        if re.match(r"^제\d+호", line):
            docs.append(
                {
                    "text": f"{title} {line}",
                    "payload": {
                        "source_type": "announcement",
                        "rule_id": "",
                        "clause": line.split(".")[0],
                        "version": "",
                        "url": "(공고 원문 업로드)",
                        "verified_at": "",
                    },
                }
            )
    return docs


def collect_documents() -> list[dict]:
    """룰 DB 전체 + 세제 룰 + 공고 픽스처 → 인입 문서 목록."""
    docs: list[dict] = []
    for rule in load_products():
        docs.extend(rule_documents(rule))
    docs.extend(_tax_documents())
    docs.extend(_announcement_documents())
    return docs
