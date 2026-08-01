"""등기부등본 PDF → 핵심 필드(주소·전용면적·용도) 텍스트 파싱.

비전 LLM 아님. 텍스트 레이어가 없는 스캔본은 NoTextLayer로 신호(유료 OCR 미사용).
"""

from __future__ import annotations

import re
from functools import lru_cache

import pdfplumber

from onjeon.rules_io import load_rules

# '면적' 키워드 있으면 우선(㎡는 OCR이 떨구므로 불요구), 없으면 'N㎡' 숫자로 폴백.
#
# **소수 최대 2자리로 끊는다.** 오른쪽 앵커가 없으면 OCR이 ㎡를 숫자로 읽어 뒤에 자릿수를
# 덧붙인다 — 실측으로 70.94가 70.941 / 70.940 / 70.9407로 나왔다. 2자리에서 끊으면
# 그 잡음이 잘려나가고 원값이 복구된다.
# **1자리도 받는다** — 실물 등기부가 '지1층 63.7㎡'로 찍는다(노원구 공릉동 412-13,
# 2026-07-28 열람). 2자리만 받던 정규식은 이 값을 통째로 놓쳤다.
_AREA_RE = re.compile(r"면적\s*([\d,]+\.\d{1,2})")
_AREA_FALLBACK_RE = re.compile(r"([\d,]+\.\d+)\s*㎡")
# 건물용도 — '용도' 키워드 없이 유형명 직접 매칭(실제 양식엔 '다세대주택' 등만 표기)
_USE_RE = re.compile(r"(오피스텔|아파트|연립주택|다세대주택|단독주택|다중주택|주상복합|근린생활시설)")
# '단독주택(다중주택)'처럼 병기되면 _USE_RE는 왼쪽의 '단독주택'을 집는다(정규식은
# 대안 순서가 아니라 **위치**가 먼저다). 다중·다가구는 다른 세입자 보증금이 선순위라
# 위험 성격이 전혀 다르므로 더 구체적인 쪽을 먼저 찾는다.
_SPECIFIC_USE_RE = re.compile(r"(다중주택|다가구주택|다가구용\s*단독주택)")
# 등기부 종류. 건물/토지 등기부는 **짝이 따로 있다** — 한쪽만 읽으면 선순위가 샌다.
_KIND_RE = re.compile(r"\[(집합건물|건물|토지)\]")
# 공동담보: 채권최고액이 토지·건물에 함께 걸려 있다는 표시.
_JOINT_RE = re.compile(r"공동담보")
_SIDO_RE = re.compile(r"(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|"
                      r"울산광역시|세종특별자치시|경기도|강원(?:특별자치)?도|충청북도|충청남도|"
                      r"전라북도|전북특별자치도|전라남도|경상북도|경상남도|제주특별자치도)")
_SIGUNGU_RE = re.compile(r"[가-힣]+(?:시|군|구)")  # findall — sido와 겹치면 제외
# 도로명주소. 표 셀 안에서 '대전광역시 유성구 / 대학로75번길 33'처럼 줄이 나뉘므로
# `(.+)`로 한 줄만 잡으면 건물을 특정하는 '…로/길 번지'가 통째로 날아간다.
# 창을 60자로 열고 '…로/길 N(-N)'까지 삼킨다. `[가-힣0-9]*`가 greedy라 '대학로75'가
# 아니라 '대학로75번길'을 먼저 집는다(백트래킹이 더 긴 쪽을 선호).
# 괄호는 관대하게 — OCR이 '[도로명주소]'의 닫는 괄호를 ')'로 읽는다(실측).
# 대괄호를 강제하면 스캔본에서 도로명주소가 통째로 날아간다.
_ROAD_RE = re.compile(
    r"[\[(]?\s*도로명주소\s*[\])]?\s*(.{0,60}?[가-힣0-9]*(?:로|길)\s*\d+(?:-\d+)?)", re.S
)
_DONG_RE = re.compile(r"[가-힣]+(?:동|가|리)")  # 법정동(예: 봉천동) — 첫 매치
_JIBUN_RE = re.compile(r"\d+(?:-\d+)?")  # 지번(예: 100-1) — dong 매치 위치 이후에서 검색
# 을구 근저당 채권최고액. '금' 유무·공백 변형을 허용하되 '채권최고액' 키워드를 요구해
# 거래가액·전세금 같은 다른 금액을 오인하지 않는다.
_CLAIM_RE = re.compile(r"채권최고액\s*금?\s*([\d,]+)\s*원")
# 말소사항 포함 증명서는 취소된 근저당까지 텍스트에 남는다 — 합계가 과대계상된다.
_CANCELLED_RE = re.compile(r"말소사항\s*포함|말소사항포함")
# 말소된 근저당을 짚는 확실한 신호 — 말소 등기 행이 **대상 순위번호를 적는다**
# ('2번근저당권설정등기말소'). 문서가 스스로 무엇이 말소됐는지 말하므로 추측이 아니다.
# 취소선(도형)은 OCR·촬영본에 아예 없으므로 이 문구가 그 경로의 유일한 방어선이다.
_VOID_TARGET_RE = re.compile(
    r"(\d{1,2}(?:-\d{1,2})?)번\s*(?:근저당권|지상권|전세권|임차권)[^\n]{0,24}?말소"
)
# 행 머리의 순위번호. 숫자 뒤 **공백**을 요구해서 '2020년5월30일'은 걸리지 않는다 —
# 접수일자를 순위번호로 오인하면 멀쩡한 근저당이 말소로 지워지고, 그 방향의 오답은
# 선순위 과소 → E[Loss] 과소 → 위험한 집이 안전해 보인다.
_RANK_LINE_RE = re.compile(r"^\s*(\d{1,2}(?:-\d{1,2})?)\s+\S")
# 대법원 인터넷등기소 발급본 끝에 붙는 '주요 등기사항 요약(참고용)' 절.
# 을구의 유효 근저당을 그대로 되풀이하므로 문서 전체를 훑으면 2배로 센다.
_SUMMARY_RE = re.compile(r"주요\s*등기사항\s*요약")

