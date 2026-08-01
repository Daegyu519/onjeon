"""집합건물 등기부 '전유부분의 건물의 표시' → 층·호수·전용면적.

실물 집합건물 등기부는 **'전용면적'이라는 낱말을 찍지 않는다.** 표제부 안 '건물내역'
칸에 '철근콘크리트조 25.59㎡'로만 나온다. 그런데 같은 문서에 ㎡가 여러 군데 있고
어느 것도 전용면적이 아니다:

    ( 1동의 건물의 표시 )          층별 면적   120.15 / 130.24 …
    ( 대지권의 목적인 토지의 표시 )  대지면적    250.30
    ( 대지권의 표시 )              대지권비율  250.30분의 21.45
    ( 전유부분의 건물의 표시 )      건물내역    25.59  ← 이것만이 전용면적

대지면적(250.30)을 집으면 시세가 10배로 추정되고, 그만큼 LGD가 낮아져서
**E[Loss]가 과소평가된다** — 위험한 집이 안전해 보이는 방향이다(CLAUDE.md 함정 6).

기존 픽스처 26건은 전부 '전용면적 N㎡'라는 실물에 없는 줄을 쓰고 있어서, 이 절을
못 읽는 버그가 테스트를 전부 통과하면서 살아 있었다(함정 4와 같은 실패).
"""

import pytest

from onjeon.register.parse import extract_fields

# 실물 집합건물 등기부의 텍스트 구조. 절 4개가 전부 있어야 이 테스트가 뭔가를 보증한다.
JIPHAP = """등기사항전부증명서(현재 유효사항) - 집합건물 -
고유번호 1146-2005-003281
[집합건물] 서울특별시 관악구 봉천동 100-1 제3층 제301호
【 표 제 부 】 ( 1동의 건물의 표시 )
표시번호 접 수 소재지번,건물명칭 및 번호 건물내역 등기원인 및 기타사항
1 2005년5월6일 서울특별시 관악구 봉천동 100-1
[도로명주소] 서울특별시 관악구 봉천로 12
철근콘크리트조 (철근)콘크리트지붕 4층 다세대주택
1층 120.15㎡
2층 130.24㎡
3층 130.24㎡
4층 130.24㎡
( 대지권의 목적인 토지의 표시 )
표시번호 소재지번 지 목 면 적 등기원인 및 기타사항
1 서울특별시 관악구 봉천동 100-1 대 250.30㎡ 2005년5월6일 등기
【 표 제 부 】 ( 전유부분의 건물의 표시 )
표시번호 접 수 건물번호 건물내역 등기원인 및 기타사항
1 2005년5월6일 제3층 제301호 철근콘크리트조 25.59㎡
( 대지권의 표시 )
표시번호 대지권종류 대지권비율 등기원인 및 기타사항
1 1 소유권대지권 250.30분의 21.45 2005년5월6일 대지권
【 갑 구 】 ( 소유권에 관한 사항 )
1 소유권보존 소유자 김○○ 서울특별시 관악구 봉천동 100-1
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
1 근저당권설정 채권최고액 금120,000,000원 근저당권자 국민은행
-- 이 하 여 백 --
"""


class TestExclusivePart:
    def test_area_comes_from_geonmul_naeyeok_only(self):
        """건물내역의 25.59 — 층별면적·대지면적·대지권비율은 후보조차 아니다."""
        f = extract_fields(JIPHAP)
        assert f["exclusive_area_m2"] == 25.59
        assert f["area_note"] is None

    def test_floor_and_unit(self):
        f = extract_fields(JIPHAP)
        assert (f["floor"], f["unit"]) == ("3", "301")

    def test_basement_unit(self):
        """지하는 '제지하1층'으로 찍힌다 — int로 못 눌리므로 문자열로 남긴다."""
        f = extract_fields(JIPHAP.replace("제3층 제301호", "제지하1층 제101호"))
        assert (f["floor"], f["unit"]) == ("지하1", "101")

    def test_land_area_never_wins_even_with_area_keyword(self):
        """'면적 250.30'처럼 대지면적에 키워드가 붙어 나와도 전유부분이 이긴다.

        키워드 경로가 먼저 돌면 대지면적 250.30이 전용면적이 된다 — 시세 10배 과대,
        E[Loss] 과소. 절을 먼저 읽는 순서만이 이걸 막는다.
        """
        text = JIPHAP.replace("대 250.30㎡", "면적 250.30㎡")
        assert extract_fields(text)["exclusive_area_m2"] == 25.59


