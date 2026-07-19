"""등기부등본 PDF → 페이지 이미지(PNG bytes) 변환.

pypdfium2(PDFium, BSD/Apache) 사용 — poppler 같은 시스템 의존성이 없어
Streamlit Cloud에서도 pip만으로 동작한다. 이미지는 L1 비전 파싱(LLM) 입력.
"""

from __future__ import annotations

import io


def pdf_to_images(pdf_bytes: bytes, *, max_pages: int = 5, scale: float = 2.0) -> list[bytes]:
    """PDF 바이트 → 페이지별 PNG 바이트 목록 (max_pages 상한, scale=해상도 배율).

    등기부는 보통 2~4쪽 — 상한은 LLM 비용·토큰 보호용.
    """
    import pypdfium2 as pdfium

    try:
        document = pdfium.PdfDocument(pdf_bytes)
    except Exception as exc:
        raise ValueError("PDF를 열 수 없다 — 파일이 손상됐거나 PDF가 아니다") from exc

    images: list[bytes] = []
    try:
        for index, page in enumerate(document):
            if index >= max_pages:
                break
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG")
            images.append(buffer.getvalue())
    finally:
        document.close()
    return images