# ── 권리 제한 탐지(갑구·을구) ────────────────────────────────────────────────
# 절 경계. **대괄호를 요구한다** — 실물 각주에 "기록사항 없는 갑구, 을구는 '기록사항
# 없음'으로 표시함"이 있어서(노원구 412-13·559-22 실측) 낱말만 보면 문서 끝에서 절이
# 뒤집히고, 그 뒤 항목의 구가 전부 틀린다.
_SECTION_RE = re.compile(r"[【\[]\s*(갑|을)\s*구\s*[】\]]")
_DATE_RE = re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
# 권리 말소가 지목한 순위번호. **`_VOID_TARGET_RE`와 따로 둔다** — 갑구와 을구는
# 순위번호가 **각각 1번부터** 시작한다. 갑구 '3번가압류등기말소'를 그쪽 정규식에
# 합치면 을구 3번 근저당이 말소로 지워져 선순위가 과소계상되고, E[Loss]가 줄어
# 위험한 집이 안전해 보인다. 여기서는 (절, 순위번호) 쌍으로만 쓴다.
_RIGHT_VOID_RE = re.compile(r"(\d{1,2}(?:-\d{1,2})?)번\s*\S{1,20}?말소")

# ── 전유부분의 건물의 표시 ────────────────────────────────────────────────────
# 집합건물(아파트·오피스텔·다세대·연립) 등기부에서 **전용면적이 적힌 유일한 절**이다.
# 실물은 '전용면적'이라는 낱말을 찍지 않는다 — 표제부 안 '건물내역' 칸에 조 구조와
# 함께 '철근콘크리트조 25.59㎡'로만 나온다.
#
# 이 절 밖에도 ㎡가 널려 있고, 어느 것을 집어도 전용면적이 아니다:
#   ( 1동의 건물의 표시 )        → 층별 면적 (1층 120.15㎡ …)
#   ( 대지권의 목적인 토지의 표시 ) → 대지면적 (대 250.30㎡)
#   ( 대지권의 표시 )            → 대지권비율 (250.30분의 21.45)
# 절을 자르지 않으면 무엇이 걸리는지가 문서마다 달라지고, 대지면적이 걸리면 시세가
# 통째로 과대추정돼 **LGD가 낮아지고 E[Loss]가 과소평가된다**(함정 6과 같은 방향).
_EXCL_HEAD_RE = re.compile(r"전유부분의?\s*건물의?\s*표시")
# 다음 절 경계 — 대지권 / 다른 표제부·갑구·을구 / 요약 / 여백.
_EXCL_END_RE = re.compile(r"대지권|【|갑\s*구|을\s*구|주요\s*등기사항|이\s*하\s*여\s*백")
# 건물번호 '제3층 제301호'. 지하는 '제지하1층'·'제B1층'으로 찍힌다.
_UNIT_RE = re.compile(r"제\s*((?:지하\s*)?B?\d+)\s*층\s*제\s*([0-9A-Za-z가-힣]+(?:-\d+)?)\s*호")
# 절 안의 면적. ㎡를 요구하지 않는다 — OCR이 ㎡를 숫자로 읽어 떨구기 때문(함정 12).
# 대신 2자리에서 끊어 그 잡음을 자른다.
_SECTION_AREA_RE = re.compile(r"([\d,]+\.\d{1,2})")
# 층별 면적표. 라벨과 면적이 표 셀에서 줄이 나뉘므로 사이에 숫자 없는 24자를 허용한다
# ('1층 단독주택(다중주택)' 다음 줄에 '106.53㎡', '옥탑1층' 다음 줄에 '7.44㎡' — 둘 다 실측).
_FLOOR_AREA_RE = re.compile(r"(지하?\d+층|옥탑\d*층|\d+층)[^\d]{0,24}([\d,]+\.\d{1,2})\s*㎡")
# '(연면적제외)'가 붙은 면적은 주거 층이 아니다(옥탑·계단실) — 후보에서 뺀다.
_EXCLUDED_AREA_RE = re.compile(r"([\d,]+\.\d{1,2})\s*㎡\s*\(?\s*연면적\s*제외")
# 말소·변경 전 기록. 취소선은 도형이라 텍스트엔 안 남으므로(→ _page_text) 문구로도 건다.
_VOID_LINE_RE = re.compile(r"말소|삭제|취소|변경\s*전")