class TestCancelledRecords:
    def test_struck_out_area_row_is_ignored(self):
        """면적변경으로 말소된 행은 빼고 현재 유효한 면적만 읽는다."""
        text = JIPHAP.replace(
            "1 2005년5월6일 제3층 제301호 철근콘크리트조 25.59㎡",
            "1 2005년5월6일 제3층 제301호 철근콘크리트조 30.24㎡ 2018년3월2일 면적변경으로 인하여 말소\n"
            "2 2018년3월2일 제3층 제301호 철근콘크리트조 25.59㎡ 면적변경",
        )
        assert extract_fields(text)["exclusive_area_m2"] == 25.59

    def test_two_live_areas_are_not_guessed(self):
        """둘 다 유효해 보이면 값을 내지 않는다 — 최신처럼 보이는 쪽을 고르는 건 추측이다."""
        text = JIPHAP.replace(
            "1 2005년5월6일 제3층 제301호 철근콘크리트조 25.59㎡",
            "1 2005년5월6일 제3층 제301호 철근콘크리트조 30.24㎡\n"
            "2 2018년3월2일 제3층 제301호 철근콘크리트조 25.59㎡",
        )
        f = extract_fields(text)
        assert f["exclusive_area_m2"] is None
        assert "25.59" in f["area_note"] and "30.24" in f["area_note"]


class TestBuildingRegisterUnaffected:
    def test_no_exclusive_section_keeps_old_path(self):
        """건물 등기부엔 이 절이 없다 — 기존 경로(후보 여러 개면 None)가 그대로 돈다."""
        f = extract_fields("【 표 제 부 】 ( 건물의 표시 )\n1층 106.53㎡\n2층 111.21㎡\n")
        assert f["exclusive_area_m2"] is None
        assert f["floor"] is None and f["unit"] is None


# ── 취소선(빨간 줄) — 도형이라 텍스트엔 안 남는다 ────────────────────────────
# 말소된 근저당의 채권최고액은 유효한 것과 **똑같은 문자열**로 들어온다. 문구로는
# 구분할 수 없다('…말소'는 말소를 집행한 다른 행에 붙는다). 선을 봐야 한다.
reportlab = pytest.importorskip("reportlab", reason="픽스처 PDF 생성용(개발 의존성)")


_FONT = "HYSMyeongJo-Medium"
# 취소선 그은 줄. 문구엔 '말소'가 없다 — 선을 보지 않으면 살아 있는 기록과 구분되지 않는다.
_DEAD_AREA = "1 2005년5월6일 제3층 제301호 철근콘크리트조 30.24㎡"
_DEAD_CLAIM = "1 근저당권설정 채권최고액 금50,000,000원 근저당권자 우리은행"


