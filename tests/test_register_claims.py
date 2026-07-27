"""등기부 을구 채권최고액 추출 — E[Loss]의 선순위 입력을 자동 채우기 위한 편의 기능.

수동 입력이 1차 경로다. 여기서 실패해도 사용자가 직접 넣으면 기능은 동작한다
(계획서 §3.1). 그래서 추출 실패는 예외가 아니라 None을 반환한다.

가장 위험한 오작동은 **말소된 근저당까지 합산**하는 것이다. '말소사항 포함'
증명서를 그대로 더하면 선순위가 과대계상되고 E[Loss]가 부풀려진다 —
텍스트 레이어로는 취소선을 볼 수 없으므로, 탐지해서 신고만 하고 판단은 사용자에게 맡긴다.
"""

import pathlib

import pytest

from onjeon.register.parse import extract_senior_claims

VALID_ONLY = """
등기사항전부증명서(현재 유효사항)  - 건물 -
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
1  근저당권설정   채권최고액 금120,000,000원   근저당권자 국민은행
-- 이 하 여 백 --
"""

TWO_LIENS = """
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
1  근저당권설정   채권최고액 금120,000,000원   근저당권자 국민은행
2  근저당권설정   채권최고액 금 30,000,000 원   근저당권자 신한은행
"""

WITH_CANCELLED = """
등기사항전부증명서(말소사항 포함)  - 건물 -
【 을 구 】
1  근저당권설정   채권최고액 금500,000,000원   근저당권자 국민은행
2  1번근저당권설정등기말소
3  근저당권설정   채권최고액 금120,000,000원   근저당권자 우리은행
"""

NO_LIEN = """
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
-- 기 록 사 항 없 음 --
"""

# 대법원 인터넷등기소 발급본은 마지막에 '주요 등기사항 요약(참고용)' 절을 붙이고,
# 거기서 을구의 유효 근저당을 **그대로 되풀이한다**. 문서 전체를 훑으면 2배로 센다.
WITH_SUMMARY_TRAILER = """
등기사항전부증명서(현재 유효사항)  - 건물 -
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
1  근저당권설정   채권최고액 금120,000,000원   근저당권자 국민은행
-- 이 하 여 백 --

[ 주요 등기사항 요약 ] - 본 주요 등기사항 요약은 증명서상에 말소되지 않은 사항을 간략히 요약한 것
3. (근)저당권 및 전세권 등 ( 을구 )
순위번호  등기목적  접수정보  주요등기사항  대상소유자
1  근저당권설정  2020년1월1일  채권최고액 금120,000,000원 근저당권자 국민은행  소유자
"""

# 요약 절만 발급/스캔된 경우 — 본문이 없으므로 요약에서라도 읽어야 한다
SUMMARY_ONLY = """
[ 주요 등기사항 요약 ] (참고용)
3. (근)저당권 및 전세권 등 ( 을구 )
1  근저당권설정  2020년1월1일  채권최고액 금90,000,000원 근저당권자 하나은행  소유자
"""


class TestExtractSeniorClaims:
    def test_single_lien(self):
        got = extract_senior_claims(VALID_ONLY)
        assert got["senior_claims_krw"] == 120_000_000
        assert got["senior_claims_count"] == 1
        assert got["includes_cancelled"] is False

    def test_sums_multiple_liens_and_tolerates_spacing(self):
        got = extract_senior_claims(TWO_LIENS)
        assert got["senior_claims_krw"] == 150_000_000
        assert got["senior_claims_count"] == 2

    def test_no_lien_is_zero_not_none(self):
        """근저당이 없는 것과 못 읽은 것은 다르다 — 0은 '선순위 없음'이라는 정보다."""
        got = extract_senior_claims(NO_LIEN)
        assert got["senior_claims_krw"] == 0
        assert got["senior_claims_count"] == 0

    def test_cancelled_document_is_flagged(self):
        """말소사항 포함 증명서는 합계가 과대계상된다 — 신고해서 사용자가 판단하게 한다."""
        got = extract_senior_claims(WITH_CANCELLED)
        assert got["includes_cancelled"] is True
        # 취소선을 볼 수 없으므로 합계 자체는 보정하지 않는다(허구 금지)
        assert got["senior_claims_krw"] == 620_000_000

    def test_empty_text_returns_none_amount(self):
        got = extract_senior_claims("")
        assert got["senior_claims_krw"] is None

    def test_summary_trailer_is_not_double_counted(self):
        """실제 발급본의 '주요 등기사항 요약'은 을구를 되풀이한다 — 같이 세면 선순위가 2배다.

        2배가 되면 engine.lgd의 회수 예상액이 0으로 깎여 LGD가 1.0에 고정되고
        E[Loss]가 348만 → 660만원/년으로 뛴다(실측). 예외 없이 조용히 틀린다.
        가짜 등기부 픽스처엔 이 절이 없어서 다른 테스트로는 잡히지 않았다.
        """
        got = extract_senior_claims(WITH_SUMMARY_TRAILER)
        assert got["senior_claims_krw"] == 120_000_000
        assert got["senior_claims_count"] == 1

    def test_summary_only_document_still_readable(self):
        """본문 없이 요약만 있으면 요약에서 읽는다 — 못 읽었다고 하면 위험이 사라진다."""
        got = extract_senior_claims(SUMMARY_ONLY)
        assert got["senior_claims_krw"] == 90_000_000
        assert got["senior_claims_count"] == 1

    def test_ignores_non_lien_amounts(self):
        """거래가액·전세금 등 다른 금액을 채권최고액으로 오인하면 안 된다."""
        text = """
        【 갑 구 】
        2  소유권이전   거래가액 금350,000,000원
        【 을 구 】
        1  근저당권설정   채권최고액 금120,000,000원
        """
        assert extract_senior_claims(text)["senior_claims_krw"] == 120_000_000


class TestParsedPdfCarriesClaims:
    """생성된 가짜 등기부 PDF로 파이프라인 전체를 확인한다.

    파일을 **형식별로 지정**한다. 예전엔 glob의 `[0]`을 썼는데, 픽스처를 하나
    추가하자 정렬 순서가 바뀌어 엉뚱한 형식을 검사했다 — 무엇을 보증하는지
    파일 이름 정렬에 맡기면 안 된다.
    """

    FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "data/fixtures/fake_registers"

    def _parse(self, name):
        from onjeon.register.parse import parse_register_pdf

        path = self.FIXTURES / name
        if not path.exists():
            pytest.skip("가짜 등기부 PDF 없음 — scripts/gen_fake_registers.py로 생성")
        return parse_register_pdf(str(path))

    def test_jiphap_pdf_yields_claims_and_area(self):
        """집합건물(구분소유) — 전용면적 하나. 지금까지의 정상 경로."""
        fields = self._parse("서울-강남구-다세대주택.pdf")
        assert fields["senior_claims_krw"] > 0
        assert fields["exclusive_area_m2"] > 0

    def test_building_register_pdf_yields_claims_but_no_area(self):
        """건물 등기부(다중주택) — 채권최고액은 읽되 전용면적은 단정하지 않는다.

        층별 면적 중 하나를 집으면 시세가 과대추정되고 E[Loss]가 과소평가된다.
        """
        fields = self._parse("대전-유성구-다중주택-건물등기부.pdf")
        assert fields["senior_claims_krw"] == 120_000_000
        assert fields["exclusive_area_m2"] is None
        assert fields["area_note"]
        assert fields["building_use"] == "다중주택"
        assert fields["road_addr"] == "대전광역시 유성구 대학로75번길 33"
        assert any("토지 등기부" in w for w in fields["warnings"])
