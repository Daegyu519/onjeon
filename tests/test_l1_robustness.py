"""실물 등기부 대응 강건성 — 실제 Gemini 추출은 우리 스키마와 완벽히 안 맞는다.

핵심 원칙: 계산에 실제로 쓰는 필드(채권최고액·말소여부·시세·건물유형)만 필수로
막고, 인용용 부가 필드(source_loc·rank·set_date)는 없어도 통과시킨다.
그래야 실물 등기부가 파이프라인을 통과한다.
"""

import copy

from onjeon.compare import run_comparison
from onjeon.l1.schema import gate, senior_claims, validate_extraction
from onjeon.l2.model import train
from onjeon.l2.synth import generate

# 실물 등기부에서 Gemini가 뽑을 법한 '최소' 추출 — source_loc·rank·cancelled·
# title_section·senior_lease_deposits_krw 누락, building_type이 enum 밖.
REALISTIC_EXTRACTION = {
    "property": {
        "address": "서울특별시 강남구 역삼동 000-00 ㅇㅇ빌 501호",
        "building_type": "다세대주택",  # 우리 enum(빌라/오피스텔/아파트/기타) 밖
        "market_price_krw": 300_000_000,
        "price_source": {"api": "사용자 입력", "queried_at": "2026-07-22"},
    },
    "register": {
        "eul_section": [
            {"type": "근저당권설정", "max_claim_krw": 180_000_000},  # rank·cancelled·source_loc 없음
        ],
        "gap_section": [],
    },
}


class TestRealisticExtractionPasses:
    def test_gate_accepts_minimal_real_extraction(self):
        assert validate_extraction(REALISTIC_EXTRACTION) == []
        gate(REALISTIC_EXTRACTION)  # 예외 없이 통과

    def test_senior_claims_handles_missing_cancelled(self):
        # cancelled 누락 → 보수적으로 '말소 안 됨' 취급(위험 과소평가 방지)
        assert senior_claims(REALISTIC_EXTRACTION["register"]) == 180_000_000

    def test_senior_claims_handles_missing_senior_lease(self):
        reg = copy.deepcopy(REALISTIC_EXTRACTION["register"])
        assert "senior_lease_deposits_krw" not in reg
        assert senior_claims(reg) == 180_000_000  # KeyError 없이

    def test_full_pipeline_runs_on_real_extraction(self):
        # source_loc 없는 실추출도 3안 비교까지 완주 (citations도 안 죽음)
        persona = {"age": 30, "annual_income_krw": 40_000_000, "assets_krw": 50_000_000,
                   "expected_stay_years": 4}
        doc = copy.deepcopy(REALISTIC_EXTRACTION)
        doc["offer"] = {"jeonse_deposit_krw": 270_000_000, "sale_price_krw": 300_000_000, "insured": False}
        officetel = copy.deepcopy(REALISTIC_EXTRACTION)
        officetel["property"]["building_type"] = "오피스텔"
        officetel["register"]["eul_section"] = []
        officetel["offer"] = {"wolse_deposit_krw": 10_000_000, "monthly_rent_krw": 700_000, "insured": False}
        model = train(generate(800, seed=1))
        report = run_comparison(persona=persona, villa_doc=doc, officetel_doc=officetel, model=model)
        assert report["best"] in ("전세", "월세", "매수")
        assert report["jeonse"]["e_loss"] >= 0
        # 인용: source_loc 없어도 크래시 없이 항목이 나온다
        assert isinstance(report["jeonse"]["citations"], list)


class TestCriticalFieldsStillGate:
    """계산에 꼭 필요한 것은 여전히 막아야 한다 (게이트의 존재 이유)."""

    def test_missing_market_price_still_blocked(self):
        doc = copy.deepcopy(REALISTIC_EXTRACTION)
        del doc["property"]["market_price_krw"]
        assert validate_extraction(doc)  # 시세 없으면 차단

    def test_missing_register_still_blocked(self):
        doc = copy.deepcopy(REALISTIC_EXTRACTION)
        del doc["register"]
        assert validate_extraction(doc)
