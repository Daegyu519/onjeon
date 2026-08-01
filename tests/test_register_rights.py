"""등기부 갑구·을구 권리 제한 탐지 + 등급.

E[Loss]와 **다른 축**이다 — 이 등급이 🟢여도 전세가율이 높으면 기대손실은 크다.
그래서 여기서 지켜야 할 것은 '숫자가 맞는가'가 아니라 두 방향의 오답이다:

  과소(위험한 집이 안전해 보임) — 가압류를 못 잡거나, 유효한 등기를 말소로 오인하거나,
    OCR이라 못 읽은 문서를 🟢로 내보내는 것. **이쪽이 치명적이다.**
  과대(안전한 집이 위험해 보임) — 말소된 가압류를 세거나, '가압류' 한 줄을 '압류'로도
    세는 것. 사용자가 등기부와 대조하면 드러나므로 덜 위험하지만 신뢰를 깎는다.
"""

import pathlib

import pytest

from onjeon.l3.register_risk import grade_register
from onjeon.register.parse import extract_rights, parse_register_pdf

SEIZURE = """
등기사항전부증명서(말소사항 포함)  - 건물 -
【 갑 구 】 ( 소유권에 관한 사항 )
1  소유권이전   2019년3월4일   매매   소유자 김OO
2  가압류   2024년5월17일   청구금액 금50,000,000원   채권자 서울보증보험
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
1  근저당권설정   채권최고액 금120,000,000원   근저당권자 국민은행
"""

CLEAN = """
등기사항전부증명서(현재 유효사항)  - 집합건물 -
【 갑 구 】 ( 소유권에 관한 사항 )
1  소유권이전   2019년3월4일   매매   소유자 김OO
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
1  근저당권설정   채권최고액 금120,000,000원   근저당권자 국민은행
"""

# 취소선(도형)이 없는 OCR·촬영본. 말소를 짚을 단서는 순위번호를 적은 말소 등기뿐이다.
CANCELLED_SEIZURE = """
등기사항전부증명서(말소사항 포함)  - 건물 -
【 갑 구 】 ( 소유권에 관한 사항 )
2  가압류   2024년5월17일   채권자 서울보증보험
3  2번가압류등기말소   2024년11월2일   해제
"""

# 갑구 2번 말소가 을구 2번 근저당까지 지워버리면 선순위가 과소계상된다.
CROSS_SECTION_RANKS = """
【 갑 구 】 ( 소유권에 관한 사항 )
2  가압류   2024년5월17일   채권자 서울보증보험
3  2번가압류등기말소   2024년11월2일   해제
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
2  전세권설정   2023년1월9일   전세금 금100,000,000원
"""

# 실물 발급본의 **줄 구조**를 그대로 본뜬 위험 등기부.
# 실물 2건(노원구 412-13·559-22)에는 가압류·경매개시가 하나도 없어서, 진짜 양성을
# 실물 레이아웃에서 확인할 자리가 없다. 그래서 레이아웃만 실물에서 가져왔다 —
# 한 행이 여러 줄에 걸치고, 순위번호는 첫 줄에만 있고, 등기원인·권리자는 아랫줄이다.
# 위 SEIZURE 같은 한 줄짜리 합성 텍스트만으로는 이 구조에서 도는지 알 수 없다(함정 4·10).
REAL_LAYOUT_RISKY = """등기사항전부증명서(말소사항 포함)  - 건물 -
[건물] 서울특별시 노원구 공릉동 412-13 태평아트1
【 갑 구 】
( 소유권에 관한 사항 )
순위번호 등 기 목 적 접 수 등 기 원 인 권리자 및 기타사항
1 소유권보존 2017년5월31일 소유자 임OO 500825-*******
제39357호
2 소유권이전 2024년3월11일 2024년2월20일 소유자 김OO 900101-*******
제20114호 매매 거래가액 금320,000,000원
3 소유권이전 2024년11월5일 2024년10월2일 소유자 박OO 880303-*******
제88210호 매매 거래가액 금410,000,000원
4 가압류 2025년6월17일 2025년6월16일 청구금액 금50,000,000원
제55120호 서울북부지방법원 채권자 서울보증보험주식회사
가압류결정
5 임의경매개시결정 2026년2월3일 2026년2월2일 채권자 주식회사국민은행
제10022호 서울북부지방법원
임의경매개시결정
【 을 구 】
( 소유권 이외의 권리에 관한 사항 )
순위번호 등 기 목 적 접 수 등 기 원 인 권리자 및 기타사항
1 근저당권설정 2024년3월11일 2024년3월11일 채권최고액 금240,000,000원
제20115호 설정계약 근저당권자 주식회사국민은행
2 주택임차권 2025년12월9일 2025년11월28일 임차보증금 금180,000,000원
제99001호 서울북부지방법원 임차인 이OO
임차권등기명령
열람일시 : 2026년07월31일 09시40분00초
"""

