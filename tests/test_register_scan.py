"""스캔·촬영본 등기부 업로드 — OCR 경로 end-to-end.

사용자가 실제로 하는 일은 등기부를 **찍어서 올리는 것**이다. 텍스트 레이어가 있는
PDF만 테스트하면 그 경로는 아무것도 보증하지 않는다.

여기서는 픽스처 PDF를 이미지로 렌더해 텍스트 레이어를 **제거**하고, 조명 그라디언트·
흐림·기울기·JPEG 압축을 입혀 촬영본에 가깝게 만든 뒤 파서에 넣는다. 기대는
"텍스트 레이어로 읽은 값과 같은 값이 나온다"이다.

tesseract(+kor)가 없으면 skip — OCR은 선택 의존성이고 없으면 수동 입력이 폴백이다.
"""

import io
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from onjeon.register.parse import parse_register_pdf

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "data/fixtures/fake_registers"


def _ocr_available() -> bool:
    if not shutil.which("tesseract"):
        return False
    try:
        import pytesseract  # noqa: F401
        import pypdfium2  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    return "kor" in langs.stdout.split()


pytestmark = pytest.mark.skipif(
    not _ocr_available(), reason="tesseract(+kor)/pytesseract/pypdfium2 없음 — OCR은 선택 의존성"
)


def _photograph(src: pathlib.Path) -> bytes:
    """텍스트 레이어를 없앤 촬영본 근사 PDF.

    한쪽이 어두운 조명, 약한 흐림, 1.5도 기울기, JPEG 압축 — 손으로 찍은 등기부의
    전형적인 열화를 모은 것이다. 실물 첨부본(그림자·워터마크·기울기)이 이 형태였다.
    """
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw, ImageFilter

    doc = pdfium.PdfDocument(str(src))
    pages = []
    for i in range(len(doc)):
        img = doc[i].render(scale=2.4).to_pil().convert("L")
        w, h = img.size
        grad = Image.new("L", (w, h))
        draw = ImageDraw.Draw(grad)
        for x in range(w):
            draw.line([(x, 0), (x, h)], fill=int(255 - 90 * (x / w)))
        img = Image.composite(img, Image.new("L", (w, h), 0), grad)
        img = img.point(lambda p: min(255, int(p * 1.15)))
        img = img.filter(ImageFilter.GaussianBlur(0.9))
        img = img.rotate(1.5, resample=Image.BICUBIC, fillcolor=245, expand=True)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=75)
        pages.append(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
    out = io.BytesIO()
    pages[0].save(out, format="PDF", save_all=True, append_images=pages[1:])
    return out.getvalue()


def _parse_as_photo(name: str) -> tuple[dict, dict]:
    """(텍스트 레이어 결과, 촬영본 OCR 결과)."""
    src = FIXTURES / name
    if not src.exists():
        pytest.skip("가짜 등기부 PDF 없음 — scripts/gen_fake_registers.py로 생성")
    truth = parse_register_pdf(str(src))
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(_photograph(src))
        tmp.flush()
        return truth, parse_register_pdf(tmp.name)


class TestPhotographedJiphap:
    """집합건물 촬영본 — 전 필드가 텍스트 레이어와 일치해야 한다."""

    def test_all_fields_survive_photography(self):
        truth, got = _parse_as_photo("서울-강남구-다세대주택.pdf")
        assert got["ocr"] is True  # 저신뢰 표시 — 화면이 사용자 확인을 받아야 한다
        for key in ("senior_claims_krw", "exclusive_area_m2", "building_use", "sigungu", "dong"):
            assert got[key] == truth[key], f"{key}: 텍스트={truth[key]!r} OCR={got[key]!r}"

    def test_claim_amount_exact(self):
        """금액은 한 자리만 틀려도 E[Loss]가 통째로 어긋난다 — 근사 허용 없음."""
        _, got = _parse_as_photo("서울-강남구-다세대주택.pdf")
        assert got["senior_claims_krw"] == 80_000_000


class TestPhotographedBuildingRegister:
    """건물 등기부 촬영본 — 면적이 없어도 나머지를 버리면 안 된다.

    회귀 지점: 예전엔 면적 실패가 ValueError로 올라가 NoTextLayer(422)가 됐고,
    잘 읽힌 채권최고액 1.2억이 통째로 사라져 전부 수동 입력으로 떨어졌다.
    """

    def test_claims_survive_even_though_area_is_undecidable(self):
        truth, got = _parse_as_photo("대전-유성구-다중주택-건물등기부.pdf")
        assert got["senior_claims_krw"] == 120_000_000 == truth["senior_claims_krw"]
        assert got["exclusive_area_m2"] is None
        assert got["area_note"]

    def test_limits_still_reported_from_ocr_text(self):
        _, got = _parse_as_photo("대전-유성구-다중주택-건물등기부.pdf")
        assert any("토지 등기부" in w for w in got["warnings"])

    def test_road_address_survives_bracket_misread(self):
        """OCR이 '[도로명주소]'의 닫는 괄호를 ')'로 읽어도 주소를 잡아야 한다.

        대괄호를 강제했더니 스캔본에서 도로명주소가 통째로 None이 됐다(실측).
        """
        _, got = _parse_as_photo("대전-유성구-다중주택-건물등기부.pdf")
        assert got["road_addr"] == "대전광역시 유성구 대학로75번길 33"