def _exclusive_part(text: str) -> dict:
    """'전유부분의 건물의 표시' 절만 잘라 층·호수·건물내역 면적을 읽는다.

    절이 없으면 `{}` — 건물 등기부(단독·다가구·다중)엔 이 절이 아예 없다.

    대지권·대지면적·공유지분·갑구·을구를 골라내는 처리는 두지 않는다 — 절 경계
    밖은 애초에 읽지 않는다. 말소분만 따로 빠진다: 취소선(빨간 줄)이 그어진 단어는
    `_page_text`가 텍스트 조립에서 이미 빼고, 여기서는 '…말소'라고 **적힌** 줄을 뺀다.

    **절 안에서 면적 후보가 2개 이상이면 값을 내지 않는다.** 면적변경 기록이 섞인
    경우이고, 최신처럼 보이는 쪽을 고르는 건 추측이다(CLAUDE.md 원칙 5).
    """
    head = _EXCL_HEAD_RE.search(text)
    if not head:
        return {}
    section = text[head.end() :]
    end = _EXCL_END_RE.search(section)
    if end:
        section = section[: end.start()]
    section = "\n".join(ln for ln in section.splitlines() if not _VOID_LINE_RE.search(ln))

    # 층·호수는 표제부 상단 '[집합건물] … 제3층 제301호'에도 같은 값이 찍힌다 —
    # 절 안이 OCR로 깨졌을 때의 폴백. 면적은 폴백하지 않는다(절 밖의 ㎡는 다른 면적).
    unit = _UNIT_RE.search(section) or _UNIT_RE.search(text)
    out = {}
    if unit:
        out["floor"] = unit.group(1).replace(" ", "")
        out["unit"] = unit.group(2)
    # 3~1000㎡ 밖은 면적이 아니다. 날짜를 점으로 찍는 판본('2005.5.6' → 2005.5)이나 OCR
    # 잡음이 후보로 끼면 "면적이 2개"가 돼 자동추출이 조용히 실패한다.
    areas = sorted(
        v for v in {float(x.replace(",", "")) for x in _SECTION_AREA_RE.findall(section)}
        if 3 <= v <= 1000
    )
    if len(areas) == 1:
        out["exclusive_area_m2"] = areas[0]
    elif len(areas) > 1:
        shown = ", ".join(f"{a}㎡" for a in areas[:4])
        out["area_note"] = (
            f"전유부분의 건물내역에 면적이 {len(areas)}개 나온다({shown}) — 면적변경 기록이 "
            "섞인 것으로 보인다. 어느 쪽이 현재 유효한지 문서만으로 정할 수 없어 "
            "계약서의 전용면적을 직접 입력해야 한다."
        )
    else:
        out["area_note"] = (
            "전유부분의 건물 표시는 찾았지만 건물내역의 면적을 읽지 못했다 — "
            "계약서의 전용면적을 직접 입력해야 한다."
        )
    return out


class NoTextLayer(ValueError):
    """텍스트 레이어가 없는(스캔) PDF."""