FREQUENT_TRANSFER = """
【 갑 구 】 ( 소유권에 관한 사항 )
3  소유권이전   2025년2월10일   매매   소유자 김OO
4  소유권이전   2025년8월20일   매매   소유자 이OO
"""


def _fields(rights, **kw):
    """등급 함수의 입력 최소형 — 파서가 채우는 키만 흉내낸다."""
    return {"rights": rights, "senior_claims_krw": 120_000_000, "senior_claims_count": 1, **kw}


class TestDetect:
    def test_seizure_is_cited_with_section_rank_and_date(self):
        """위험요소는 원문 위치와 함께 나온다 (CLAUDE.md 원칙 2)."""
        found = {r["key"]: r for r in extract_rights(SEIZURE)}
        assert found["가압류"]["section"] == "갑구"
        assert found["가압류"]["rank"] == "2"
        assert found["가압류"]["date"] == "2024-05-17"
        assert "가압류" in found["가압류"]["quote"]

    def test_seizure_does_not_also_match_apreension(self):
        """'가압류' 한 줄이 '압류'로도 잡히면 같은 사실이 두 항목이 된다."""
        assert "압류" not in {r["key"] for r in extract_rights(SEIZURE)}

    def test_cancelled_seizure_is_marked_not_counted(self):
        """취소선이 없는 OCR 경로에서도 말소는 순위번호로 짚인다.

        말소된 가압류를 유효로 세면 안전한 집이 위험해 보인다.
        """
        found = {r["key"]: r for r in extract_rights(CANCELLED_SEIZURE)}
        assert found["가압류"]["cancelled"] is True  # 목록엔 남는다 — 원문을 숨기지 않는다
        assert grade_register(_fields(extract_rights(CANCELLED_SEIZURE)))["grade"] == "low"

    def test_cancellation_does_not_leak_across_sections(self):
        """갑구 2번 말소가 을구 2번을 지우면 선순위가 과소계상된다 — 오답의 위험 방향."""
        found = {r["key"]: r for r in extract_rights(CROSS_SECTION_RANKS)}
        assert found["가압류"]["cancelled"] is True
        assert found["전세권"]["cancelled"] is False

    def test_summary_trailer_is_not_double_counted(self):
        """'주요 등기사항 요약'은 을구를 되풀이한다 — 같이 세면 2배가 된다(함정 4)."""
        text = SEIZURE + """
[ 주요 등기사항 요약 ] - 참고용
2. 소유지분을 제외한 소유권에 관한 사항 ( 갑구 )
2  가압류  2024년5월17일  채권자 서울보증보험
"""
        assert len([r for r in extract_rights(text) if r["key"] == "가압류"]) == 1


class TestGrade:
    def test_seizure_is_high(self):
        risk = grade_register(_fields(extract_rights(SEIZURE)))
        assert risk["grade"] == "high"
        assert risk["label"] == "🔴 높음"
        assert [i["key"] for i in risk["items"]] == ["가압류"]

    def test_clean_register_is_low_and_never_says_safe(self):
        """🟢는 '안전'이 아니라 '이 문서에서 보이는 권리 제한이 없다'까지다."""
        risk = grade_register(_fields(extract_rights(CLEAN)))
        assert risk["grade"] == "low"
        assert risk["items"] == []
        assert "안전" not in risk["label"]

    def test_ocr_without_findings_is_undetermined(self):
        """못 읽은 문서가 🟢로 나가는 것이 이 기능의 최악의 실패다(원칙 5)."""
        risk = grade_register(_fields(extract_rights(CLEAN), ocr=True))
        assert risk["grade"] == "unknown"
        assert risk["note"]

    def test_ocr_with_findings_keeps_the_red_flag(self):
        """저신뢰를 이유로 진짜 적신호를 '판정 보류'에 묻지 않는다."""
        risk = grade_register(_fields(extract_rights(SEIZURE), ocr=True))
        assert risk["grade"] == "high"
        assert risk["note"]  # 대조하라는 안내는 그대로 붙는다

    def test_unreadable_claims_is_undetermined_but_zero_is_not(self):
        """None(못 읽음)과 0(근저당 없음)은 다르다."""
        rights = extract_rights(CLEAN)
        assert grade_register(_fields(rights, senior_claims_krw=None))["grade"] == "unknown"
        assert grade_register(_fields(rights, senior_claims_krw=0))["grade"] == "low"

    def test_three_or_more_liens_is_caution(self):
        risk = grade_register(_fields(extract_rights(CLEAN), senior_claims_count=3))
        assert risk["grade"] == "caution"
        assert "근저당 3건" in [i["key"] for i in risk["items"]]

    def test_frequent_transfer_is_caution(self):
        """짧은 기간의 반복 이전 — 접수일이 문서에 적혀 있으므로 추정이 아니다."""
        risk = grade_register(_fields(extract_rights(FREQUENT_TRANSFER)))
        assert risk["grade"] == "caution"
        assert "잦은 소유권 이전" in [i["key"] for i in risk["items"]]

    def test_single_transfer_is_not_flagged(self):
        assert grade_register(_fields(extract_rights(CLEAN)))["items"] == []


