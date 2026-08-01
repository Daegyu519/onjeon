"""실물 등기부 회귀 테스트 — 합성 픽스처가 아니라 발급본 그 자체로 검증한다.

CLAUDE.md 함정 4·10·11이 전부 "픽스처가 실물과 달라서 버그가 테스트를 통과했다"는
실패였다. 합성 문서로 만든 보증은 합성 문서에만 유효하다. 그래서 실물 발급본을
`data/fixtures/real_registers/`에 두고 파이프라인 전체를 여기에 고정한다.

파일은 **저장소에 없다** — 소유자 이름·주민번호 일부가 담긴 발급본이라 `.gitignore`의
`*.pdf`로 추적하지 않는다. 없으면 skip한다(다른 사람 환경에서 실패하지 않게).

세 건 다 서울 노원구 공릉동, '말소사항 포함', 2026-07-28 열람.
각주가 규칙을 명시한다: **"실선으로 그어진 부분은 말소사항을 표시함."**

  412-13  건물(다중주택). 갑구 1-1(민간임대주택등기)만 말소, 1-2는 유효 — 오탐/미탐을
          한 문서에서 가른다
  559-22  건물(다중주택). **표제부 표시번호 1 전체가 말소**되고 2가 유효. 을구 근저당 2건은
          채권최고액에 실선이 없어 유효하고, 변경 전 채무자·근저당권자·주소에만 실선이 있다.
          매매목록의 거래가액 8.5억이 채권최고액과 같은 문서에 있다.
  559-27  **집합건물**(제1층 제101호). 함정 10을 실물로 고정하는 자리다 — 전에는 실물
          형식을 손으로 옮긴 픽스처뿐이었다. 같은 문서에 ㎡가 네 종류로 있고(전유부분
          29.59 / 층별 52.36·97.06·90.05 / 대지면적 199.3 / 대지권비율 20.45) 정답은
          전유부분 하나다. 표제부 표시번호 1·2가 전부 말소되고 3만 유효하며,
          공동담보목록 21개 호실 중 일부해지된 행에 실선이 있다.
"""

import pathlib

import pytest

from onjeon.register.parse import extract_fields, parse_register_pdf

REAL = pathlib.Path(__file__).resolve().parent.parent / "data/fixtures/real_registers"
DAJUNG_412 = REAL / "노원구-공릉동-412-13-다중주택-말소사항포함.pdf"
DAJUNG_559 = REAL / "노원구-공릉동-559-22-다중주택-표제부말소.pdf"
JIPHAP_527 = REAL / "노원구-공릉동-559-27-집합건물-제101호.pdf"


def _parse(path):
    if not path.exists():
        pytest.skip(f"실물 등기부 없음(저장소 미추적) — {path.name}")
    return parse_register_pdf(path)


def _page(path, i):
    """실선 제거를 거친 페이지 텍스트와 (원문, 실선줄 수)."""
    import pdfplumber

    from onjeon.register.parse import _page_text

    if not path.exists():
        pytest.skip(f"실물 등기부 없음 — {path.name}")
    with pdfplumber.open(path) as pdf:
        return (*_page_text(pdf.pages[i]), pdf.pages[i].extract_text() or "")


@pytest.fixture(scope="module")
def f412():
    return _parse(DAJUNG_412)


@pytest.fixture(scope="module")
def f559():
    return _parse(DAJUNG_559)


@pytest.fixture(scope="module")
def f527():
    return _parse(JIPHAP_527)


class TestAddressAndKind:
    def test_412_address(self, f412):
        assert (f412["sido"], f412["sigungu"], f412["dong"], f412["jibun"]) == (
            "서울특별시", "노원구", "공릉동", "412-13",
        )

    def test_559_address(self, f559):
        assert (f559["sigungu"], f559["dong"], f559["jibun"]) == ("노원구", "공릉동", "559-22")

    def test_both_are_building_registers_for_dajung(self, f412, f559):
        """'다중주택' — 다른 세입자 보증금이 선순위라 위험 성격이 전혀 다르다."""
        for f in (f412, f559):
            assert f["register_kind"] == "건물"
            assert f["building_use"] == "다중주택"

    def test_559_use_is_dajung_not_dandok(self, f559):
        """'단독주택(다중주택)' 병기 — 위치상 단독이 먼저지만 다중이 위험을 결정한다."""
        assert f559["building_use"] == "다중주택"


