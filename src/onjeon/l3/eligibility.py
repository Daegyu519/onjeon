"""L3 정책상품 자격 판정 룰엔진 — 미자격 반증(gap·clause) 포함.

룰은 코드가 아니라 데이터(JSON, 버전 태그). docs/design.md §5 스키마 준수.
"""

from __future__ import annotations

from numbers import Number

_OPS = {
    "<=": lambda value, limit: value <= limit,
    ">=": lambda value, limit: value >= limit,
    "==": lambda value, limit: value == limit,
    "in": lambda value, limit: value in limit,
}


def check_criterion(value, op: str, limit) -> bool:
    """단일 자격 조건 판정. L0 경계값 테스트에서도 재사용된다."""
    if op not in _OPS:
        raise ValueError(f"지원하지 않는 연산자: {op!r}")
    return bool(_OPS[op](value, limit))


def _gap(value, op: str, limit):
    """수치 조건에서 '얼마나 초과/미달인지' — 미자격 반증의 근거."""
    if not (isinstance(value, Number) and isinstance(limit, Number)):
        return None
    if op == "<=":
        return value - limit
    if op == ">=":
        return limit - value
    return None


def evaluate(user: dict, rule: dict) -> dict:
    """사용자를 룰에 대조해 자격 판정. 미자격이면 조항·초과분·차선 상품을 담는다."""
    failed = []
    for criterion in rule["criteria"]:
        field = criterion["field"]
        actual = user.get(field)
        if actual is None or not check_criterion(actual, criterion["op"], criterion["value"]):
            failed.append(
                {
                    "field": field,
                    "op": criterion["op"],
                    "limit": criterion["value"],
                    "actual": actual,
                    "gap": None if actual is None else _gap(actual, criterion["op"], criterion["value"]),
                    "clause": criterion.get("clause", ""),
                }
            )
    return {
        "rule_id": rule["rule_id"],
        "product_name": rule["product_name"],
        "version": rule.get("version", ""),
        "eligible": not failed,
        "failed": failed,
        "alternatives": rule.get("alternatives", []) if failed else [],
    }
