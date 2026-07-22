"""등기부등본 PDF → 핵심 필드(주소·전용면적·용도) 텍스트 파싱.

비전 LLM 아님. 텍스트 레이어가 없는 스캔본은 NoTextLayer로 신호(유료 OCR 미사용).
"""

from __future__ import annotations

import re

import pdfplumber

_AREA_RE = re.compile(r"면적\s*([\d,]+\.\d+)\s*㎡")
_USE_RE = re.compile(r"용도\s*([가-힣A-Za-z]+)")
_SIDO_RE = re.compile(r"(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|"
                      r"울산광역시|세종특별자치시|경기도|강원(?:특별자치)?도|충청북도|충청남도|"
                      r"전라북도|전북특별자치도|전라남도|경상북도|경상남도|제주특별자치도)")
_SIGUNGU_RE = re.compile(r"[가-힣]+(?:시|군|구)")  # findall — sido와 겹치면 제외
_ROAD_RE = re.compile(r"\[도로명주소\]\s*(.+)")


class NoTextLayer(ValueError):
    """텍스트 레이어가 없는(스캔) PDF."""


def extract_fields(text: str) -> dict:
    """등기부 텍스트 → 필드. 전용면적은 필수(없으면 ValueError)."""
    area_m = _AREA_RE.search(text)
    if not area_m:
        raise ValueError("전용면적을 찾지 못했다 — 등기부 형식 확인 필요")
    sido = _SIDO_RE.search(text)
    sido_val = sido.group(1) if sido else None
    # 시군구: '시/군/구' 토큰 중 sido(예: 서울특별시)와 겹치지 않는 첫 번째
    sigungu_val = next((t for t in _SIGUNGU_RE.findall(text) if t != sido_val), None)
    use = _USE_RE.search(text)
    road = _ROAD_RE.search(text)
    return {
        "sido": sido_val,
        "sigungu": sigungu_val,
        "jibun": None,  # [확인] 지번 상세 파싱은 실물 등기부로 규칙 확정
        "road_addr": road.group(1).strip() if road else None,
        "exclusive_area_m2": float(area_m.group(1).replace(",", "")),
        "building_use": use.group(1) if use else None,
    }


def parse_register_pdf(path) -> dict:
    """PDF 텍스트 추출 후 필드 파싱. 텍스트 없으면 NoTextLayer."""
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if not text.strip():
        raise NoTextLayer("텍스트 레이어 없음(스캔 PDF로 추정) — 수동 입력 필요")
    return extract_fields(text)