def extract_senior_claims(text: str) -> dict:
    """등기부 텍스트 → 선순위 채권최고액 합계. E[Loss]의 입력을 자동 채우는 편의 기능.

    반환 `senior_claims_krw`: 합계(원) | None(읽지 못함). **0과 None은 다르다** —
    0은 "근저당 없음"이라는 정보이고 None은 "확인 못 함"이다. 화면이 이 둘을
    같게 다루면, 못 읽은 매물이 안전한 매물로 보인다.

    **본문(을구)만 센다.** 대법원 발급본은 끝에 '주요 등기사항 요약(참고용)' 절을
    붙이고 거기서 을구의 유효 근저당을 그대로 되풀이한다. 문서 전체를 훑으면 2배가
    되고, 그러면 engine.lgd의 회수 예상액이 0으로 깎여 LGD가 1.0에 고정된다
    (실측: E[Loss] 348만 → 660만원/년). 요약만 있는 발급본은 거기서라도 읽는다.

    **말소된 근저당은 뺀다.** 이미 말소된 근저당은 담보 부담이 아니므로 선순위에
    넣으면 E[Loss]가 부풀고 전세가 실제보다 나빠 보인다. 근거는 문서에 있다 —
    말소 등기 행이 대상 순위번호를 적는다('1번근저당권설정등기말소'). 문서가 스스로
    말하는 것만 배제하므로 지어내는 판단이 아니다. 취소선(도형)만 남은 말소는
    `_page_text`가 텍스트 조립 단계에서 먼저 걷어낸다.

    한계: 순위번호도 취소선도 없이 말소된 경우는 여전히 못 잡는다. '말소사항 포함'
    증명서면 `includes_cancelled`로 신고해 사용자 확인 게이트에 걸린다.
    """
    if not text.strip():
        return {"senior_claims_krw": None, "senior_claims_count": 0, "includes_cancelled": False,
                "cancelled_claims_krw": 0, "cancelled_claims_count": 0}
    marker = _SUMMARY_RE.search(text)
    body, summary = (text[: marker.start()], text[marker.start() :]) if marker else (text, "")
    amounts = [int(m.replace(",", "")) for m in _CLAIM_RE.findall(body)]
    # 말소분은 본문에서만 뺀다 — 요약 절은 애초에 말소되지 않은 사항만 싣는다.
    dead = _cancelled_amounts(body) if amounts else []
    if not amounts and summary:
        amounts = [int(m.replace(",", "")) for m in _CLAIM_RE.findall(summary)]
    return {
        "senior_claims_krw": sum(amounts) - sum(dead),
        "senior_claims_count": len(amounts) - len(dead),
        "cancelled_claims_krw": sum(dead),
        "cancelled_claims_count": len(dead),
        "includes_cancelled": bool(_CANCELLED_RE.search(text)),
    }


def _cancelled_amounts(body: str) -> list[int]:
    """말소된 근저당의 채권최고액 목록 — 말소 등기가 지목한 순위번호로 짚는다.

    행은 여러 줄에 걸친다(순위번호는 첫 줄에만, 채권최고액은 그 아래 줄일 수 있다).
    그래서 마지막으로 본 순위번호를 이어서 쓴다.

    **이 함수는 오직 뺄 것만 찾는다.** 합계의 출처는 본문 전체 findall이므로, 여기서
    한 건을 못 짚어도 그 근저당은 계속 합산된다(과대 방향 = 안전 방향). 반대로 이
    함수가 오탐하면 유효 근저당이 사라져 **위험이 과소평가된다** — 그래서 순위번호
    패턴을 좁게 잡는다.
    """
    voided = set(_VOID_TARGET_RE.findall(body))
    if not voided:
        return []
    out: list[int] = []
    rank = None
    for ln in body.splitlines():
        head = _RANK_LINE_RE.match(ln)
        if head:
            rank = head.group(1)
        if rank in voided:
            out += [int(m.replace(",", "")) for m in _CLAIM_RE.findall(ln)]
    return out


@lru_cache(maxsize=1)
def _rights_rules() -> tuple:
    """룰 JSON의 권리 항목 → (항목, 컴파일된 패턴) 튜플. 패턴은 데이터다(원칙 3)."""
    return tuple(
        (item, re.compile(item["pattern"])) for item in load_rules("register_risk")["items"]
    )


