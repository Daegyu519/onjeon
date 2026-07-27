"""HF 은행별 금리 수집 — 파싱·집계 로직.

네트워크 없이 검증한다. API 키는 사용자가 활용신청해야 나오는데, 그때 가서야
파싱 버그를 발견하면 늦다. 응답 형태만 고정해두면 키가 생기는 즉시 돈다.

가장 위험한 오작동은 **단순평균으로 대표값을 내는 것**이다. 취급액이 미미한 은행이
큰 은행과 같은 무게를 가지면 시장 대표금리가 왜곡되고, 그 값이 전세 비용 계산의
`loan_rate_jeonse`로 들어간다.
"""

import importlib.util
import pathlib

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "fetch_bank_rates",
    pathlib.Path(__file__).resolve().parent.parent / "scripts" / "fetch_bank_rates.py",
)
fbr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fbr)


def item(bank, rate, amt, cnt=10, lo=None, hi=None):
    return {"bankNm": bank, "avgLoanRat2": rate, "loanAmt": amt, "cnt": cnt,
            "minLoanRat": lo, "maxLoanRat": hi}


class TestWeightedNotSimpleAverage:
    def test_overall_is_amount_weighted(self):
        """취급액 990억 은행 3.0% + 10억 은행 9.0% → 단순평균 6.0%가 아니라 ~3.06%."""
        got = fbr.summarize([item("가은행", 3.0, 99_000_000_000),
                             item("나은행", 9.0, 1_000_000_000)])
        assert got["overall_weighted_avg_pct"] == pytest.approx(3.06, abs=0.01)

    def test_same_bank_rows_are_merged(self):
        """고객 특성별로 여러 행이 오므로 은행 단위로 합산해야 한다."""
        got = fbr.summarize([item("가은행", 3.0, 50), item("가은행", 5.0, 50)])
        assert list(got["banks"]) == ["가은행"]
        assert got["banks"]["가은행"]["weighted_avg_pct"] == pytest.approx(4.0)
        assert got["banks"]["가은행"]["loan_count"] == 20


class TestRobustParsing:
    def test_comma_separated_numbers(self):
        """공공 API는 금액을 '1,234,567' 문자열로 준다."""
        got = fbr.summarize([item("가은행", "3.5", "1,000,000")])
        assert got["banks"]["가은행"]["loan_amount"] == 1_000_000

    def test_rows_without_rate_are_skipped_not_zeroed(self):
        """금리 없는 행을 0으로 세면 대표금리가 통째로 내려간다."""
        got = fbr.summarize([item("가은행", 3.5, 100), item("나은행", None, 100)])
        assert "나은행" not in got["banks"]
        assert got["overall_weighted_avg_pct"] == pytest.approx(3.5)

    def test_blank_bank_name_ignored(self):
        assert fbr.summarize([item("", 3.5, 100)])["banks"] == {}

    def test_falls_back_to_arithmetic_rate_when_weighted_missing(self):
        got = fbr.summarize([{"bankNm": "가은행", "avgLoanRat": 3.2, "loanAmt": 100, "cnt": 1}])
        assert got["banks"]["가은행"]["weighted_avg_pct"] == pytest.approx(3.2)

    def test_min_max_span_all_rows(self):
        got = fbr.summarize([item("가은행", 3.5, 100, lo=2.9, hi=4.1),
                             item("가은행", 3.7, 100, lo=2.5, hi=5.0)])
        assert got["banks"]["가은행"]["min_pct"] == 2.5
        assert got["banks"]["가은행"]["max_pct"] == 5.0

    def test_empty_input_does_not_crash(self):
        got = fbr.summarize([])
        assert got["banks"] == {} and got["overall_weighted_avg_pct"] is None


class TestNoSilentFailure:
    def test_xml_error_response_raises(self, monkeypatch):
        """포털은 오류를 200 + XML로 준다 — JSON 파싱 실패로 흘리면 원인을 못 찾는다."""
        class FakeResp:
            def read(self): return b"<OpenAPI_ServiceResponse><cmmMsgHeader/>"
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(fbr.urllib.request, "urlopen", lambda *a, **k: FakeResp())
        with pytest.raises(SystemExit, match="XML"):
            fbr.fetch("key", "L1M")

    def test_hf_shape_without_response_wrapper(self, monkeypatch):
        """HF는 {"header","body"}로 주고 MOLIT은 {"response":{...}}로 준다.

        회귀 지점: 한쪽만 가정했더니 200 OK인데 items가 빈 채로 조용히 넘어갔다.
        실측 호출에서 잡았다 — 네트워크 없이 두 형태를 다 고정해둔다.
        """
        payload = (b'{"header":{"resultCode":"00","resultMsg":"\xec\xa0\x95\xec\x83\x81"},'
                   b'"body":{"totalCount":1,"items":[{"bankNm":"\xea\xb5\xad\xeb\xaf\xbc\xec\x9d\x80'
                   b'\xed\x96\x89","avgLoanRat2":3.49,"loanAmt":100,"cnt":987}]}}')

        class FakeResp:
            def read(self): return payload
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(fbr.urllib.request, "urlopen", lambda *a, **k: FakeResp())
        items = fbr.fetch("key", "L1M")
        assert len(items) == 1 and items[0]["bankNm"] == "국민은행"

    def test_error_result_code_raises(self, monkeypatch):
        """200인데 header.resultCode가 오류인 경우 — 빈 결과로 흘리면 원인을 못 찾는다."""
        class FakeResp:
            def read(self):
                return b'{"header":{"resultCode":"30","resultMsg":"SERVICE_KEY_IS_NOT_REGISTERED"},"body":{}}'
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(fbr.urllib.request, "urlopen", lambda *a, **k: FakeResp())
        with pytest.raises(SystemExit, match="30"):
            fbr.fetch("key", "L1M")

    def test_json_response_parsed(self, monkeypatch):
        payload = (b'{"response":{"body":{"items":[{"bankNm":"KB\xea\xb5\xad\xeb\xaf\xbc\xec\x9d\x80'
                   b'\xed\x96\x89","avgLoanRat2":3.4,"loanAmt":100,"cnt":5}]}}}')

        class FakeResp:
            def read(self): return payload
            def __enter__(self): return self
            def __exit__(self, *a): return False

        monkeypatch.setattr(fbr.urllib.request, "urlopen", lambda *a, **k: FakeResp())
        items = fbr.fetch("key", "L1M")
        assert items[0]["bankNm"] == "KB국민은행"
