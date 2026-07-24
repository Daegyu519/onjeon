"""적정 주거비(RIR) 진단 — L3 순수함수 회귀 테스트."""
import pytest

from onjeon.l3.affordability import appropriate_rent, diagnose, monthly_housing_cost


def test_monthly_cost_includes_maintenance_and_deposit_opp():
    # 월세 50만 + 관리비 7만 + 보증금 1억×0.03/12=25만 = 82만
    assert monthly_housing_cost(
        monthly_rent=500_000, maintenance=70_000, deposit=100_000_000, opportunity_rate=0.03
    ) == 820_000


def test_appropriate_rent_is_income_times_cap():
    assert appropriate_rent(monthly_income=3_000_000, rir_cap=0.30) == 900_000


def test_diagnose_within_budget():
    d = diagnose(monthly_income=3_000_000, monthly_rent=500_000, maintenance=70_000,
                 deposit=100_000_000, opportunity_rate=0.03, rir_cap=0.30)
    assert d["monthly_cost"] == 820_000
    assert d["appropriate"] == 900_000
    assert d["over_under_krw"] == -80_000  # 여유
    assert d["verdict"] == "적정"


def test_diagnose_over_budget():
    d = diagnose(monthly_income=3_000_000, monthly_rent=900_000, maintenance=100_000,
                 deposit=20_000_000, opportunity_rate=0.03, rir_cap=0.30)
    assert d["monthly_cost"] == 1_050_000
    assert d["over_under_krw"] == 150_000  # 초과
    assert d["verdict"] == "초과"


def test_zero_income_raises():
    with pytest.raises(ValueError):
        diagnose(monthly_income=0, monthly_rent=500_000, maintenance=0,
                 deposit=0, opportunity_rate=0.03, rir_cap=0.30)