class TestSeniorClaims:
    def test_412_single_live_lien(self, f412):
        assert (f412["senior_claims_krw"], f412["senior_claims_count"]) == (391_300_000, 1)

    def test_559_sums_two_live_liens(self, f559):
        """2.04억 + 0.36억. 두 근저당의 채권최고액엔 실선이 없다(=유효).

        변경 전 채무자·근저당권자에만 실선이 있는데, 그걸 근저당 말소로 오인해 빼면
        선순위가 과소계상돼 **E[Loss]가 줄고 위험한 집이 안전해 보인다**.
        """
        assert (f559["senior_claims_krw"], f559["senior_claims_count"]) == (240_000_000, 2)

    def test_no_lien_wrongly_cancelled(self, f412, f559):
        for f in (f412, f559):
            assert f["cancelled_claims_krw"] == 0
            assert f["includes_cancelled"] is True  # 증명서 종류는 신고한다

    def test_559_transaction_price_is_not_a_lien(self, f559):
        """매매목록의 거래가액 8.5억을 채권최고액으로 세면 선순위가 4.5배가 된다.

        그 금액이 실제로 이 문서에(실선 없이, 유효하게) 있다는 것까지 확인해야
        테스트가 뭔가를 보증한다 — 없는 금액을 안 셌다는 건 보증이 아니다.
        """
        text, _, _ = _page(DAJUNG_559, 2)
        assert "850,000,000" in text
        assert f559["senior_claims_krw"] == 204_000_000 + 36_000_000

    def test_joint_collateral_warned(self, f412, f559):
        """둘 다 토지와 공동담보 — 이 건물만의 부담이 아니라 회수액 추정이 달라진다."""
        for f in (f412, f559):
            assert any("공동담보" in w for w in f["warnings"])


class TestRedStrikethrough:
    """빨간 실선 = 말소. 실물에서만 확인되는 성질이라 여기에 고정한다."""

    def test_412_cancelled_row_dropped_and_live_row_kept(self):
        """말소된 갑구 1-1은 빠지고 유효한 1-2는 남아야 한다.

        접수번호로 확인한다 — 1-1은 제178584호, 1-2는 제141527호다. 한쪽만 보면
        미탐(둘 다 남음)과 오탐(둘 다 사라짐)을 구분할 수 없다.
        """
        text, n, _ = _page(DAJUNG_412, 0)
        assert "제178584호" not in text, "말소된 1-1이 남았다"
        assert "제141527호" in text, "유효한 1-2가 실선으로 오인돼 사라졌다"
        assert n > 0

    def test_559_struck_pyojebu_row_halves_duplicated_values(self):
        """표제부 표시번호 1이 전체 말소, 2가 유효 — 같은 값이 두 번 실린 문서다.

        1행이 빠지면 중복 값이 **정확히 절반**이 된다(61.88: 2→1, 45.98: 6→3).
        안 빠지면 층 면적이 10개로 보이고, 과하게 빠지면 0이 된다.
        """
        text, n, raw = _page(DAJUNG_559, 0)
        for token in ("(철근)콘크리트지붕", "단독주택(다중주택)", "61.88", "9.72"):
            assert raw.count(token) == 2 and text.count(token) == 1, token
        assert raw.count("45.98") == 6 and text.count("45.98") == 3
        assert n > 0

    def test_559_live_gapgu_row_untouched(self):
        """같은 페이지의 유효한 갑구(소유권보존)는 건드리지 않는다."""
        text, _, raw = _page(DAJUNG_559, 0)
        assert raw.count("제12724호") == text.count("제12724호") == 1

    def test_559_superseded_debtor_dropped_current_kept(self):
        """변경 전 채무자(최영옥)는 실선 → 제거, 현재 채무자(이미자)는 유지."""
        text, _, raw = _page(DAJUNG_559, 1)
        assert "최영옥" in raw and "최영옥" not in text
        assert "이미자" in text