def extract_rights(text: str) -> list[dict]:
    """등기부 텍스트 → 갑구·을구에 **적힌** 권리 제한 목록. 등급은 매기지 않는다.

    판정은 `l3.register_risk.grade_register`가 룰 테이블로 한다 — 여기는 문서에
    무엇이 적혀 있는지만 낸다(CLAUDE.md 원칙 1).

    **본문만 훑는다.** '주요 등기사항 요약(참고용)' 절은 을구 항목을 그대로
    되풀이하므로 같이 세면 2배가 된다(채권최고액이 밟은 함정 4와 같은 자리).

    말소는 세 겹으로 뺀다:
      1. 취소선(도형)이 그어진 단어는 `_page_text`가 텍스트 조립에서 이미 뺐다
      2. '…말소'가 적힌 줄 자체는 세지 않는다 — 그 문구는 말소를 **집행한** 행에
         붙는다. 그 줄에서는 대상 순위번호만 꺼낸다
      3. 지목된 (절, 순위번호)의 항목은 `cancelled=True`로 남긴다. 지우지는
         않는다 — 원문에 있는 것은 숨기지 않는다(display.citation_label과 같은 자세)

    순위번호·접수일을 못 붙여도 항목은 버리지 않는다. 인용은 `quote`(원문 줄)가
    이미 하고 있고, 버리는 쪽이 **위험이 조용히 사라지는** 방향이다.
    """
    marker = _SUMMARY_RE.search(text)
    body = text[: marker.start()] if marker else text
    section = rank = None
    voided: set[tuple] = set()
    found: dict[tuple, dict] = {}
    for line in body.splitlines():
        sec = _SECTION_RE.search(line)
        if sec:
            section = sec.group(1) + "구"
        head = _RANK_LINE_RE.match(line)
        if head:
            rank = head.group(1)
        if "말소" in line:
            void = _RIGHT_VOID_RE.search(line)
            if void:
                voided.add((section, void.group(1)))
            continue
        date = _DATE_RE.search(line)
        for item, pattern in _rights_rules():
            if not pattern.search(line):
                continue
            found.setdefault(
                (section, rank, item["key"]),
                {
                    "key": item["key"],
                    "section": section or item["section"],
                    "rank": rank,
                    "date": (
                        f"{date.group(1)}-{int(date.group(2)):02d}-{int(date.group(3)):02d}"
                        if date
                        else None
                    ),
                    "quote": " ".join(line.split())[:80],
                    "grade": item["grade"],
                    "why": item["why"],
                    "action": item["action"],
                    "cancelled": False,
                },
            )
    for (sec_key, rank_key, _), entry in found.items():
        entry["cancelled"] = (sec_key, rank_key) in voided
    return list(found.values())


def _extract_area(text: str, excl: dict, use: str | None = None) -> tuple[float | None, str | None]:
    """등기부 텍스트 → (전용면적, 미확정 사유). **후보가 여러 개면 단정하지 않는다.**

    순서가 곧 신뢰도다:
      1) 전유부분의 건물내역 면적 — 집합건물에서 이게 정의상 전용면적이다
      2) '전용면적' 키워드 — 이름이 스스로 무엇인지 말한다
      3) 문서 전체 ㎡ 후보가 딱 1개
      4) None + 사유 (수동 입력)
    3은 전유부분 절이 있는 문서에선 타지 않는다 — 그 절이 있는데 면적을 못 정했다면
    문서 전체에서 고르는 건 대지면적·층별면적을 집을 위험뿐이다.

    집합건물(아파트·오피스텔·다세대)은 전유부분 면적이 하나라 그대로 쓴다.
    건물 등기부(단독·다가구·다중)는 층별 면적이 여러 줄 나온다 — 여기서 첫 매치를
    집으면 **1층 면적을 전용면적이라 부르게 된다**. 예외도 None도 나지 않고 그럴듯한
    숫자만 나오므로 눈으로는 못 잡는다(실측: 3층 다중주택에서 106.53㎡를 집어
    시세를 4.83억으로 추정 — 원룸 25㎡ 기준 1.13억의 4.3배. 시세 과대 →
    LGD 과소 → **E[Loss]가 과소평가되어 위험한 집이 안전해 보인다**).

    게다가 다중·다가구주택 임차인은 층이 아니라 **방**을 빌리므로, 층별 면적 중
    무엇을 골라도 전용면적이 아니다. 후보를 보여주는 것조차 오답을 유도한다 —
    그래서 None + 사유만 남기고 수동 입력을 요구한다(CLAUDE.md 원칙 5).

    **여기서 예외를 던지지 않는다.** 면적은 등기부의 여러 필드 중 하나일 뿐인데,
    예전엔 못 찾으면 ValueError로 올려 호출측이 OCR 폴백을 타게 했다. 그 결과
    OCR을 이미 돌린 뒤에도 같은 예외가 나면 **멀쩡히 읽은 채권최고액·주소까지
    통째로 버리고 422**가 됐다(실측: 건물 등기부 촬영본이 전부 수동 입력으로 떨어짐).
    건물 등기부는 면적이 없는 게 정상이다. OCR을 탈지 말지는 "이 텍스트에서
    아무것도 못 건졌는가"로 판단해야지 면적 하나로 정할 일이 아니다.
    """
    if excl.get("exclusive_area_m2"):  # 전유부분의 건물내역 — 정의상 이게 전용면적이다
        return excl["exclusive_area_m2"], None
    keyed = _AREA_RE.search(text)
    if keyed:  # '전용면적 59.94' — 키워드가 붙었으면 그게 답이다
        return float(keyed.group(1).replace(",", "")), None
    if excl:  # 전유부분 절은 있는데 면적을 못 정했다 — 절 밖에서 고르면 다른 면적이다
        return None, excl["area_note"]

    # 같은 층 목록이 두 번 나올 수 있다 — 표제부에 표시번호 1·2가 함께 실린다(도로명주소
    # 추가 등). 순서를 지키며 중복만 걷어낸다.
    floors = list(dict.fromkeys(_FLOOR_AREA_RE.findall(text)))
    dropped = {float(x.replace(",", "")) for x in _EXCLUDED_AREA_RE.findall(text)}
    cands = sorted({float(x.replace(",", "")) for x in _AREA_FALLBACK_RE.findall(text)} - dropped)
    if not cands:
        return None, "전용면적을 찾지 못했다 — 계약서를 보고 직접 입력해야 한다."
    # 층별 면적표가 있으면 후보가 1개로 보여도 전용면적이 아니다. **같은 면적의 층이
    # 반복되면 집합(set)에서 하나로 합쳐진다** — 실측 문서가 1·2·3층 모두 45.29㎡였고,
    # 지1층·옥탑이 없었다면 후보가 45.29 하나가 돼 그게 전용면적으로 자동채움됐다.
    # 개수로 판단하면 이 경로가 조용히 열린다(함정 6이 되돌아오는 방향).
    rents_a_room = bool(use and ("다중" in use or "다가구" in use))
    if len(cands) == 1 and not floors and not rents_a_room:
        return cands[0], None
    if floors:
        shown = ", ".join(
            f"{f} {a}㎡" + ("(연면적제외)" if float(a.replace(",", "")) in dropped else "")
            for f, a in floors[:6]
        ) + ("…" if len(floors) > 6 else "")
        head = f"이 등기부엔 층별 면적만 있다({shown})."
    else:
        shown = ", ".join(f"{c}㎡" for c in cands[:4]) + ("…" if len(cands) > 4 else "")
        head = f"면적이 {len(cands)}개 나온다({shown})."
    why = (
        "다중·다가구주택 임차인은 층이 아니라 방을 빌리므로, 층 면적은 전용면적이 아니다. "
        if rents_a_room or len(floors) > 1
        else "어느 것이 전용면적인지 문서만으로 정할 수 없다. "
    )
    return None, head + " " + why + "계약서의 전용면적을 직접 입력해야 시세·기대손실이 계산된다."


