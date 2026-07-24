"""서울 25개 구 fake 등기부등본 PDF 생성기(텍스트 레이어 O — 파서가 읽을 수 있음).

실제 등기부 양식을 따르되 내용은 합성. 업로드 데모/파서 검증용.
reportlab 내장 한글 CID 폰트 사용(외부 폰트 불필요). faker 미사용 — 서울 구·동을
직접 통제해야 해서 랜덤주소가 무용하고, 이름 몇 개는 stdlib random이 더 간단.

사용: .venv/bin/python scripts/gen_fake_registers.py  → data/fixtures/fake_registers/*.pdf
"""
import os
import random

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

# 구 → 대표 법정동(현실감용)
GU_DONG = {
    "종로구": "청운동", "중구": "회현동", "용산구": "이태원동", "성동구": "성수동",
    "광진구": "자양동", "동대문구": "전농동", "중랑구": "면목동", "성북구": "정릉동",
    "강북구": "미아동", "도봉구": "창동", "노원구": "상계동", "은평구": "불광동",
    "서대문구": "홍제동", "마포구": "서교동", "양천구": "목동", "강서구": "화곡동",
    "구로구": "구로동", "금천구": "시흥동", "영등포구": "당산동", "동작구": "사당동",
    "관악구": "봉천동", "서초구": "방배동", "강남구": "역삼동", "송파구": "잠실동",
    "강동구": "천호동",
}
TYPES = ["아파트", "연립주택", "다세대주택", "오피스텔"]  # 모두 building_type_for_use 매핑됨
SURNAMES = "김이박최정강조윤장임한오서신"
GIVEN = ["서연", "민준", "지우", "하은", "도윤", "예은", "시우", "수아", "지호", "유진"]


def make_pdf(path, gu, dong, btype):
    r = random
    jibun = f"{r.randint(100, 999)}-{r.randint(1, 30)}"
    area = round(r.uniform(29, 84), 2)
    owner = r.choice(SURNAMES) + r.choice(GIVEN)
    amount = r.randint(8, 25) * 10_000_000  # 채권최고액
    lines = [
        "등기사항전부증명서(현재 유효사항)  - 건물 -",
        f"고유번호 1101-2020-{r.randint(100000, 999999)}",
        f"[건물] 서울특별시 {gu} {dong} {jibun}",
        "【 표 제 부 】 ( 건물의 표시 )",
        f"서울특별시 {gu} {dong} {jibun}",
        f"[도로명주소] 서울특별시 {gu} {dong[:-1]}로 {r.randint(1, 99)}",
        f"철근콘크리트조 {btype}",
        f"전용면적 {area}㎡",
        "【 갑 구 】 ( 소유권에 관한 사항 )",
        f"1  소유권보존   소유자 {owner}   서울특별시 {gu} {dong} {jibun}",
        "【 을 구 】 ( 소유권 이외의 권리에 관한 사항 )",
        f"1  근저당권설정   채권최고액 금{amount:,}원   근저당권자 국민은행",
        "-- 이 하 여 백 --",
    ]
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("HYSMyeongJo-Medium", 10.5)
    y = 800
    for ln in lines:
        c.drawString(50, y, ln)
        y -= 24
    c.save()


def main():
    pdfmetrics.registerFont(UnicodeCIDFont("HYSMyeongJo-Medium"))
    random.seed(42)  # 재현 가능
    out = "data/fixtures/fake_registers"
    os.makedirs(out, exist_ok=True)
    for i, (gu, dong) in enumerate(GU_DONG.items()):
        btype = TYPES[i % len(TYPES)]
        make_pdf(f"{out}/서울-{gu}-{btype}.pdf", gu, dong, btype)
    print(f"생성 완료: {len(GU_DONG)}개 → {out}/")


if __name__ == "__main__":
    main()
