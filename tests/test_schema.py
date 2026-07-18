"""L1 스키마 게이트 테스트 — 검증 통과 전 하위 레이어 전달 금지."""

import copy

import pytest

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