class TestRealLayout:
    """실물 발급본 줄 구조에서 진짜 양성이 잡히는가 — 이 기능의 회수율 그 자체."""

    def test_all_risks_found_with_their_positions(self):
        risk = grade_register(_fields(extract_rights(REAL_LAYOUT_RISKY)))
        found = {i["key"]: i for i in risk["items"]}
        assert risk["grade"] == "high"
        assert set(found) == {"가압류", "경매개시결정", "임차권등기", "잦은 소유권 이전"}
        # 행이 여러 줄에 걸쳐도 순위번호·접수일이 첫 줄에서 정확히 붙어야 한다
        assert (found["가압류"]["section"], found["가압류"]["rank"]) == ("갑구", "4")
        assert found["가압류"]["date"] == "2025-06-17"
        assert (found["임차권등기"]["section"], found["임차권등기"]["rank"]) == ("을구", "2")
        assert found["경매개시결정"]["date"] == "2026-02-03"

    def test_transfer_twice_in_eight_months_is_flagged(self):
        """2024-03-11 → 2024-11-05. 접수일이 문서에 적혀 있으므로 추정이 아니다."""
        rights = extract_rights(REAL_LAYOUT_RISKY)
        dates = sorted(r["date"] for r in rights if r["key"] == "소유권이전")
        assert dates == ["2024-03-11", "2024-11-05"]

    def test_preservation_is_not_a_transfer(self):
        """'소유권보존'(최초 등기)은 이전이 아니다 — 세면 모든 등기부가 1회를 얻는다."""
        assert "소유권보존" not in REAL_LAYOUT_RISKY.split("\n")[0]  # 문서 종류 오인 방지
        rights = extract_rights(REAL_LAYOUT_RISKY)
        assert all(r["rank"] != "1" for r in rights if r["key"] == "소유권이전")


class TestExplainNeverBreaksTheResponse:
    """LLM 설명은 곁가지다 — 없거나 실패해도 등급·항목은 그대로 나가야 한다.

    여기서 예외가 새면 등기부 업로드 전체가 422로 떨어진다(함정 7과 같은 실패:
    한 필드의 실패가 문서 전체를 버리는 것).
    """

    def test_returns_none_without_a_key(self, monkeypatch):
        from onjeon.l4 import register_explain

        monkeypatch.setattr(register_explain, "make_llm", lambda: None)
        assert register_explain.explain(grade_register(_fields(extract_rights(SEIZURE)))) is None

    def test_swallows_call_failures(self, monkeypatch):
        from onjeon.l4 import register_explain

        class Boom:
            def complete(self, prompt, *, system=None, images=None):
                raise RuntimeError("타임아웃")

        monkeypatch.setattr(register_explain, "make_llm", Boom)
        assert register_explain.explain(grade_register(_fields(extract_rights(SEIZURE)))) is None

    def test_prompt_carries_items_and_grade(self, monkeypatch):
        """LLM은 이미 정해진 등급·항목을 받는다 — 스스로 판정하지 않는다(원칙 1)."""
        from onjeon.l4 import register_explain

        seen = {}

        class Spy:
            def complete(self, prompt, *, system=None, images=None):
                seen["prompt"], seen["system"] = prompt, system
                return "설명입니다."

        monkeypatch.setattr(register_explain, "make_llm", Spy)
        risk = grade_register(_fields(extract_rights(SEIZURE)))
        assert register_explain.explain(risk, ["토지 등기부는 별도다"]) == "설명입니다."
        assert "가압류" in seen["prompt"] and "high" in seen["prompt"]
        assert "토지 등기부는 별도다" in seen["prompt"]
        assert "등급을 바꾸" in seen["system"]


# 실물 발급본. 합성 픽스처가 실물과 다르면 테스트는 아무것도 보증하지 않는다(함정 4·10).
_REAL = sorted(pathlib.Path("data/fixtures/real_registers").glob("*.pdf"))


@pytest.mark.skipif(not _REAL, reason="실물 등기부 없음(저장소 미추적)")
@pytest.mark.parametrize("path", _REAL, ids=lambda p: p.stem)
def test_real_registers_produce_a_grade(path):
    """실물에서 파이프라인이 끝까지 돈다 — 절 구분이 각주에 걸려 뒤집히지 않는지 포함.

    두 문서 모두 갑구에 압류·가압류가 없다(2026-07-28 열람). 여기서 high가 나오면
    각주의 '기록사항 없는 갑구, 을구는…' 같은 줄을 항목으로 오인한 것이다.
    """
    fields = parse_register_pdf(str(path))
    risk = grade_register(fields)
    assert risk["grade"] in {"high", "caution", "low", "unknown"}
    assert risk["grade"] != "high", [i["quote"] for i in risk["items"]]
