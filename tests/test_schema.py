"""L1 스키마 게이트 테스트 — 검증 통과 전 하위 레이어 전달 금지."""

import copy
import json

import pytest

from tests.conftest import FIXTURES

from onjeon.l1.schema import (
    ExtractionInvalid,
    gate,
    senior_claims,
    validate_extraction,
)


class TestValidateExtraction:
    def test_valid_fixture_passes(self, load_fixture):
        doc = load_fixture("register_risky_villa.json")
        assert validate_extraction(doc) == []

    def test_valid_officetel_passes(self, load_fixture):
        doc = load_fixture("register_safe_officetel.json")
        assert validate_extraction(doc) == []

    def test_missing_market_price_fails(self, load_fixture):
        doc = copy.deepcopy(load_fixture("register_risky_villa.json"))
        del doc["property"]["market_price_krw"]
        errors = validate_extraction(doc)
        assert errors and "market_price_krw" in " ".join(errors)

    def test_eul_entry_without_source_loc_fails(self, load_fixture):
        doc = copy.deepcopy(load_fixture("register_risky_villa.json"))
        del doc["register"]["eul_section"][0]["source_loc"]
        errors = validate_extraction(doc)
        assert errors and "source_loc" in " ".join(errors)

    def test_missing_price_queried_at_fails(self, load_fixture):
        # 데이터 소스에는 조회 기준일이 반드시 있어야 한다 (CLAUDE.md 컨벤션)
        doc = copy.deepcopy(load_fixture("register_risky_villa.json"))
        del doc["property"]["price_source"]["queried_at"]
        assert validate_extraction(doc)


class TestAllRegisterFixtures:
    """UI 선택지로 노출되는 모든 매물 픽스처는 게이트를 통과해야 한다."""

    @pytest.mark.parametrize(
        "path", sorted(FIXTURES.glob("register_*.json")), ids=lambda p: p.name
    )
    def test_fixture_passes_gate(self, path):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert validate_extraction(doc) == []
        assert "offer" in doc, "UI 비교 입력(offer)이 있어야 한다"


class TestGate:
    def test_gate_returns_doc_when_valid(self, load_fixture):
        doc = load_fixture("register_risky_villa.json")
        assert gate(doc) is doc

    def test_gate_raises_when_invalid(self, load_fixture):
        doc = copy.deepcopy(load_fixture("register_risky_villa.json"))
        del doc["property"]["address"]
        with pytest.raises(ExtractionInvalid):
            gate(doc)


class TestSeniorClaims:
    def test_villa_sums_active_liens(self, load_fixture):
        doc = load_fixture("register_risky_villa.json")
        assert senior_claims(doc["register"]) == 72_000_000

    def test_cancelled_lien_excluded(self, load_fixture):
        doc = copy.deepcopy(load_fixture("register_risky_villa.json"))
        doc["register"]["eul_section"][0]["cancelled"] = True
        assert senior_claims(doc["register"]) == 0

    def test_senior_lease_deposits_included(self, load_fixture):
        doc = copy.deepcopy(load_fixture("register_risky_villa.json"))
        doc["register"]["senior_lease_deposits_krw"] = 20_000_000
        assert senior_claims(doc["register"]) == 92_000_000

    def test_officetel_no_liens_is_zero(self, load_fixture):
        doc = load_fixture("register_safe_officetel.json")
        assert senior_claims(doc["register"]) == 0


class TestAmountlessEulEntry:
    """전세권·임차권 등 채권최고액이 없는 을구 등기 — 파서 지침('모르면 비워라')과 정합."""

    def _doc_with_jeonse_right(self, load_fixture):
        import copy

        doc = copy.deepcopy(load_fixture("register_risky_villa.json"))
        doc["register"]["eul_section"].append(
            {
                "rank": 2,
                "type": "전세권설정",
                "cancelled": False,
                "source_loc": {"page": 2, "section": "을구", "entry_no": 4},
            }
        )
        return doc

    def test_gate_accepts_entry_without_amount(self, load_fixture):
        doc = self._doc_with_jeonse_right(load_fixture)
        assert validate_extraction(doc) == []

    def test_senior_claims_counts_missing_amount_as_zero(self, load_fixture):
        doc = self._doc_with_jeonse_right(load_fixture)
        assert senior_claims(doc["register"]) == 72_000_000
