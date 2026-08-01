"""Finlife(금감원 공시) KB 상품 파싱 + 시중대출 상품/금리 정합성.

네트워크 없이 검증한다 — 인증키는 사용자가 신청해야 나오는데 그때 파싱 버그를
발견하면 늦다(test_bank_rates.py와 같은 이유).

가장 위험한 오작동은 **화면에 보이는 금리와 계산에 쓴 금리가 갈라지는 것**이다.
`market_loan_product.rate`는 화면이 "KB 3.5% × 8,000만원"이라고 말하는 근거고,
`loan_rate_jeonse`는 실제로 곱해지는 값이다. 하나만 고치면 예외도 경고도 없이
화면이 거짓말을 한다 — 룰 JSON을 손대는 순간 여기서 걸린다.
"""

import importlib.util
import json
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "fetch_finlife_rates", _ROOT / "scripts" / "fetch_finlife_rates.py"
)
ffr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ffr)

KB = "0010001"
OTHER = "0010002"


def base(fin_co_no, prdt, name):
    return {"fin_co_no": fin_co_no, "fin_prdt_cd": prdt, "fin_prdt_nm": name,
            "kor_co_nm": "테스트은행", "dcls_month": "202607", "loan_lmt": "한도"}


def opt(fin_co_no, prdt, lo, hi, avg=None, kind="변동금리"):
    return {"fin_co_no": fin_co_no, "fin_prdt_cd": prdt, "lend_rate_type_nm": kind,
            "rpay_type_nm": "분할상환", "lend_rate_min": lo, "lend_rate_max": hi,
            "lend_rate_avg": avg}


class TestCollect:
    def test_joins_options_to_its_own_product(self):
        """상품코드로 묶는다 — 은행이 같아도 다른 상품의 금리를 붙이면 안 된다."""
        got = ffr.collect(
            [base(KB, "P1", "가"), base(KB, "P2", "나")],
            [opt(KB, "P1", "3.0", "4.0"), opt(KB, "P2", "5.0", "6.0")],
            KB,
        )
        by_name = {p["product_name"]: p for p in got}
        assert by_name["가"]["options"][0]["lend_rate_min_pct"] == 3.0
        assert by_name["나"]["options"][0]["lend_rate_min_pct"] == 5.0

    def test_filters_to_requested_bank(self):
        """fin_co_no를 안 거르면 다른 은행 상품이 KB 상품으로 화면에 나간다."""
        got = ffr.collect([base(KB, "P1", "가"), base(OTHER, "P9", "남")],
                          [opt(KB, "P1", "3.0", "4.0"), opt(OTHER, "P9", "9.0", "9.9")], KB)
        assert [p["product_name"] for p in got] == ["가"]
        assert all(o["lend_rate_min_pct"] != 9.0 for p in got for o in p["options"])

    def test_missing_avg_stays_none(self):
        """전월 실적이 없으면 평균이 빈 값으로 온다. 0으로 바꾸면 공짜 대출이 된다."""
        got = ffr.collect([base(KB, "P1", "가")], [opt(KB, "P1", "3.0", "4.0", avg="")], KB)
        assert got[0]["options"][0]["lend_rate_avg_pct"] is None

    def test_all_banks_when_no_filter(self):
        got = ffr.collect([base(KB, "P1", "가"), base(OTHER, "P9", "남")], [], None)
        assert len(got) == 2


class TestRateSpan:
    def test_spans_all_options_ignoring_blanks(self):
        products = ffr.collect(
            [base(KB, "P1", "가"), base(KB, "P2", "나")],
            [opt(KB, "P1", "3.2", "4.1"), opt(KB, "P2", "", ""), opt(KB, "P2", "2.9", "5.5")],
            KB,
        )
        assert ffr.rate_span(products) == (2.9, 5.5)

    def test_empty_is_none_not_zero(self):
        """0.0을 내면 '금리 0%'로 읽힌다 — 없는 것과 공짜는 다르다."""
        assert ffr.rate_span([]) == (None, None)


class TestMarketLoanProductMatchesCalculation:
    """룰 JSON 정합성 — 화면이 대는 금리와 실제로 곱하는 금리가 같아야 한다."""

    @staticmethod
    def _rules():
        path = _ROOT / "src" / "onjeon" / "rules" / "market_params_2026-07.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_displayed_rate_is_the_computed_rate(self):
        mp = self._rules()
        assert mp["market_loan_product"]["rate"] == mp["loan_rate_jeonse"]

    def test_market_average_is_carried_for_contrast(self):
        """KB 단독 금리는 시장평균보다 낮다. 대조값이 빠지면 그 치우침이 안 보인다."""
        p = self._rules()["market_loan_product"]
        assert p["market_avg_rate"] > p["rate"]
        assert p["market_avg_banks"] >= 2

    def test_product_name_is_not_invented(self):
        """정식 상품명은 금감원 공시에서만 온다 — 없으면 None이어야 한다(지어내지 않는다)."""
        p = self._rules()["market_loan_product"]
        assert p["product_name"] is None or p.get("posted")

    def test_rate_matches_measured_kb_source(self):
        """market_params의 KB 금리가 실측 파일(bank_rates)의 국민은행 값과 같아야 한다."""
        path = _ROOT / "src" / "onjeon" / "rules" / "bank_rates_2026-07.json"
        banks = json.loads(path.read_text(encoding="utf-8"))["banks"]
        kb = next(v for k, v in banks.items() if "국민" in k)
        assert self._rules()["market_loan_product"]["rate"] == round(kb["weighted_avg_pct"] / 100, 5)
