"""건물 등기부(단독·다가구·다중주택) 파싱 — 집합건물과 형식이 다르다.

실물 등기부(대전 유성구 궁동 다중주택, 2026-02-07 열람)에서 확인한 차이:
  - 전용면적이 아니라 **층별 면적**이 여러 줄 나온다 (1층 106.53 / 2·3층 111.21)
  - 도로명주소가 표 셀 안에서 **줄바꿈**된다
  - 근저당이 토지와 **공동담보**로 걸려 있고, 토지 등기부는 별도다
  - '단독주택(다중주택)'처럼 용도가 병기된다

가장 위험한 오작동은 층별 면적 중 하나를 전용면적이라 부르는 것이다. 예외가 나지
않고 그럴듯한 숫자가 나오므로 눈으로는 못 잡는다 — 시세가 과대추정되고 그만큼
LGD가 낮아져서 **E[Loss]가 과소평가된다**(위험한 집이 안전해 보이는 방향).
"""

import pytest

from onjeon.register.parse import extract_fields, register_limits

# 실물 등기부의 텍스트 구조를 그대로 옮긴 것. 층별 면적·줄바꿈된 도로명주소·
# 공동담보 문구가 핵심이며, 이 셋이 빠진 픽스처는 아무것도 보증하지 않는다.
DAJUNG_BUILDING = """등기사항전부증명서(현재 유효사항)
- 건물 -
고유번호 1601-2007-000270
[건물] 대전광역시 유성구 궁동 471-3
【 표 제 부 】 ( 건물의 표시 )
대전광역시 유성구 궁동
471-3
[도로명주소]
대전광역시 유성구
대학로75번길 33
철근콘크리트구조
(철근)콘크리트지붕 3층
단독주택(다중주택)
1층 단독주택(다중주택)
106.53㎡
2층 단독주택(다중주택)
111.21㎡
3층 단독주택(다중주택)
111.21㎡
【 갑 구 】 ( 소유권에 관한 사항 )
1 소유권보존 2007년1월19일 제5900호
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
1 근저당권설정 2007년10월24일 제85144호
채권최고액 금120,000,000원
근저당권자 농업협동조합중앙회
공동담보 토지 대전광역시 유성구 궁동
471-3의 담보물에 추가
-- 이 하 여 백 --
"""

# 집합건물(구분소유) — 전유부분 면적이 하나. 지금까지 잘 되던 경로가 안 깨져야 한다.
JIPHAP_UNIT = """등기사항전부증명서(현재 유효사항)  - 건물 -
[집합건물] 서울특별시 관악구 봉천동 100-1
【 표 제 부 】 ( 전유부분의 건물의 표시 )
[도로명주소] 서울특별시 관악구 봉천로 12
철근콘크리트조 다세대주택
전용면적 59.94㎡
【 을 구 】
1  근저당권설정   채권최고액 금72,000,000원   근저당권자 국민은행
"""


class TestAreaNotGuessed:
    def test_multi_floor_areas_do_not_become_exclusive_area(self):
        """층별 면적이 여러 개면 None — 첫 매치(1층 106.53)를 집으면 안 된다."""
        f = extract_fields(DAJUNG_BUILDING)
        assert f["exclusive_area_m2"] is None
        assert f["area_note"] and "직접 입력" in f["area_note"]
        # 사유에 실제 후보를 적어야 사용자가 무슨 일인지 안다
        assert "106.53" in f["area_note"] and "111.21" in f["area_note"]

    def test_single_area_still_parsed(self):
        """집합건물 경로 회귀 방지 — 전유부분 면적 하나는 그대로 쓴다."""
        assert extract_fields(JIPHAP_UNIT)["exclusive_area_m2"] == 59.94
        assert extract_fields(JIPHAP_UNIT)["area_note"] is None

    def test_area_keyword_wins_over_multiple_bare_numbers(self):
        """'전용면적' 키워드가 있으면 다른 ㎡ 숫자가 있어도 그것이 답이다."""
        text = JIPHAP_UNIT + "\n공용부분 12.30㎡\n대지권 35.70㎡\n"
        assert extract_fields(text)["exclusive_area_m2"] == 59.94

    def test_missing_area_does_not_discard_the_rest(self):
        """면적 하나 못 읽었다고 문서 전체를 버리면 안 된다.

        예전엔 ValueError를 올렸고, 그래서 OCR을 이미 돌린 뒤에도 같은 예외가
        멀쩡히 읽은 채권최고액까지 통째로 버리고 422를 냈다.
        """
        f = extract_fields("【 을 구 】 채권최고액 금1,000,000원")
        assert f["exclusive_area_m2"] is None
        assert f["area_note"]
        assert f["senior_claims_krw"] == 1_000_000  # ← 이게 살아남아야 한다

    def test_ocr_trailing_digit_noise_is_trimmed(self):
        """OCR이 ㎡를 숫자로 읽어 '70.941'이 돼도 2자리로 끊어 원값을 복구한다."""
        assert extract_fields("전용면적 70.941")["exclusive_area_m2"] == 70.94


