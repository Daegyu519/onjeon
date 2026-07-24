"""주거 의사결정 오케스트레이터 decide() — 통합 회귀 테스트(실제 룰 사용)."""
import pytest

from onjeon.decision import decide

PROFILE = {
    "monthly_income_krw": 2_800_000, "assets_krw": 20_000_000, "age": 27,
    "region": "관악구", "is_homeless": True, "is_household_head": True, "works_at_sme": True,
}
LISTING = {"kind": "wolse", "deposit_krw": 20_000_000, "monthly_rent_krw": 550_000, "maintenance_krw": 70_000}


def test_returns_three_sections():
    out = decide(PROFILE, LISTING)
    assert set(out) == {"affordability", "recommendations", "sources"}
    assert out["affordability"]["verdict"] in ("적정", "초과")
    assert "eligible" in out["recommendations"] and "ineligible" in out["recommendations"]


def test_income_converted_to_annual_for_eligibility():
    # 월 2.8M → 연 33.6M ≤ 중기청 상한 35M → 중기청 자격
    out = decide(PROFILE, LISTING)
    names = [e["product_name"] for e in out["recommendations"]["eligible"]]
    assert "중소기업취업청년 전월세보증금대출" in names


def test_high_income_disqualifies_sme():
    # 월 3.0M → 연 36M > 35M → 중기청 미자격
    out = decide({**PROFILE, "monthly_income_krw": 3_000_000, "works_at_sme": False}, LISTING)
    inelig = [e["product_name"] for e in out["recommendations"]["ineligible"]]
    assert "중소기업취업청년 전월세보증금대출" in inelig


def test_missing_income_raises():
    with pytest.raises(ValueError):
        decide({"assets_krw": 1_000_000}, LISTING)