def register_limits(text: str, building_use: str | None) -> list[str]:
    """이 문서로는 **볼 수 없는** 위험을 문장으로 남긴다.

    조용히 넘어가면 사용자는 "등기부가 깨끗하니 안전하다"로 읽는다. 실제로는
    위험이 문서 밖에 있다 — 토지 등기부의 근저당, 다른 세입자의 선순위 보증금.
    """
    out = []
    kind = _KIND_RE.search(text)
    if kind and kind.group(1) == "건물":
        out.append(
            "건물 등기부다 — 단독·다가구·다중주택은 토지 등기부가 별도이고, "
            "토지에 걸린 근저당은 이 문서에 나오지 않는다. 토지 등기부도 떼어봐야 "
            "선순위 합계가 맞는다."
        )
    if _JOINT_RE.search(text):
        out.append(
            "공동담보로 설정된 근저당이 있다 — 채권최고액이 토지와 건물에 함께 걸려 "
            "있어서 이 건물만의 부담이 아니다. 경매 회수액 추정이 달라진다."
        )
    if building_use and ("다중" in building_use or "다가구" in building_use):
        out.append(
            "다중·다가구주택은 다른 세입자의 보증금이 선순위다. 등기부에 나오지 "
            "않으므로 주민센터에서 '확정일자 부여현황'을 떼어 확인해야 한다 — "
            "이 항목이 빠지면 미회수 위험이 크게 과소평가된다."
        )
    return out


def is_useless(fields: dict) -> bool:
    """이 텍스트에서 **아무것도 못 건졌는가** — OCR 폴백을 탈지의 판단 기준.

    주소도 없고 근저당도 없고 면적도 없으면 텍스트 레이어가 표지뿐이거나 깨진
    것이다. 하나라도 건졌으면 OCR을 또 돌릴 이유가 없다(수 초가 그냥 나간다).
    """
    return not any((fields.get("sigungu"), fields.get("senior_claims_count"),
                    fields.get("exclusive_area_m2")))