# 실물 다중주택 등기부의 층별 면적표(노원구 공릉동 412-13·559-22, 2026-07-28 열람).
# 위 DAJUNG_BUILDING과 다른 세 가지가 여기에 있고, 셋 다 실제로 결함을 만들었다:
#   - 소수 **1자리** 면적('지1층 63.7㎡') — 2자리만 받는 정규식이 통째로 놓쳤다
#   - '(연면적제외)' 옥탑 — 전용면적 후보가 아니다(다음 줄에 오는 판본도 있다)
#   - **모든 층이 같은 면적** — 집합으로 합치면 후보가 1개가 돼 자동채움된다
NOWON_DAJUNG = """등기사항전부증명서(말소사항 포함)
- 건물 -
[건물] 서울특별시 노원구 공릉동 412-13 태평아트1
【 표 제 부 】 ( 건물의 표시 )
표시번호 접 수 소재지번,건물명칭 및 번호 건 물 내 역 등기원인 및 기타사항
1 2017년5월31일 서울특별시 노원구 공릉동 철근콘크리트구조
412-13 태평아트1 (철근)콘크리트지붕 3층
[도로명주소] 다중주택
서울특별시 노원구 공릉로 1층 45.29㎡
154-19 2층 45.29㎡
3층 45.29㎡
지1층 63.7㎡
옥탑1층
7.44㎡(연면적제외)
【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )
1 근저당권설정 채권최고액 금391,300,000원 근저당권자 영동농업협동조합
"""


class TestRealDajungFloorTable:
    def test_one_decimal_area_is_read(self):
        """실물이 '지1층 63.7㎡'로 찍는다 — 소수 2자리만 받으면 이 층이 사라진다."""
        note = extract_fields(NOWON_DAJUNG)["area_note"]
        assert "63.7" in note

    def test_okttap_marked_as_excluded_from_floor_area(self):
        """옥탑 7.44㎡는 '(연면적제외)' — 전용면적 후보로 세면 안 된다."""
        note = extract_fields(NOWON_DAJUNG)["area_note"]
        assert "연면적제외" in note

    def test_identical_floor_areas_are_not_autofilled(self):
        """모든 층이 45.29㎡면 집합에서 하나로 합쳐진다 — 개수로 판단하면 자동채움된다.

        1·2·3층만 있는 다중주택(지하·옥탑 없음)이면 후보가 45.29 하나다. 이게 전용면적으로
        채워지면 원룸 20㎡ 세입자의 시세가 2배로 잡히고 **E[Loss]가 과소평가된다**.
        """
        only_same = """【 표 제 부 】 ( 건물의 표시 )
철근콘크리트구조 3층 다중주택
1층 45.29㎡
2층 45.29㎡
3층 45.29㎡
"""
        f = extract_fields(only_same)
        assert f["exclusive_area_m2"] is None
        assert "방을 빌리므로" in f["area_note"]

    def test_floors_are_labelled_in_the_note(self):
        """라벨 없는 숫자 목록은 '45.29가 답이겠지'를 유도한다 — 층을 붙여 보여준다."""
        note = extract_fields(NOWON_DAJUNG)["area_note"]
        assert "1층 45.29㎡" in note and "지1층 63.7㎡" in note


class TestRoadAddressAcrossLines:
    def test_wrapped_road_address_is_joined(self):
        """표 셀에서 줄이 나뉘어도 '…로/길 번지'까지 잡는다 — 건물 특정에 필요하다."""
        assert extract_fields(DAJUNG_BUILDING)["road_addr"] == "대전광역시 유성구 대학로75번길 33"

    def test_single_line_road_address_unchanged(self):
        assert extract_fields(JIPHAP_UNIT)["road_addr"] == "서울특별시 관악구 봉천로 12"


class TestSpecificUseWins:
    def test_dajung_beats_dandok_when_both_present(self):
        """'단독주택(다중주택)' — 위치상 단독이 먼저지만 위험 성격은 다중이 결정한다."""
        assert extract_fields(DAJUNG_BUILDING)["building_use"] == "다중주택"


class TestLimitsSurfaced:
    def test_building_register_warns_about_separate_land_register(self):
        w = " ".join(extract_fields(DAJUNG_BUILDING)["warnings"])
        assert "토지 등기부" in w

    def test_joint_collateral_warned(self):
        assert any("공동담보" in x for x in extract_fields(DAJUNG_BUILDING)["warnings"])

    def test_dajung_warns_about_other_tenants_deposits(self):
        w = " ".join(extract_fields(DAJUNG_BUILDING)["warnings"])
        assert "확정일자" in w  # 등기부 밖에서 확인해야 하는 선순위

    def test_jiphap_unit_has_no_land_register_warning(self):
        """집합건물은 토지·건물이 한 등기부다 — 없는 경고를 붙이면 노이즈가 된다."""
        w = " ".join(extract_fields(JIPHAP_UNIT)["warnings"])
        assert "토지 등기부" not in w

    def test_register_kind_detected(self):
        assert extract_fields(DAJUNG_BUILDING)["register_kind"] == "건물"
        assert extract_fields(JIPHAP_UNIT)["register_kind"] == "집합건물"

    def test_limits_is_pure_function_of_text_and_use(self):
        assert register_limits("[건물] 서울시", None)  # 종류만으로도 경고가 나온다
        assert register_limits("[집합건물] 서울시", "다세대주택") == []


class TestClaimsStillWork:
    def test_senior_claim_read_from_real_format(self):
        """'금120,000,000원' — '금' 접두·쉼표가 붙은 실제 표기."""
        assert extract_fields(DAJUNG_BUILDING)["senior_claims_krw"] == 120_000_000
