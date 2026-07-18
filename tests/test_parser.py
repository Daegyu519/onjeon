"""L1 등기부 파서 테스트 — LLM 추출은 스키마 게이트 통과 후에만 반환된다."""

import copy
import json

import pytest

from onjeon.l1.parser import EXTRACT_PROMPT, parse_register
from onjeon.l1.schema import ExtractionInvalid
from onjeon.llm import MockLLM


class TestExtractPrompt:
    def test_prompt_names_register_sections(self):
        # 등기부 구조(표제부/갑구/을구)를 프롬프트에 명시해야 추출 정확도가 나온다
        for section in ("표제부", "갑구", "을구"):
            assert section in EXTRACT_PROMPT


class TestParseRegister:
    def test_valid_extraction_returns_doc(self, load_fixture):
        doc = load_fixture("register_risky_villa.json")
        llm = MockLLM(["```json\n" + json.dumps(doc, ensure_ascii=False) + "\n```"])
        result = parse_register(["page1-image-bytes"], llm)
        assert result["register"]["eul_section"][0]["max_claim_krw"] == 72_000_000
        assert llm.calls[0]["images"] == ["page1-image-bytes"]

    def test_unfenced_json_also_parses(self, load_fixture):
        doc = load_fixture("register_safe_officetel.json")
        llm = MockLLM([json.dumps(doc, ensure_ascii=False)])
        result = parse_register([b"img"], llm)
        assert result["property"]["building_type"] == "오피스텔"

    def test_schema_violation_blocked(self, load_fixture):
        doc = copy.deepcopy(load_fixture("register_risky_villa.json"))
        del doc["property"]["market_price_krw"]
        llm = MockLLM([json.dumps(doc, ensure_ascii=False)])
        with pytest.raises(ExtractionInvalid):
            parse_register([b"img"], llm)

    def test_non_json_response_raises(self):
        llm = MockLLM(["등기부를 읽을 수 없습니다"])
        with pytest.raises(ValueError):
            parse_register([b"img"], llm)
