"""L1 PDF 입력 테스트 — PDF → 페이지 이미지(PNG) 변환 + 시세 주입 파싱."""

import io
import json

import pytest

from onjeon.l1.parser import parse_register
from onjeon.l1.pdf import pdf_to_images
from onjeon.llm import MockLLM


def make_pdf(pages: int = 1) -> bytes:
    """matplotlib으로 유효한 다중 페이지 PDF 생성 (외부 파일 불필요)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for i in range(pages):
            fig = plt.figure(figsize=(2, 2))
            fig.text(0.5, 0.5, f"page {i + 1}")
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()


class TestPdfToImages:
    def test_renders_each_page_as_png(self):
        images = pdf_to_images(make_pdf(pages=2))
        assert len(images) == 2
        assert all(img.startswith(b"\x89PNG") for img in images)

    def test_max_pages_cap(self):
        images = pdf_to_images(make_pdf(pages=3), max_pages=1)
        assert len(images) == 1

    def test_invalid_bytes_raise_value_error(self):
        with pytest.raises(ValueError):
            pdf_to_images(b"this is not a pdf")


class TestParseWithMarketInjection:
    """실제 LLM은 등기부에서 시세를 알 수 없다 — 시세는 외부(사용자/실거래가 API) 주입."""

    def _llm_doc_without_market(self, load_fixture) -> dict:
        import copy

        doc = copy.deepcopy(load_fixture("register_risky_villa.json"))
        del doc["property"]["market_price_krw"]
        del doc["property"]["price_source"]
        doc.pop("offer", None)
        return doc

    def test_injected_market_price_passes_gate(self, load_fixture):
        doc = self._llm_doc_without_market(load_fixture)
        llm = MockLLM([json.dumps(doc, ensure_ascii=False)])
        result = parse_register(
            [b"img"], llm, market_price_krw=185_000_000, price_queried_at="2026-07-19"
        )
        assert result["property"]["market_price_krw"] == 185_000_000
        assert result["property"]["price_source"]["queried_at"] == "2026-07-19"

    def test_without_injection_llm_omission_still_blocked(self, load_fixture):
        # 주입이 없으면 기존 게이트 규칙 그대로 — 시세 누락 문서는 차단
        from onjeon.l1.schema import ExtractionInvalid

        doc = self._llm_doc_without_market(load_fixture)
        llm = MockLLM([json.dumps(doc, ensure_ascii=False)])
        with pytest.raises(ExtractionInvalid):
            parse_register([b"img"], llm)
