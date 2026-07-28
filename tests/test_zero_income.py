"""무소득(월소득 0) 사용자 — 거절이 아니라 결과로 답한다.

무소득 청년(학생·구직자·프리랜서 준비기)은 이 서비스가 도와야 할 대상이다.
청년전용 버팀목전세자금대출은 소득 **상한**만 있고 하한이 없어 무소득도 신청 대상이다
(주택도시기금·금융위 안내, 2026-07-27 확인).

예전엔 세 군데가 소득 0을 막았다:
  api/main.py `Field(gt=0)` → 422, decision.decide() 하드 게이트, affordability.diagnose() ValueError.
그래서 화면에 `[object Object]`만 떴다(FastAPI 422 detail이 객체 배열인데 프론트가
문자열로 취급). 지금은 200이 나오고, 소득 때문에 못 받는 상품은 미자격 반증으로 답한다.
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_cache
from onjeon.l3.affordability import diagnose
from onjeon.l3.engine import wolse_tax_credit
from onjeon.market.cache import open_cache
from onjeon.rules_io import load_rules

BASE = {
    "profile": {"monthly_income_krw": 0, "assets_krw": 20_000_000, "age": 22,
                "region": "노원구", "expected_stay_years": 2, "works_at_sme": True},
    "listing": {"jeonse_deposit_krw": 50_000_000, "wolse_deposit_krw": 30_000_000,
                "wolse_monthly_rent_krw": 300_000, "maintenance_krw": 70_000,
                "building_type": "sh", "exclusive_area_m2": 18},
}


@pytest.fixture
def client(tmp_path):
    conn = open_cache(tmp_path / "cache.db")
    app.dependency_overrides[get_cache] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()
    conn.close()


class TestZeroIncomeIsAccepted:
    def test_api_returns_200_not_422(self, client):
        """화면에 [object Object]가 뜨던 자리 — 이제 결과가 나와야 한다."""
        assert client.post("/api/decision", json=BASE).status_code == 200

    def test_negative_income_still_rejected(self, client):
        """0은 유효한 입력이지만 음수는 아니다."""
        body = {**BASE, "profile": {**BASE["profile"], "monthly_income_krw": -1}}
        assert client.post("/api/decision", json=body).status_code == 422

    def test_jeonse_wolse_comparison_still_computed(self, client):
        """소득과 무관한 계산은 그대로 나와야 한다 — RIR 하나 때문에 전부 잃으면 안 된다."""
        jw = client.post("/api/decision", json=BASE).json()["jeonse_vs_wolse"]
        assert jw["cheaper"] in {"전세", "월세"}
        assert jw["jeonse"]["annual_krw"] > 0 and jw["wolse"]["annual_krw"] > 0


class TestRirUnavailableNotZero:
    """RIR은 분모가 소득이라 0에서 정의되지 않는다. 0%로 표시하면 '부담 없음'으로 읽힌다."""

    def test_diagnose_reports_unavailable_with_reason(self):
        d = diagnose(monthly_income=0, monthly_rent=300_000, maintenance=70_000,
                     deposit=30_000_000, opportunity_rate=0.035, rir_cap=0.25)
        assert d["available"] is False
        assert d["reason"]
        assert d["rir_actual"] is None and d["verdict"] is None

    def test_monthly_cost_still_reported(self):
        """'얼마 쓰는지'는 소득과 무관하게 답할 수 있다."""
        d = diagnose(monthly_income=0, monthly_rent=300_000, maintenance=70_000,
                     deposit=0, opportunity_rate=0.035, rir_cap=0.25)
        assert d["monthly_cost"] == 370_000

    def test_normal_income_unchanged(self):
        d = diagnose(monthly_income=2_800_000, monthly_rent=300_000, maintenance=70_000,
                     deposit=0, opportunity_rate=0.035, rir_cap=0.25)
        assert d["available"] is True
        assert d["rir_actual"] == pytest.approx(370_000 / 2_800_000)
        assert d["verdict"] in {"적정", "초과"}

    def test_negative_income_raises(self):
        with pytest.raises(ValueError):
            diagnose(monthly_income=-1, monthly_rent=0, maintenance=0,
                     deposit=0, opportunity_rate=0.035, rir_cap=0.25)


class TestNoTaxCreditWithoutIncome:
    """세액공제는 산출세액에서 빼는 것이라 낼 세금이 없으면 0이다.

    회귀 지점: 구간표가 소득 **상한**만 보므로 그냥 매칭하면 소득 0이 최저구간에 걸려
    공제가 붙는다 → 무소득자에게 월세가 실제보다 싸게 계산되고 결론이 월세로 기운다.
    """

    def test_zero_income_gets_no_credit(self):
        assert wolse_tax_credit(3_600_000, 0, load_rules("tax_rules")) == 0

    def test_normal_income_still_gets_credit(self):
        assert wolse_tax_credit(3_600_000, 33_600_000, load_rules("tax_rules")) > 0

    def test_api_breakdown_shows_zero_credit(self, client):
        jw = client.post("/api/decision", json=BASE).json()["jeonse_vs_wolse"]
        assert jw["wolse"]["breakdown"]["월세세액공제"] == 0


class TestEligibilityAtZeroIncome:
    """소득 하한이 있는 상품만 떨어져야 한다 — 나머지는 통과."""

    def _recs(self, client, income):
        body = {**BASE, "profile": {**BASE["profile"], "monthly_income_krw": income}}
        return client.post("/api/decision", json=body).json()["recommendations"]

    def test_jeonse_loan_eligible_without_income(self, client):
        """사용자 지적 사항 — 버팀목은 소득 상한만 있고 하한이 없다."""
        names = [r["product_name"] for r in self._recs(client, 0)["eligible"]]
        assert "청년전용 버팀목전세자금대출" in names

    def test_savings_account_ineligible_without_income(self, client):
        """청년미래적금은 소득금액 증명이 불가능하면 가입 대상이 아니다."""
        bad = {r["product_name"]: r for r in self._recs(client, 0)["ineligible"]}
        assert "청년미래적금" in bad
        # 미자격 반증: 어느 조건에서 걸렸는지 말해야 한다
        assert any(f["field"] == "annual_income_krw" for f in bad["청년미래적금"]["failed"])

    def test_savings_account_eligible_with_income(self, client):
        names = [r["product_name"] for r in self._recs(client, 2_800_000)["eligible"]]
        assert "청년미래적금" in names


class TestTaxCreditRequiresHomelessHouseholdHead:
    """조특법 §95조의2는 **무주택 세대주**를 요구한다 — 소득 상한만 보면 조건의 절반이다.

    법령 원문 대조(2026-07-28, 시행 2026-07-01):
      "주택을 소유하지 아니한 … 세대의 세대주로서 해당 과세기간의 총급여액이
       8천만원 이하인 근로소득이 있는 근로자 … 100분의 15[5천500만원 이하는 17]"

    받지도 못할 공제를 빼주면 월세가 실제보다 싸 보인다 — 소득 0 때와 같은 방향의 오류다.
    """

    RULES = None

    def _credit(self, **kw):
        return wolse_tax_credit(3_600_000, 33_600_000, load_rules("tax_rules"), **kw)

    def test_homeless_household_head_gets_credit(self):
        assert self._credit(is_homeless=True, is_household_head=True) > 0

    def test_homeowner_gets_nothing(self):
        assert self._credit(is_homeless=False, is_household_head=True) == 0

    def test_non_household_head_gets_nothing(self):
        assert self._credit(is_homeless=True, is_household_head=False) == 0

    def test_api_drops_credit_for_homeowner(self, client):
        """배선 확인 — 엔진만 고치고 호출측이 안 넘기면 화면은 그대로다."""
        body = {
            "profile": {**BASE["profile"], "monthly_income_krw": 2_800_000, "is_homeless": False},
            "listing": BASE["listing"],
        }
        jw = client.post("/api/decision", json=body).json()["jeonse_vs_wolse"]
        assert jw["wolse"]["breakdown"]["월세세액공제"] == 0

    def test_api_keeps_credit_for_homeless(self, client):
        body = {
            "profile": {**BASE["profile"], "monthly_income_krw": 2_800_000, "is_homeless": True},
            "listing": BASE["listing"],
        }
        jw = client.post("/api/decision", json=body).json()["jeonse_vs_wolse"]
        assert jw["wolse"]["breakdown"]["월세세액공제"] < 0  # 비용에서 빼므로 음수