def extract_fields(text: str) -> dict:
    """등기부 텍스트 → 필드. **예외를 던지지 않는다** — 못 읽은 항목은 None + 사유.

    "읽지 못함"을 예외로 올리면 한 필드 실패가 문서 전체를 버린다. 호출측은
    is_useless()로 OCR 폴백 여부를 판단한다.
    """
    excl = _exclusive_part(text)
    use_m = _SPECIFIC_USE_RE.search(text) or _USE_RE.search(text)
    use_val = use_m.group(1) if use_m else None
    # 용도를 면적보다 먼저 읽는다 — 다중·다가구면 층 면적을 전용면적으로 쓸 수 없다.
    area_val, area_note = _extract_area(text, excl, use_val)
    sido = _SIDO_RE.search(text)
    sido_val = sido.group(1) if sido else None
    # 시군구: '시/군/구' 토큰 중 sido(예: 서울특별시)와 겹치지 않는 첫 번째
    sigungu_val = next((t for t in _SIGUNGU_RE.findall(text) if t != sido_val), None)
    road = _ROAD_RE.search(text)
    # 동은 시군구 '뒤'에서 찾는다 — '성동구'의 '동' 오매칭 방지
    after = text.find(sigungu_val) + len(sigungu_val) if sigungu_val and sigungu_val in text else 0
    dong_m = _DONG_RE.search(text, after)
    dong_val = dong_m.group(0) if dong_m else None
    jibun_m = _JIBUN_RE.search(text, dong_m.end()) if dong_m else None
    jibun_val = jibun_m.group(0) if jibun_m else None
    kind_m = _KIND_RE.search(text)
    claims = extract_senior_claims(text)
    warnings = register_limits(text, use_val)
    if claims["cancelled_claims_count"]:
        # 조용히 줄어든 선순위는 사용자가 문서와 대조할 때 이유를 알 수 없다.
        # 금액은 여기서 포맷하지 않는다 — 만원 변환은 표시 계층 몫(cancelled_claims_krw).
        warnings.append(
            f"말소된 근저당 {claims['cancelled_claims_count']}건은 선순위 합계에서 제외했다 — "
            "문서에 '…번근저당권설정등기말소'로 적혀 있다. 이미 말소된 근저당은 담보 "
            "부담이 아니므로 넣으면 기대손실이 부풀려진다."
        )
    return {
        # 층·호수 — 전유부분의 건물번호. 문자열이다('지하1'·'B1'이 있어서 int로 못 눌린다)
        "floor": excl.get("floor"),
        "unit": excl.get("unit"),
        "sido": sido_val,
        "sigungu": sigungu_val,
        "dong": dong_val,
        "jibun": jibun_val,
        # 표 셀에서 줄이 나뉘므로 공백을 한 칸으로 눌러 붙인다
        "road_addr": " ".join(road.group(1).split()) if road else None,
        "exclusive_area_m2": area_val,  # None 가능 — area_note에 사유가 있다
        "area_note": area_note,
        "building_use": use_val,
        "register_kind": kind_m.group(1) if kind_m else None,
        "warnings": warnings,
        # 갑구·을구에 적힌 권리 제한. 등급은 l3.register_risk가 매긴다(원칙 1).
        "rights": extract_rights(text),
        **claims,
    }


# 렌더 배율. 1 = 72 DPI이므로 3 = 216 DPI.
#
# 2에서 3으로 올린 근거(합성 촬영본 실측 — 흐림·기울기·그림자·JPEG 압축 조합):
#   흐림1.4·기울기2.5·JPEG60에서 scale=2는 **채권최고액을 통째로 놓쳤고**(None)
#   scale=3은 읽었다. 비용은 페이지당 약 +0.3초.
# 4는 올리지 않는다 — 깨끗한 스캔에서 오히려 면적을 놓쳤다(과확대 아티팩트).
# lang은 'kor' 유지: 'kor+eng'가 30% 느린데 실측에서 금액 정확도 이득이 없었다.
_OCR_SCALE = 3


def _ocr_pages(path, max_pages: int = 5) -> str:
    """스캔 PDF → 이미지 렌더(pypdfium2) → Tesseract OCR(kor). 무료·로컬.

    회색조로 넘긴다 — 등기부는 흑백 문서라 색 정보가 없고, 촬영본의 색 노이즈만 줄어든다.

    tesseract 바이너리/kor 데이터/pytesseract 미설치면 예외 → 호출측이 NoTextLayer로 폴백.
    """
    import pypdfium2 as pdfium
    import pytesseract

    doc = pdfium.PdfDocument(path)
    parts = []
    for i in range(min(len(doc), max_pages)):
        img = doc[i].render(scale=_OCR_SCALE).to_pil().convert("L")
        parts.append(pytesseract.image_to_string(img, lang="kor"))
    return "\n".join(parts)


def _struck(word, hlines) -> bool:
    """이 단어에 취소선이 그어져 있는가 — 말소된 기록이다.

    글자 높이의 중간 40% 안을 지나는 수평선만 취소선으로 본다. 표 괘선은 셀의
    위·아래 경계에 있어서 이 띠 밖이다. x가 절반 이상 겹칠 것도 요구한다 —
    셀 경계선의 끝점이 글자에 스치는 것까지 말소로 세면 유효 기록이 지워진다.
    """
    h = word["bottom"] - word["top"]
    lo, hi = word["top"] + 0.3 * h, word["bottom"] - 0.3 * h
    w = word["x1"] - word["x0"]
    return any(
        lo <= ln["top"] <= hi
        and min(ln["x1"], word["x1"]) - max(ln["x0"], word["x0"]) >= 0.5 * w
        for ln in hlines
    )