class TestAreaIsAbsentNotGuessed:
    def test_no_exclusive_area(self, f412, f559):
        """다중주택 임차인은 층이 아니라 방을 빌린다 — 그 면적은 이 문서에 없다.

        층 면적(45.29/45.98)을 채우면 원룸 20㎡ 세입자의 시세가 2배 이상으로 잡히고
        **E[Loss]가 과소평가된다**(위험한 집이 안전해 보이는 방향).
        """
        for f in (f412, f559):
            assert f["exclusive_area_m2"] is None
            assert "방을 빌리므로" in f["area_note"]

    def test_412_note_labels_every_floor(self, f412):
        """라벨 없는 숫자 목록은 '45.29가 답이겠지'를 유도한다."""
        for token in ("1층 45.29㎡", "2층 45.29㎡", "3층 45.29㎡", "지1층 63.7㎡"):
            assert token in f412["area_note"], token

    def test_559_note_labels_every_floor_once(self, f559):
        """말소된 표제부 1행 때문에 같은 층이 두 번 나오면 안 된다."""
        note = f559["area_note"]
        for token in ("지1층 61.88㎡", "1층 45.98㎡", "2층 45.98㎡", "3층 45.98㎡"):
            assert token in note, token
        assert note.count("지1층 61.88㎡") == 1

    def test_okttap_marked_as_excluded(self, f412, f559):
        """옥탑은 '(연면적제외)' — 라벨·면적·괄호가 서로 다른 줄에 있어도 붙여 읽는다."""
        assert "7.44㎡(연면적제외)" in f412["area_note"]
        assert "9.72㎡(연면적제외)" in f559["area_note"]

    def test_one_decimal_floor_area_not_lost(self, f412, f559):
        """'지1층 63.7㎡'·'옥탑층 9.72 ㎡' — 소수 2자리를 요구하면 층이 통째로 사라진다."""
        assert "63.7" in f412["area_note"]
        assert "9.72" in f559["area_note"]


class TestNoJeonyuSection:
    def test_neither_document_has_jeonyu_or_daejigwon(self):
        """건물 등기부엔 전유부분·대지권 절이 없다 — 그래서 층·호수도 None이 정답이다.

        전용면적이 '못 읽힌' 게 아니라 **문서에 존재하지 않는다**. 이 테스트가 그 근거다.
        """
        import pdfplumber

        for path in (DAJUNG_412, DAJUNG_559):
            if not path.exists():
                pytest.skip(f"실물 등기부 없음 — {path.name}")
            with pdfplumber.open(path) as pdf:
                text = "\n".join(p.extract_text() or "" for p in pdf.pages)
            assert "전유부분" not in text and "대지권" not in text
            f = extract_fields(text)
            assert (f["floor"], f["unit"]) == (None, None)


class TestRoadAddress:
    """도로명주소 — 실물에선 **옆 칸 글자가 같은 줄에 섞여 든다**.

    창을 열어 통째로 삼키던 예전 방식은 세 건 모두 틀렸다. 412-13은 '공릉로 1층
    45.29㎡'의 1을 번지로 집어 **'서울특별시 노원구 공릉로 1'** — 실재할 수 있는 다른
    주소를 확신했다. 계산에 쓰이는 값은 아니지만 API 응답에 그대로 실린다.
    """

    def test_412_number_is_not_the_floor(self, f412):
        assert f412["road_addr"] == "서울특별시 노원구 공릉로 154-19"

    def test_559_drops_interleaved_use_and_floor_area(self, f559):
        assert f559["road_addr"] == "서울특별시 노원구 동일로182길 63-11"

    def test_527_drops_interleaved_building_use(self, f527):
        assert f527["road_addr"] == "서울특별시 노원구 동일로182길 63-21"


