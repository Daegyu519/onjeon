"""등기부등본 PDF → 핵심 필드(주소·전용면적·용도) 텍스트 파싱.

비전 LLM 아님. 텍스트 레이어가 없는 스캔본은 NoTextLayer로 신호(유료 OCR 미사용).
"""

from __future__ import annotations

import re

import pdfplumber

# '면적' 키워드가 있으면 우선, 없으면 아무 'N㎡' 숫자로 폴백(실제 등기부는 키워드 생략)
_AREA_RE = re.compile(r"면적\s*([\d,]+\.\d+)\s*㎡")
_AREA_FALLBACK_RE = re.compile(r"([\d,]+\.\d+)\s*㎡")
# 건물용도 — '용도' 키워드 없이 유형명 직접 매칭(실제 양식엔 '다세대주택' 등만 표기)
_USE_RE = re.compile(r"(오피스텔|아파트|연립주택|다세대주택|단독주택|다중주택|주상복합|근린생활시설)")
_SIDO_RE = re.compile(r"(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|"
                      r"울산광역시|세종특별자치시|경기도|강원(?:특별자치)?도|충청북도|충청남도|"
                      r"전라북도|전북특별자치도|전라남도|경상북도|경상남도|제주특별자치도)")
_SIGUNGU_RE = re.compile(r"[가-힣]+(?:시|군|구)")  # findall — sido와 겹치면 제외
_ROAD_RE = re.compile(r"\[도로명주소\]\s*(.+)")
_DONG_RE = re.compile(r"[가-힣]+(?:동|가|리)")  # 법정동(예: 봉천동) — 첫 매치
_JIBUN_RE = re.compile(r"\d+(?:-\d+)?")  # 지번(예: 100-1) — dong 매치 위치 이후에서 검색


class NoTextLayer(ValueError):
    """텍스트 레이어가 없는(스캔) PDF."""


def extract_fields(text: str) -> dict:
    """등기부 텍스트 → 필드. 전용면적은 필수(없으면 ValueError)."""
    area_m = _AREA_RE.search(text) or _AREA_FALLBACK_RE.search(text)
    if not area_m:
        raise ValueError("전용면적을 찾지 못했다 — 등기부 형식 확인 필요")
    sido = _SIDO_RE.search(text)
    sido_val = sido.group(1) if sido else None
    # 시군구: '시/군/구' 토큰 중 sido(예: 서울특별시)와 겹치지 않는 첫 번째
    sigungu_val = next((t for t in _SIGUNGU_RE.findall(text) if t != sido_val), None)
    use = _USE_RE.search(text)
    road = _ROAD_RE.search(text)
    # 동은 시군구 '뒤'에서 찾는다 — '성동구'의 '동' 오매칭 방지
    after = text.find(sigungu_val) + len(sigungu_val) if sigungu_val and sigungu_val in text else 0
    dong_m = _DONG_RE.search(text, after)
    dong_val = dong_m.group(0) if dong_m else None
    jibun_m = _JIBUN_RE.search(text, dong_m.end()) if dong_m else None
    jibun_val = jibun_m.group(0) if jibun_m else None
    return {
        "sido": sido_val,
        "sigungu": sigungu_val,
        "dong": dong_val,
        "jibun": jibun_val,
        "road_addr": road.group(1).strip() if road else None,
        "exclusive_area_m2": float(area_m.group(1).replace(",", "")),
        "building_use": use.group(1) if use else None,
    }


def _ocr_pages(path, max_pages: int = 5) -> str:
    """스캔 PDF → 이미지 렌더(pypdfium2) → Tesseract OCR(kor). 무료·로컬.

    tesseract 바이너리/kor 데이터/pytesseract 미설치면 예외 → 호출측이 NoTextLayer로 폴백.
    """
    import pypdfium2 as pdfium
    import pytesseract

    doc = pdfium.PdfDocument(path)
    parts = []
    for i in range(min(len(doc), max_pages)):
        img = doc[i].render(scale=2).to_pil()
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
        return extract_fields(text)

    try:
        ocr_text = _ocr_pages(path)
    except Exception as exc:  # tesseract 미설치 등
        raise NoTextLayer("텍스트 레이어 없음 + OCR 불가(tesseract 미설치?) — 수동 입력") from exc
    if not ocr_text.strip():
        raise NoTextLayer("텍스트·OCR 모두 실패 — 수동 입력")
    try:
        return {**extract_fields(ocr_text), "ocr": True}
    except ValueError as exc:
        raise NoTextLayer(f"OCR은 됐으나 필드 추출 실패 — 수동 입력({exc})") from exc
