"""제출 문서에 실린 헤드라인 수치를 배포 경로에 고정한다.

README·docs/summary.md·docs/problem.md·기술설명서 덱이 같은 실측 1건을 인용한다.
CLAUDE.md에 적힌 사고가 이미 한 번 났다 — `risk_model_*`을 새로 보정했더니 문서 세
곳의 숫자가 서로 어긋났고, 어긋난 채로 며칠이 지났다. 실물 룰(`load_rules`)을 그대로
쓰는 테스트가 없으면 룰을 갱신할 때 문서가 조용히 거짓이 된다.

**이 테스트가 깨지면 코드가 아니라 문서를 고쳐야 할 수 있다.** 계수를 의도적으로
갱신했다면 아래 기대값과 문서 네 곳을 같이 바꾼다. 의도하지 않았다면 회귀다.

다른 테스트들은 룰 드리프트를 피하려고 인라인 룰을 주입하는데, 여기는 반대로
**실물 룰을 쓰는 것이 목적**이다.
"""

from onjeon.decision import decide

# ── 문서에 적힌 실측 조건 (docs/summary.md §4)
PROFILE = {
    "monthly_income_krw": 2_800_000,
    "assets_krw": 20_000_000,
    "age": 27,
    "region": "관악구",
    "expected_stay_years": 4,
    "is_homeless": True,
    "is_household_head": True,
    "works_at_sme": True,
}
LISTING = {
    "kind": "jeonse",
    "deposit_krw": 200_000_000,
    "jeonse_deposit_krw": 200_000_000,
    "wolse_deposit_krw": 20_000_000,
    "wolse_monthly_rent_krw": 550_000,
    "market_price_krw": 290_000_000,
    "senior_claims_krw": 120_000_000,
    # "빌라"여야 관악구 낙찰가율 0.74가 걸린다. 영문 코드(rh)를 넣으면 조용히
    # default 기타 0.68로 떨어져 LGD가 52.7%→61.4%로 벌어진다.
    "building_type": "빌라",
    "exclusive_area_m2": 40.0,
    "region": "관악구",
    # 시세를 구 평균 평당가로 추정했다는 뜻 — 밴드 ±30%가 여기서 붙는다.
    "price_level": "sigungu",
}


def man(krw: int) -> int:
    """원 → 만원(반올림). 문서가 만원 단위로 인용하므로 같은 자리에서 비교한다."""
    return round(krw / 10_000)


def result():
    return decide(PROFILE, LISTING)["jeonse_vs_wolse"]


class TestHeadlineNumbers:
    def test_wolse_is_cheaper_by_413man(self):
        """"월세보다 연 413만원 비싸다" — 결론 문장 그 자체."""
        jw = result()
        assert jw["cheaper"] == "월세"
        assert man(jw["diff_krw"]) == 413

    def test_annual_totals(self):
        """전세 921만원 / 월세 508만원 (docs/summary.md §4 표)."""
        jw = result()
        assert man(jw["jeonse"]["annual_krw"]) == 921
        assert man(jw["wolse"]["annual_krw"]) == 508

    def test_breakdown_rows(self):
        """항목별 분해 — 기술설명서 슬라이드 9의 표."""
        j = result()["jeonse"]["breakdown"]
        assert {k: man(v) for k, v in j.items()} == {
            "정책대출이자": 120,
            "시장대출이자": 279,
            "보증금기회비용": 80,
            "미회수기대손실": 442,
        }

    def test_expected_loss_and_its_factors(self):
        """E[Loss] 442만원 = P 4.19% × LGD 52.7% × 2억."""
        risk = result()["jeonse"]["risk"]
        assert man(risk["e_loss_krw"]) == 442
        assert round(risk["p_accident"] * 100, 2) == 4.19
        assert round(risk["lgd"] * 100, 1) == 52.7
        assert risk["auction_rate"] == 0.74

    def test_band_is_125x_and_keeps_its_sign(self):
        """밴드 35만~4,414만(125배)에서도 부호가 바뀌지 않는다 — 강건성 주장의 근거."""
        jw = result()
        risk = jw["jeonse"]["risk"]
        lo, hi = risk["e_loss_range_krw"]
        assert (man(lo), man(hi)) == (35, 4414)
        assert round(hi / lo) == 125
        assert round(risk["p_accident_range"][0] * 100, 2) == 1.16
        assert round(risk["p_accident_range"][1] * 100, 2) == 11.63

        # 기대손실을 뺀 전세 비용에 밴드 양 끝을 각각 얹어 월세와 비교한다.
        no_loss = jw["jeonse"]["annual_krw"] - risk["e_loss_krw"]
        wolse = jw["wolse"]["annual_krw"]
        assert man(no_loss - wolse) == -29, "혜택만 보면 전세가 29만원 싸다"
        assert man(no_loss + lo - wolse) == 7, "밴드 하한에서도 전세가 비싸다(아슬아슬하게)"
        assert man(no_loss + hi - wolse) == 4385, "밴드 상한"

    def test_policy_product_applied(self):
        """중소기업취업청년 전월세보증금대출 — 금리 1.2% · 한도 1억."""
        j = result()["jeonse"]
        assert j["product_name"] == "중소기업취업청년 전월세보증금대출"
        assert j["loan_rate"] == 0.012
        assert j["loan_limit_krw"] == 100_000_000