def _pdf_with_strikethrough(path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont(_FONT, 10.5)

    def row(y, s, struck=False):
        c.drawString(50, y, s)
        if struck:  # 글자 중간을 지나는 가로줄 = 취소선
            c.line(50, y + 3.5, 50 + c.stringWidth(s, _FONT, 10.5), y + 3.5)

    row(770, "[집합건물] 서울특별시 관악구 봉천동 100-1 제3층 제301호")
    row(740, "【 표 제 부 】 ( 전유부분의 건물의 표시 )")
    row(710, _DEAD_AREA, struck=True)
    row(680, "2 2018년3월2일 제3층 제301호 철근콘크리트조 25.59㎡")
    row(650, "( 대지권의 표시 )  1 소유권대지권 250.30분의 21.45")
    row(620, "【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )")
    row(590, _DEAD_CLAIM, struck=True)
    row(560, "2 근저당권설정 채권최고액 금120,000,000원 근저당권자 국민은행")
    # 표 괘선 — 행 사이를 지나가지만 취소선이 아니다. 이것까지 말소로 세면 문서가 빈다.
    for y in (695, 665, 575, 545):
        c.line(40, y, 550, y)
    c.save()
    return path


def _jiphap_pdf(path):
    """실물 집합건물 등기부의 **레이아웃**까지 옮긴 2페이지 PDF.

    텍스트만 넣은 픽스처로는 안 잡히는 것을 잡으려는 것이다. 실물 두 건(노원구 공릉동
    412-13·559-22)에서 측정한 레이아웃 특성을 그대로 넣는다:
      - 절 순서: 1동의 건물 → 대지권의 목적인 토지 → **전유부분** → 대지권의 표시
      - 표제부가 표시번호 1·2로 두 번 실리고 1번엔 **실선**이 그어진다(대체된 행)
      - 절이 **페이지 경계**를 넘고, 페이지마다 머리글/열람일시/쪽번호가 끼어든다
      - '열 람 용' 워터마크가 표 위를 지나간다
      - 전유면적이 소수 **1자리**(58.5㎡)이고, 대지면적엔 '면적' 키워드가 붙어 있다
    마지막 줄이 핵심 함정이다 — 키워드 경로가 먼저 돌면 대지면적 250.30이 전용면적이 된다.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(UnicodeCIDFont(_FONT))
    c = canvas.Canvas(str(path), pagesize=A4)

    def page(rows):
        c.setFont(_FONT, 9.5)
        y = 800
        for s, struck in rows:
            c.drawString(40, y, s)
            if struck:
                c.line(40, y + 3.2, 40 + c.stringWidth(s, _FONT, 9.5), y + 3.2)
            y -= 26
        c.line(30, y + 14, 560, y + 14)  # 표 괘선
        c.drawString(40, 60, "열람일시 : 2026년07월28일 21시00분00초")
        c.showPage()

    page([
        ("등기사항전부증명서(말소사항 포함)  - 집합건물 -", False),
        ("[집합건물] 서울특별시 관악구 봉천동 100-1 제3층 제301호", False),
        ("【 표 제 부 】 ( 1동의 건물의 표시 )", False),
        ("1  2005년5월6일  서울특별시 관악구 봉천동 100-1", True),   # ← 대체된 행(실선)
        ("   철근콘크리트조 4층 다세대주택  1층 120.15㎡  2층 130.24㎡", True),
        ("2  서울특별시 관악구 봉천동 100-1  [도로명주소] 서울특별시 관악구 봉천로 12", False),
        ("   철근콘크리트조 4층 다세대주택", False),
        ("   1층 120.15㎡", False),
        ("   2층 130.24㎡", False),
        ("   3층 130.24㎡", False),
        ("   4층 130.24㎡", False),
        ("( 대지권의 목적인 토지의 표시 )", False),
        ("표시번호  소재지번  지 목  면 적  등기원인 및 기타사항", False),
        ("1  서울특별시 관악구 봉천동 100-1  대  면적 250.30㎡", False),  # ← 키워드 붙은 대지면적
        ("【 표 제 부 】 ( 전유부분의 건물의 표시 )", False),          # ← 절이 여기서 끊긴다
    ])
    page([
        ("[집합건물] 서울특별시 관악구 봉천동 100-1 제3층 제301호", False),
        ("표시번호  접 수  건물번호  건물내역  등기원인 및 기타사항", False),
        ("1  2005년5월6일  제3층 제301호  철근콘크리트조 58.5㎡", False),  # ← 소수 1자리
        ("열 람 용", False),
        ("( 대지권의 표시 )", False),
        ("표시번호  대지권종류  대지권비율  등기원인 및 기타사항", False),
        ("1  1 소유권대지권  250.30분의 21.45  2005년5월6일 대지권", False),
        ("【 갑 구 】 ( 소유권에 관한 사항 )", False),
        ("1  소유권보존  소유자 김서연", False),
        ("【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )", False),
        ("1  근저당권설정  채권최고액 금120,000,000원  근저당권자 국민은행", False),
        ("-- 이 하 여 백 --", False),
        ("* 실선으로 그어진 부분은 말소사항을 표시함.", False),
    ])
    c.save()
    return path


@pytest.fixture(scope="module")
def f(tmp_path_factory):
    from onjeon.register.parse import parse_register_pdf

    return parse_register_pdf(_jiphap_pdf(tmp_path_factory.mktemp("jp") / "집합건물.pdf"))


class TestRealLayoutJiphapPdf:
    """실물 레이아웃 집합건물 PDF를 `parse_register_pdf`로 끝까지 통과시킨다.

    이 문서에는 전용면적이 아닌 ㎡가 6개 있다(층별 120.15·130.24, 대지면적 250.30,
    대지권비율 21.45). 그중 **하나라도** 전용면적 자리에 들어오면 시세가 어긋나고
    E[Loss]가 통째로 틀린다.
    """

    def test_exclusive_area_is_the_geonmul_naeyeok_value(self, f):
        """소수 1자리 58.5㎡ — 절 안의 건물내역 값이다."""
        assert f["exclusive_area_m2"] == 58.5

    def test_land_area_with_keyword_did_not_win(self, f):
        """'면적 250.30㎡'라고 키워드가 붙어 있어도 대지면적은 전용면적이 아니다."""
        assert f["exclusive_area_m2"] != 250.30

    def test_no_other_area_leaked(self, f):
        """층별 면적·대지권비율도 후보가 아니다."""
        assert f["exclusive_area_m2"] not in (120.15, 130.24, 21.45)
        assert f["area_note"] is None

    def test_floor_and_unit_across_page_break(self, f):
        """전유부분 절이 페이지를 넘어가도 층·호수를 읽는다."""
        assert (f["floor"], f["unit"]) == ("3", "301")

    def test_struck_replaced_table_row_removed(self, f):
        """대체된 표제부 1행(실선)은 빼고 읽는다."""
        assert f["struck_rows"] > 0

    def test_lien_intact(self, f):
        assert f["senior_claims_krw"] == 120_000_000


@pytest.fixture(scope="module")
def fields(tmp_path_factory):
    from onjeon.register.parse import parse_register_pdf

    return parse_register_pdf(_pdf_with_strikethrough(tmp_path_factory.mktemp("reg") / "말소.pdf"))


class TestStrikethroughDropped:
    """텍스트만 읽으면 이 문서는 면적 후보 2개(30.24·25.59) + 근저당 2건이 된다.

    즉 면적은 None으로 떨어지고 선순위는 1.7억으로 과대계상된다. 선을 봐야 맞는다.
    """

    def test_cancelled_area_row_dropped(self, fields):
        assert fields["exclusive_area_m2"] == 25.59

    def test_cancelled_mortgage_not_counted(self, fields):
        assert fields["senior_claims_krw"] == 120_000_000
        assert fields["senior_claims_count"] == 1

    def test_table_rules_do_not_erase_live_rows(self, fields):
        """표 괘선을 취소선으로 오인하면 유효한 행까지 사라진다."""
        assert (fields["floor"], fields["unit"]) == ("3", "301")