class TestJiphapUnit:
    """집합건물 실물 — ㎡가 네 종류로 있고 정답은 전유부분 하나다(함정 10)."""

    def test_exclusive_area_is_the_jeonyu_one(self, f527):
        """29.59㎡. 대지면적 199.3을 집으면 6.7배 → 시세 과대 → **E[Loss] 과소평가**."""
        assert f527["exclusive_area_m2"] == 29.59
        assert f527["area_note"] is None  # 읽었으므로 사유가 없다

    def test_floor_and_unit(self, f527):
        assert (f527["floor"], f527["unit"], f527["register_kind"]) == ("1", "101", "집합건물")

    def test_address(self, f527):
        assert (f527["sigungu"], f527["dong"], f527["jibun"]) == ("노원구", "공릉동", "559-27")

    def test_single_live_lien(self, f527):
        """4.8억 1건. 1-1은 '근저당권이전'(회사합병)이라 새 근저당이 아니다 — 2건으로
        세면 선순위가 2배가 된다."""
        assert (f527["senior_claims_krw"], f527["senior_claims_count"]) == (480_000_000, 1)
        assert f527["cancelled_claims_krw"] == 0

    def test_mixed_use_is_not_decided_for_us(self, f527):
        """표제부에 '제1종근린생활시설/도시형생활주택'이 함께 있고 전유부분엔 용도가 없다.

        근생(상가)이면 주택임대차보호법의 대항력·최우선변제가 달라진다. 둘 중 하나를
        고르면 그 차이가 조용히 사라지므로 경고로 남긴다.
        """
        assert f527["building_use"] == "근린생활시설"
        assert any("근린생활시설과 주택이 함께" in w for w in f527["warnings"])

    def test_joint_collateral_warned(self, f527):
        """공동담보목록에 21개 호실 — 4.8억이 이 호실만의 부담이 아니다."""
        assert any("공동담보" in w for w in f527["warnings"])

    def test_struck_pyojebu_leaves_only_the_live_row(self):
        """표제부 표시번호 1·2 말소, 3만 유효 — 층 면적이 세 벌에서 한 벌로 줄어야 한다.

        표시번호 1에만 있는 5층 55.05는 사라지고, 증축 후 값 90.05는 한 번 남는다.
        안 빠지면 층이 9개로 보이고, 과하게 빠지면 표제부가 통째로 사라진다.
        """
        text, n, raw = _page(JIPHAP_527, 0)
        assert (raw.count("52.36"), text.count("52.36")) == (3, 1)
        assert (raw.count("97.06"), text.count("97.06")) == (9, 3)
        assert "55.05" in raw and "55.05" not in text
        assert (raw.count("90.05"), text.count("90.05")) == (2, 1)
        assert n > 0

    def test_struck_daejigwon_and_joint_collateral_rows(self):
        """말소된 대지권 별도등기와 일부해지된 공동담보 행만 빠진다."""
        p1, _, raw1 = _page(JIPHAP_527, 1)
        assert "별도등기 있음" in raw1 and "별도등기 있음" not in p1
        assert "29.59" in p1 and p1.count("199.3") == 2  # 유효한 전유부분·대지면적은 남는다
        p2, _, raw2 = _page(JIPHAP_527, 2)
        assert "제2층 제203호" in raw2 and "제2층 제203호" not in p2  # 2021-01-07 일부해지
        assert "480,000,000" in p2  # 근저당 본문은 유효


class TestTextLayerNotOcr:
    def test_digital_text_layer(self, f412, f559, f527):
        """텍스트 레이어가 있으니 OCR을 타지 않는다 — 탔으면 저신뢰 경고가 붙어야 한다."""
        for f in (f412, f559, f527):
            assert f.get("ocr") is None
