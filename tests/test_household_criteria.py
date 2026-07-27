"""가구 형태(혼인·자녀)와 신용도 요건 — 정책 상품의 우대·제한이 대부분 여기 걸린다.

2026-07-27 웹 검증한 것만 판정에 쓴다:
  - 신혼가구 = 혼인 7년 이내 · 부부합산 연소득 7,500만 이하 · 순자산 3.45억 이하
  - 신생아 특례 = 출산 후 2년 이내(막내 만 0~1세)
  - 기금 대출 제한 = 연체·대지급·대위변제 등 신용도판단정보 등록자

**신용은 점수가 아니라 불리언이다.** 기금 요강에 점수 커트라인이 없고 등록정보 유무로
거른다. 점수 임계값을 지어내면 근거 없는 숫자로 자격을 판정하게 된다(CLAUDE.md 원칙 1·6).
"""

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_cache
from onjeon.decision import _eligibility_input
from onjeon.market.cache import open_cache

PROFILE = {"monthly_income_krw": 4_000_000, "assets_krw": 20_000_000, "age": 30,
           "region": "노원구", "expected_stay_years": 4}
LISTING = {"jeonse_deposit_krw": 200_000_000, "wolse_deposit_krw": 30_000_000,
           "wolse_monthly_rent_krw": 600_000, "building_type": "rh"}
NEWLYWED = "신혼가구 전용 버팀목전세자금대출"


@pytest.fixture
def client(tmp_path):
    conn = open_cache(tmp_path / "cache.db")
    app.dependency_overrides[get_cache] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()
    conn.close()


def recs(client, **profile):
    r = client.post("/api/decision", json={"profile": {**PROFILE, **profile}, "listing": LISTING})
    assert r.status_code == 200, r.text
    body = r.json()["recommendations"]
    return ([x["product_name"] for x in body["eligible"]],
            {x["product_name"]: [f["field"] for f in x["failed"]] for x in body["ineligible"]})


class TestNewlywedDerivation:
    """혼인기간을 안 적었으면 신혼으로도, 아닌 것으로도 단정하지 않는다."""

    def test_married_within_7_years_is_newlywed(self):
        got = _eligibility_input({"monthly_income_krw": 0, "is_married": True,
                                  "marriage_years": 7}, {})
        assert got["is_newlywed"] is True

    def test_married_over_7_years_is_not(self):
        got = _eligibility_input({"monthly_income_krw": 0, "is_married": True,
                                  "marriage_years": 8}, {})
        assert got["is_newlywed"] is False

    def test_married_without_years_is_not_assumed(self):
        """기혼인데 기간 미입력 — 모르는 것을 '신혼이다'로 만들지 않는다."""
        got = _eligibility_input({"monthly_income_krw": 0, "is_married": True,
                                  "marriage_years": None}, {})
        assert got["is_newlywed"] is False
        assert got["is_married"] is True  # 기혼이라는 사실 자체는 살아 있다

    def test_unmarried_is_not_newlywed(self):
        assert _eligibility_input({"monthly_income_krw": 0}, {})["is_newlywed"] is False


class TestNewbornDerivation:
    """신생아 특례 = 출산 후 2년 이내 → 막내 만 0~1세."""

    @pytest.mark.parametrize("age,expect", [(0, True), (1, True), (2, False), (5, False)])
    def test_youngest_child_age_decides(self, age, expect):
        got = _eligibility_input({"monthly_income_krw": 0, "children_count": 1,
                                  "youngest_child_age": age}, {})
        assert got["has_newborn"] is expect

    def test_no_children_means_no_newborn(self):
        """자녀 수 0인데 막내 나이가 들어와도 신생아로 치지 않는다."""
        got = _eligibility_input({"monthly_income_krw": 0, "children_count": 0,
                                  "youngest_child_age": 0}, {})
        assert got["has_newborn"] is False


class TestNewlywedProduct:
    def test_newlywed_gets_the_product(self, client):
        ok, _ = recs(client, is_married=True, marriage_years=3)
        assert NEWLYWED in ok

    def test_unmarried_blocked_with_reason(self, client):
        _, bad = recs(client)
        assert "is_newlywed" in bad[NEWLYWED]

    def test_married_over_7_years_blocked(self, client):
        _, bad = recs(client, is_married=True, marriage_years=10)
        assert "is_newlywed" in bad[NEWLYWED]

    def test_income_ceiling_is_higher_than_youth_product(self, client):
        """신혼 7,500만 vs 청년 5,000만 — 청년 상품은 떨어져도 신혼은 통과해야 한다."""
        ok, bad = recs(client, monthly_income_krw=5_500_000,  # 연 6,600만
                       is_married=True, marriage_years=2)
        assert NEWLYWED in ok
        assert "annual_income_krw" in bad["청년전용 버팀목전세자금대출"]


class TestCreditDelinquency:
    """기금 대출은 연체 등 신용도판단정보 등록자를 배제한다."""

    FUND_LOANS = {"청년전용 버팀목전세자금대출", NEWLYWED, "내집마련 디딤돌대출"}

    def test_delinquency_blocks_every_fund_loan(self, client):
        _, bad = recs(client, is_married=True, marriage_years=3, has_credit_delinquency=True)
        for name in self.FUND_LOANS:
            assert "no_credit_delinquency" in bad.get(name, []), f"{name}이 막히지 않았다"

    def test_clean_credit_passes(self, client):
        ok, _ = recs(client, is_married=True, marriage_years=3, has_credit_delinquency=False)
        assert self.FUND_LOANS <= set(ok)

    def test_subsidy_not_blocked_by_credit(self, client):
        """지원금·적금은 기금 대출이 아니라 신용도 요건이 없다 — 과잉 차단 방지."""
        ok, _ = recs(client, has_credit_delinquency=True)
        assert "청년월세 특별지원" in ok

    def test_credit_score_is_not_a_judgment_input(self, client):
        """점수는 받되 판정에 쓰지 않는다 — 검증된 점수→승인 기준표가 없기 때문이다.

        점수만 바꿨을 때 자격 결과가 달라지면, 어딘가에서 근거 없는 임계값을 쓴 것이다.
        """
        low, _ = recs(client, is_married=True, marriage_years=3, credit_score=350)
        high, _ = recs(client, is_married=True, marriage_years=3, credit_score=990)
        assert low == high


class TestDefaultsUnchanged:
    def test_omitting_new_fields_keeps_old_behavior(self, client):
        """새 필드를 안 보내면 지금까지와 같은 결과여야 한다."""
        ok, _ = recs(client)
        assert "청년전용 버팀목전세자금대출" in ok
