"""수직 슬라이스 통합 테스트 — 픽스처 → 게이트 → L2 → L3 → 리포트.

데모의 핵심 단언: 위험 빌라는 기대손실 반영 시 '월세 유리',
모든 수치에 인용(source_loc·기준일)이 붙는다.
"""

import pytest

from onjeon.compare import run_comparison
from onjeon.l1.schema import gate, senior_claims
from onjeon.l2.model import train
from onjeon.l2.synth import generate
from onjeon.l3.eligibility import evaluate
from onjeon.rules_io import load_products, load_rules


@pytest.fixture(scope="module")
def model():
    return train(generate(1500, seed=42))


@pytest.fixture
def persona(load_fixture):
    return load_fixture("persona_kim.json")


@pytest.fixture
def villa(load_fixture):
    return load_fixture("register_risky_villa.json")


@pytest.fixture
def officetel(load_fixture):
    return load_fixture("register_safe_officetel.json")


class TestRulesIO:
    def test_load_versioned_rules(self):
        assert load_rules("tax_rules")["version"] == "2026-07"
        assert load_rules("market_params")["version"] == "2026-07"
        assert "관악구" in load_rules("auction_rates")["rates"]

    def test_load_products(self):
        products = load_products()
        ids = {p["rule_id"] for p in products}
        assert {"youth-jeonse-loan-2026-07", "sme-youth-jeonse-2026-07"} <= ids


class TestVerticalSlice:
    def test_report_recommends_wolse_for_risky_villa(self, persona, villa, officetel, model):
        report = run_comparison(
            persona=persona, villa_doc=villa, officetel_doc=officetel, model=model
        )
        assert report["best"] == "월세"
        assert report["wolse"]["total"] < report["jeonse"]["total"]

    def test_risk_ordering_villa_above_officetel(self, persona, villa, officetel, model):
        report = run_comparison(
            persona=persona, villa_doc=villa, officetel_doc=officetel, model=model
        )
        assert report["jeonse"]["p_accident"] > report["wolse"]["p_accident"]
        assert report["jeonse"]["e_loss"] > 0

    def test_lgd_matches_hand_calculation(self, persona, villa, officetel, model):
        # 1.5억×0.78 = 1.17억 − 선순위 0.72억 → 회수 0.45억 → LGD 0.625
        report = run_comparison(
            persona=persona, villa_doc=villa, officetel_doc=officetel, model=model
        )
        assert report["jeonse"]["lgd"] == pytest.approx(0.625)

    def test_every_number_has_citations(self, persona, villa, officetel, model):
        report = run_comparison(
            persona=persona, villa_doc=villa, officetel_doc=officetel, model=model
        )
        citations = report["jeonse"]["citations"]
        assert any(c.get("section") == "을구" and c.get("entry_no") == 3 for c in citations)
        assert report["sources"]["market_price_queried_at"] == "2026-07-15"
        assert report["sources"]["tax_rules_version"] == "2026-07"

    def test_gate_and_senior_claims_direct(self, villa):
        assert senior_claims(gate(villa)["register"]) == 72_000_000


class TestEligibilityVerticalSlice:
    def test_persona_passes_youth_product_fails_sme(self, persona, villa):
        user = {
            "age": persona["age"],
            "annual_income_krw": persona["annual_income_krw"],
            "assets_krw": persona["assets_krw"],
            "deposit_krw": villa["offer"]["jeonse_deposit_krw"],
        }
        by_id = {p["rule_id"]: evaluate(user, p) for p in load_products()}

        assert by_id["youth-jeonse-loan-2026-07"]["eligible"] is True

        sme = by_id["sme-youth-jeonse-2026-07"]
        assert sme["eligible"] is False
        [failure] = sme["failed"]
        assert failure["gap"] == 1_000_000
        assert sme["alternatives"] == ["youth-jeonse-loan-2026-07"]
