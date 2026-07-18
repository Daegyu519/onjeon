"""Pydantic v2 인입 모델 테스트 — jsonschema 게이트(l1.schema)와 병행.

실제 픽스처 5종·룰 DB 2종이 그대로 파싱되는지(하위호환),
오타·음수 같은 오염 입력이 ValidationError로 차단되는지,
선택 필드 결측이 None + missing_fields() + warning 로그로 드러나는지 검증.
"""

import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from onjeon.data_pipeline.molit import parse_trades
from onjeon.ingest_models import RegisterDoc, RuleDoc, TradeRecord
from onjeon.rules_io import load_products

FIXTURES = Path(__file__).resolve().parent.parent / "data" / "fixtures"
REGISTER_FIXTURES = sorted(FIXTURES.glob("register_*.json"))


class TestRegisterDoc:
    def test_five_register_fixtures_exist(self):
        assert len(REGISTER_FIXTURES) == 5

    @pytest.mark.parametrize("path", REGISTER_FIXTURES, ids=lambda p: p.stem)
    def test_fixture_parses(self, path):
        doc = RegisterDoc.model_validate_json(path.read_text(encoding="utf-8"))
        assert doc.property.building_type in {"빌라", "오피스텔", "아파트", "기타"}
        assert doc.property.market_price_krw >= 0
        assert isinstance(doc.register.senior_lease_deposits_krw, int)
        for entry in doc.register.eul_section:
            assert entry.source_loc.page >= 1

    def test_building_type_typo_rejected_with_field_name(self, load_fixture):
        data = load_fixture("register_risky_villa.json")
        data["property"]["building_type"] = "빌리"  # 오타
        with pytest.raises(ValidationError) as exc:
            RegisterDoc.model_validate(data)
        assert "building_type" in str(exc.value)

    def test_missing_max_claim_is_none_and_listed(self, load_fixture, caplog):
        data = load_fixture("register_risky_villa.json")
        del data["register"]["eul_section"][0]["max_claim_krw"]
        with caplog.at_level(logging.WARNING, logger="onjeon.ingest"):
            doc = RegisterDoc.model_validate(data)
        assert doc.register.eul_section[0].max_claim_krw is None
        assert "register.eul_section[0].max_claim_krw" in doc.missing_fields()
        assert any("max_claim_krw" in rec.getMessage() for rec in caplog.records)

    def test_complete_fixture_has_no_missing_optional_fields(self, load_fixture):
        doc = RegisterDoc.model_validate(load_fixture("register_risky_villa.json"))
        assert doc.missing_fields() == []

    def test_negative_max_claim_rejected(self, load_fixture):
        data = load_fixture("register_risky_villa.json")
        data["register"]["eul_section"][0]["max_claim_krw"] = -1
        with pytest.raises(ValidationError):
            RegisterDoc.model_validate(data)

    def test_missing_offer_is_none_and_listed(self, load_fixture):
        data = load_fixture("register_risky_villa.json")
        del data["offer"]
        doc = RegisterDoc.model_validate(data)
        assert doc.offer is None
        assert "offer" in doc.missing_fields()


class TestRuleDoc:
    def test_both_product_rules_parse(self):
        products = load_products()
        assert len(products) == 2
        for raw in products:
            rule = RuleDoc.model_validate(raw)
            assert rule.rule_id == raw["rule_id"]
            assert rule.criteria, "자격요건 없는 룰은 무의미"

    def test_invalid_op_rejected(self):
        raw = load_products()[0]
        raw["criteria"][0]["op"] = "<"  # 허용 연산자 아님
        with pytest.raises(ValidationError) as exc:
            RuleDoc.model_validate(raw)
        assert "op" in str(exc.value)


class TestTradeRecord:
    SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
    <response><body><items><item>
      <dealAmount>15,000</dealAmount><excluUseAr>29.75</excluUseAr><floor>3</floor>
      <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>12</dealDay>
      <umdNm>봉천동</umdNm><buildYear>2015</buildYear>
    </item></items></body></response>"""

    def test_parse_trades_output_validates(self):
        # molit.parse_trades 출력 형태와의 계약 — 원(₩) 정수, YYYY-MM-DD
        [trade] = parse_trades(self.SAMPLE_XML)
        record = TradeRecord.model_validate(trade)
        assert record.price_krw == 150_000_000
        assert record.deal_date == "2026-06-12"

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError) as exc:
            TradeRecord(
                price_krw=-1, area_m2=29.75, floor=3,
                deal_date="2026-06-12", dong="봉천동", build_year=2015,
            )
        assert "price_krw" in str(exc.value)