def _page_text(page) -> tuple[str, int]:
    """페이지 텍스트 — **취소선이 그어진 단어는 뺀다**(말소된 기록).

    텍스트 레이어에는 취소선이 남지 않으므로, 말소된 근저당의 채권최고액이 유효한
    것과 똑같은 문자열로 섞여 들어온다. 그러면 선순위 합계가 과대계상돼 E[Loss]가
    부풀고, 안전한 집이 위험해 보인다(반대 방향의 오답도 같은 크기의 오답이다).
    말소 여부는 문구로 판단할 수 없다 — '…말소' 문구는 말소를 **집행한** 다른 행에
    붙고, 말소된 행 자체엔 취소선만 남는다. 그래서 도형(선)으로 판단한다.

    취소선이 없는 문서에서는 `extract_text()`를 그대로 쓴다 — 단어를 다시 조립하면
    pdfplumber의 줄·간격 판단이 달라져서 기존 경로가 흔들린다. 새 경로는 필요한
    문서에서만 켠다.

    두 번째 반환값은 **실선이 지나간 줄 수**다. 실물 등기부는 각주에 "실선으로 그어진
    부분은 말소사항을 표시함"이라 적어두고, 말소된 근저당뿐 아니라 **변경 전 채무자·
    근저당권자·주소**에도 같은 실선을 쓴다(실측: 노원구 공릉동 559-22에서 17줄, 그 문서의
    채권최고액 2건은 실선이 없어 유효했다). 그래서 이 수는 "말소된 근저당 건수"가 아니라
    "빼고 읽은 줄 수"다 — 화면이 둘을 섞으면 유효한 근저당을 말소로 오해하게 만든다.
    """
    # rects도 본다 — 취소선을 선이 아니라 납작한 사각형으로 칠하는 생성기가 있다.
    hlines = [ln for ln in page.lines + page.rects if abs(ln["bottom"] - ln["top"]) <= 1.5]
    if not hlines:
        return page.extract_text() or "", 0
    rows: dict[int, list] = {}
    struck_rows = set()
    for w in page.extract_words():
        row = round(w["top"] / 3)  # 같은 줄로 묶는다(3pt) — 표 셀이 줄바꿈돼도 원래와 같은 모양
        if _struck(w, hlines):
            struck_rows.add(row)
        else:
            rows.setdefault(row, []).append(w)
    if not struck_rows:
        return page.extract_text() or "", 0
    text = "\n".join(
        " ".join(w["text"] for w in sorted(r, key=lambda w: w["x0"]))
        for _, r in sorted(rows.items())
    )
    return text, len(struck_rows)


def parse_register_pdf(path) -> dict:
    """PDF 텍스트 추출 후 필드 파싱. 텍스트 레이어 없으면 무료 OCR 폴백(있을 때만).

    OCR 결과는 저신뢰라 dict에 ocr=True를 달아 반환 — 호출측/화면이 사용자 확인을 받아야 한다.
    OCR도 불가/실패하면 NoTextLayer(수동 입력 폴백).
    """
    with pdfplumber.open(path) as pdf:
        pages = [_page_text(page) for page in pdf.pages]
    text = "\n".join(t for t, _ in pages)
    if text.strip():
        fields = extract_fields(text)
        if not is_useless(fields):
            # 실선(말소 표시)을 몇 줄 빼고 읽었는지 알려준다 — 화면이 "말소사항 포함이라
            # 선순위가 클 수 있다"는 경고를 계속 띄울지 판단하는 근거다.
            return {**fields, "struck_rows": sum(n for _, n in pages)}
        # 표지만 디지털이거나 텍스트 레이어가 깨진 경우 → OCR 폴백

    # 텍스트 레이어 없음 OR 아무것도 못 건짐 → 무료 OCR 폴백
    try:
        ocr_text = _ocr_pages(path)
    except Exception as exc:  # tesseract 미설치 등
        raise NoTextLayer("텍스트 레이어 없음/부족 + OCR 불가(tesseract 미설치?) — 수동 입력") from exc
    if not ocr_text.strip():
        raise NoTextLayer("텍스트·OCR 모두 실패 — 수동 입력")
    fields = extract_fields(ocr_text)
    if is_useless(fields):
        raise NoTextLayer("OCR은 됐으나 주소·근저당·면적을 하나도 읽지 못했다 — 수동 입력")
    # OCR 값은 저신뢰다. 특히 채권최고액은 한 자리만 틀려도 E[Loss]가 통째로 어긋나므로
    # 화면이 반드시 사용자 확인을 받아야 한다(ocr=True가 그 신호).
    return {**fields, "ocr": True}
