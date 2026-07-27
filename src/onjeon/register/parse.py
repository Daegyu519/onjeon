"""등기부등본 PDF → 핵심 필드(주소·전용면적·용도) 텍스트 파싱.

비전 LLM 아님. 텍스트 레이어가 없는 스캔본은 NoTextLayer로 신호(유료 OCR 미사용).
"""

from __future__ import annotations

import re

import pdfplumber

# '면적' 키워드 있으면 우선(㎡는 OCR이 떨구므로 불요구), 없으면 'N㎡' 숫자로 폴백.
#
# **소수 2자리로 끊는다.** 오른쪽 앵커가 없으면 OCR이 ㎡를 숫자로 읽어 뒤에 자릿수를
# 덧붙인다 — 실측으로 70.94가 70.941 / 70.940 / 70.9407로 나왔다. 등기부 면적은 항상
# 2자리이므로 딱 2자리만 취하면 그 잡음이 잘려나가고 원값이 복구된다.
# 1자리 표기(35.3㎡)는 여기서 안 걸리고 아래 ㎡ 앵커가 붙은 폴백이 받는다.
_AREA_RE = re.compile(r"면적\s*([\d,]+\.\d{2})")
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
# 대법원 인터넷등기소 발급본 끝에 붙는 '주요 등기사항 요약(참고용)' 절.
# 을구의 유효 근저당을 그대로 되풀이하므로 문서 전체를 훑으면 2배로 센다.
_SUMMARY_RE = re.compile(r"주요\s*등기사항\s*요약")


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

    한계: 텍스트 레이어에는 취소선이 없어서 말소된 근저당을 구분할 수 없다.
    '말소사항 포함' 증명서면 `includes_cancelled`로 신고만 하고 합계는 보정하지
    않는다(없는 판단을 지어내지 않는다 — CLAUDE.md 원칙 5). 값은 항상 사용자
    확인 게이트를 거쳐 적용된다.
    """
    if not text.strip():
        return {"senior_claims_krw": None, "senior_claims_count": 0, "includes_cancelled": False}
    marker = _SUMMARY_RE.search(text)
    body, summary = (text[: marker.start()], text[marker.start() :]) if marker else (text, "")
    amounts = [int(m.replace(",", "")) for m in _CLAIM_RE.findall(body)]
    if not amounts and summary:
        amounts = [int(m.replace(",", "")) for m in _CLAIM_RE.findall(summary)]
    return {
        "senior_claims_krw": sum(amounts),
        "senior_claims_count": len(amounts),
        "includes_cancelled": bool(_CANCELLED_RE.search(text)),
    }


def _extract_area(text: str) -> tuple[float | None, str | None]:
    """등기부 텍스트 → (전용면적, 미확정 사유). **후보가 여러 개면 단정하지 않는다.**

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
    keyed = _AREA_RE.search(text)
    if keyed:  # '전용면적 59.94' — 키워드가 붙었으면 그게 답이다
        return float(keyed.group(1).replace(",", "")), None
    cands = sorted({float(x.replace(",", "")) for x in _AREA_FALLBACK_RE.findall(text)})
    if not cands:
        return None, "전용면적을 찾지 못했다 — 계약서를 보고 직접 입력해야 한다."
    if len(cands) == 1:
        return cands[0], None
    shown = ", ".join(f"{c}㎡" for c in cands[:4]) + ("…" if len(cands) > 4 else "")
    return None, (
        f"면적이 {len(cands)}개 나온다({shown}) — 층별 면적이 적힌 건물 등기부로 보인다. "
        "다중·다가구주택은 층이 아니라 방을 임차하므로 문서만으로 전용면적을 정할 수 없다. "
        "계약서의 전용면적을 직접 입력해야 시세·기대손실이 계산된다."
    )


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
    area_val, area_note = _extract_area(text)
    sido = _SIDO_RE.search(text)
    sido_val = sido.group(1) if sido else None
    # 시군구: '시/군/구' 토큰 중 sido(예: 서울특별시)와 겹치지 않는 첫 번째
    sigungu_val = next((t for t in _SIGUNGU_RE.findall(text) if t != sido_val), None)
    use_m = _SPECIFIC_USE_RE.search(text) or _USE_RE.search(text)
    use_val = use_m.group(1) if use_m else None
    road = _ROAD_RE.search(text)
    # 동은 시군구 '뒤'에서 찾는다 — '성동구'의 '동' 오매칭 방지
    after = text.find(sigungu_val) + len(sigungu_val) if sigungu_val and sigungu_val in text else 0
    dong_m = _DONG_RE.search(text, after)
    dong_val = dong_m.group(0) if dong_m else None
    jibun_m = _JIBUN_RE.search(text, dong_m.end()) if dong_m else None
    jibun_val = jibun_m.group(0) if jibun_m else None
    kind_m = _KIND_RE.search(text)
    return {
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
        "warnings": register_limits(text, use_val),
        **extract_senior_claims(text),
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


def parse_register_pdf(path) -> dict:
    """PDF 텍스트 추출 후 필드 파싱. 텍스트 레이어 없으면 무료 OCR 폴백(있을 때만).

    OCR 결과는 저신뢰라 dict에 ocr=True를 달아 반환 — 호출측/화면이 사용자 확인을 받아야 한다.
    OCR도 불가/실패하면 NoTextLayer(수동 입력 폴백).
    """
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if text.strip():
        fields = extract_fields(text)
        if not is_useless(fields):
            return fields
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
