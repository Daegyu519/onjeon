"""등기부 을구 채권최고액 추출 — E[Loss]의 선순위 입력을 자동 채우기 위한 편의 기능.

수동 입력이 1차 경로다. 여기서 실패해도 사용자가 직접 넣으면 기능은 동작한다
(계획서 §3.1). 그래서 추출 실패는 예외가 아니라 None을 반환한다.

가장 위험한 오작동은 **말소된 근저당까지 합산**하는 것이다. '말소사항 포함'
증명서를 그대로 더하면 선순위가 과대계상되고 E[Loss]가 부풀려진다. 말소는 두 경로로
배제한다 — 취소선(도형)은 `_page_text`가 텍스트 조립에서 걷어내고, 말소 등기가 적은
순위번호('1번근저당권설정등기말소')는 여기서 짚어 뺀다. 문서가 스스로 말하는 것만
배제한다. 둘 다 없으면 빼지 않는다(과대 방향 = 안전 방향).

반대 방향의 오탐이 더 위험하다: 유효 근저당을 말소로 오인하면 선순위가 과소계상돼
E[Loss]가 줄고 **위험한 집이 안전해 보인다**. 그래서 순위번호 패턴을 좁게 잡는다.
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

    def test_cancelled_lien_is_excluded_and_flagged(self):
        """말소된 근저당은 뺀다 — 근거는 문서에 있다('1번근저당권설정등기말소').

        이미 말소된 근저당은 담보 부담이 아니다. 합산하면 선순위가 5억 과대계상돼
        E[Loss]가 부풀고 전세가 실제보다 나빠 보인다. 문서가 스스로 어느 순위번호가
        말소됐는지 적으므로 이건 판단을 지어내는 게 아니라 읽는 것이다.
        """
        got = extract_senior_claims(WITH_CANCELLED)
        assert got["includes_cancelled"] is True
        assert got["senior_claims_krw"] == 120_000_000
        assert got["senior_claims_count"] == 1
        assert got["cancelled_claims_krw"] == 500_000_000  # 화면이 얼마를 뺐는지 말해야 한다

    def test_release_date_line_is_not_read_as_rank_number(self):
        """'2020년5월30일 해지'의 2020을 순위번호로 오인하면 유효 근저당이 사라진다.

        그 방향의 오답은 선순위 과소 → E[Loss] 과소 → **위험한 집이 안전해 보인다**.
        """
        text = """
        【 을 구 】
        1  근저당권설정   채권최고액 금120,000,000원   근저당권자 국민은행
        2  2번근저당권설정등기말소
        2020년5월30일 해지
        """
        assert extract_senior_claims(text)["senior_claims_krw"] == 120_000_000

    def test_unattributable_cancellation_keeps_the_amount(self):
        """어느 순위인지 안 적혀 있으면 빼지 않는다 — 못 짚으면 과대 쪽(안전 쪽)에 남긴다."""
        text = """
        【 을 구 】
        1  근저당권설정   채권최고액 금120,000,000원   근저당권자 국민은행
        2  근저당권설정등기말소
        """
        got = extract_senior_claims(text)
        assert got["senior_claims_krw"] == 120_000_000
        assert got["cancelled_claims_count"] == 0

    def test_gapgu_cancellation_does_not_touch_eulgu_liens(self):
        """갑구의 '2번소유권이전등기말소'가 을구 2번 근저당을 지우면 안 된다."""
        text = """
        【 갑 구 】
        3  2번소유권이전등기말소
        【 을 구 】
        2  근저당권설정   채권최고액 금80,000,000원   근저당권자 신한은행
        """
        assert extract_senior_claims(text)["senior_claims_krw"] == 80_000_000

    def test_multiline_lien_row_is_excluded_whole(self):
        """행은 여러 줄에 걸친다 — 순위번호는 첫 줄에만 있고 금액은 다음 줄일 수 있다."""
        text = """
        【 을 구 】
        1  근저당권설정   2015년3월2일 제5000호
           채권최고액 금50,000,000원
           근저당권자 우리은행
        2  근저당권설정   채권최고액 금120,000,000원   근저당권자 국민은행
        3  1번근저당권설정등기말소
        """
        got = extract_senior_claims(text)
        assert got["senior_claims_krw"] == 120_000_000
        assert got["cancelled_claims_krw"] == 50_000_000

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
