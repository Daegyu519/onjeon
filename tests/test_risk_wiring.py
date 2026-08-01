"""E[Loss] 배선 — 시세 단위 격리 · 계수 JSON 추론 · 위험 조정 게이트.

배포 경로(api.main → decision)에 미회수 기대손실을 붙이는 부분이다. 계획서
docs/superpowers/specs/2026-07-27-jeonse-vs-wolse-promotion-design.md §3 참조.

여기서 지키는 두 가지 불변식:
1. 평당가는 만원 단위다 — ×10000을 빼먹으면 예외 없이 LGD가 1.0으로 고정된다(결함 G).
2. 입력이 없으면 E[Loss]를 0으로 두고 조용히 계산하지 않는다 — 사유를 남긴다(원칙 5).
"""

import ast
import json
from pathlib import Path

import pytest

from onjeon.decision import decide
from onjeon.l2.model import FEATURES, RiskModel, load_risk_model
from onjeon.l3 import engine
from onjeon.market.pyeong import PYEONG_PER_M2, estimate_market_price_krw
from onjeon.rules_io import load_rules

SRC = Path(__file__).resolve().parent.parent / "src"


class TestEstimateMarketPrice:
    """평당가(만원) × 전용면적 → 시세(원). 단위 변환이 이 함수 한 곳에만 있다."""

    def test_gwanak_villa_40m2(self):
        # 평당 1,850만원 × (40 ÷ 3.3058)평 = 12.10평 → 2.24억
        got = estimate_market_price_krw(pyeong_price_manwon=1850, area_m2=40.0)
        assert got == round(1850 * 10_000 * (40.0 / PYEONG_PER_M2))
        assert 220_000_000 < got < 230_000_000  # 원 단위임을 크기로 못박는다

    def test_result_is_won_not_manwon(self):
        """만원을 반환하면 LGD가 1.0으로 고정되는 결함 G가 재발한다."""
        got = estimate_market_price_krw(pyeong_price_manwon=1850, area_m2=40.0)
        assert got > 100_000_000, "원 단위가 아니다 — ×10000 누락 의심"

    def test_zero_area_raises(self):
        with pytest.raises(ValueError):
            estimate_market_price_krw(pyeong_price_manwon=1850, area_m2=0)

    def test_negative_area_raises(self):
        with pytest.raises(ValueError):
            estimate_market_price_krw(pyeong_price_manwon=1850, area_m2=-1)

    def test_roundtrip_with_price_per_pyeong(self):
        """역함수와 왕복해야 한다 — 두 방향의 단위 규약이 같음을 증명."""
        from onjeon.market.pyeong import price_per_pyeong

        price, area = 224_000_000, 40.0
        pp_won = price_per_pyeong(price, area)
        back = estimate_market_price_krw(pyeong_price_manwon=pp_won / 10_000, area_m2=area)
        assert abs(back - price) <= 1


class TestRuntimeHasNoMLDeps:
    """배포 런타임(requirements-api.txt)에 numpy·pandas·sklearn이 없다.

    l2.model을 최상단에서 그 셋을 import하도록 두면 api.main이 컨테이너에서 죽는다.
    실제 venv를 만들지 않고도 정적으로 검증할 수 있다.
    """

    BANNED = {"numpy", "pandas", "sklearn", "scipy", "xgboost", "shap"}

    def _toplevel_imports(self, rel: str) -> set[str]:
        tree = ast.parse((SRC / rel).read_text(encoding="utf-8"))
        names = set()
        for node in tree.body:  # 최상단만 — 함수 안 import는 통과시킨다
            if isinstance(node, ast.Import):
                names |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        return names

    def test_model_module_is_stdlib_at_import_time(self):
        assert not (self._toplevel_imports("onjeon/l2/model.py") & self.BANNED)

    def test_model_does_not_pull_synth_at_toplevel(self):
        """synth는 numpy·pandas를 최상단에서 쓴다 — 거기서 상수를 가져오면 같이 끌려온다."""
        tops = self._toplevel_imports("onjeon/l2/model.py")
        assert "onjeon" not in tops or all(
            "synth" not in m
            for m in {
                n.module
                for n in ast.parse((SRC / "onjeon/l2/model.py").read_text()).body
                if isinstance(n, ast.ImportFrom) and n.module
            }
        )

    def test_decision_and_pyeong_are_stdlib(self):
        for rel in ("onjeon/decision.py", "onjeon/market/pyeong.py", "onjeon/l3/engine.py"):
            assert not (self._toplevel_imports(rel) & self.BANNED), rel


class TestRiskModelFromRules:
    """학습된 계수를 룰 JSON에서 읽어 stdlib만으로 추론한다."""

    def test_coefficient_signs_move_risk_the_right_way(self):
        """`0 < p < 1`은 시그모이드라 항상 참이라 아무것도 증명하지 못한다.

        대신 **공개 통계가 실제로 뒷받침하는** 방향만 검사한다.

        `is_villa`는 일부러 뺐다. 보정 결과가 −0.04(빌라가 근소하게 안전)로 나와
        "빌라가 위험하다"는 통념과 반대다. 2023-05 HUG 담보인정비율 강화 이후
        빌라 보증 풀이 걸러진 영향으로 보이지만 확정할 수 없다. 통념을 테스트로
        고정하면 데이터가 반증해도 못 보게 된다 — 크기만 작은지 확인한다.
        """
        model = load_risk_model()
        base = {"jeonse_ratio": 0.6, "lien_ratio": 0.3, "is_villa": 1, "auction_rate": 0.74}
        p0 = model.predict_proba(base)
        assert model.predict_proba({**base, "jeonse_ratio": 0.9}) > p0, "전세가율↑ → 위험↑"
        assert model.predict_proba({**base, "lien_ratio": 0.6}) > p0, "근저당비율↑ → 위험↑"
        assert model.predict_proba({**base, "auction_rate": 0.92}) < p0, "낙찰가율↑ → 위험↓"
        assert abs(model.coef["is_villa"]) < 0.5, (
            "유형 효과가 크게 나오면 근거를 확인해야 한다 — 현재 데이터는 약한 효과만 지지한다"
        )

    def test_calibration_reproduces_published_marginals(self):
        """보정의 검증 가능한 주장 — 모델이 공개 통계의 집계 사고율을 재현하는가.

        예전엔 '합성 데이터로 학습했다'가 전부라 검증할 대상이 없었다. 이제
        유형별·전세가율 구간별 실측 사고율을 0.5%p 이내로 맞추는지 확인할 수 있다.
        """
        rule = json.loads(
            sorted((SRC / "onjeon/rules").glob("risk_model_*.json"))[-1].read_text("utf-8")
        )
        check = rule.get("calibration_check")
        if not check:
            pytest.skip("합성 학습 룰에는 마진 재현 기록이 없다")
        for label, v in check.items():
            gap = abs(v["actual"] - v["predicted"])
            assert gap < 0.005, f"{label}: 실측 {v['actual']:.4f} vs 모델 {v['predicted']:.4f}"

    def test_periods_span_real_variation(self):
        """시점별 계수가 실려 있어야 P 밴드가 생긴다 — 사고율은 해마다 몇 배 움직인다."""
        rule = json.loads(
            sorted((SRC / "onjeon/rules").glob("risk_model_*.json"))[-1].read_text("utf-8")
        )
        periods = rule.get("periods")
        if not periods:
            pytest.skip("시점 데이터가 없는 룰")
        rates = [p["actual_overall"] for p in periods]
        assert len(periods) >= 2
        assert max(rates) / min(rates) > 2, "시점 변동이 작으면 밴드의 의미가 없다"

    def test_base_rate_is_anchored_near_hug_statistic(self):
        """기저 사고율이 HUG 공개 통계(연 2.2%)에 앵커돼 있어야 한다 — 원칙 5의 근거."""
        model = load_risk_model()
        p_at_mean = model.predict_proba(dict(model.feature_means))
        assert 0.005 < p_at_mean < 0.06, f"모집단 평균 사고율이 비현실적: {p_at_mean:.3%}"

    def test_rule_file_has_version_and_note(self):
        rule = json.loads(
            sorted((SRC / "onjeon/rules").glob("risk_model_*.json"))[-1].read_text("utf-8")
        )
        assert rule["version"]
        assert rule["data_note"], "합성 데이터 한계를 문서에 남겨야 한다(원칙 5)"
        assert list(rule["coef"]) == FEATURES

    def test_missing_data_note_does_not_claim_synthetic(self, monkeypatch):
        """출처가 없는 룰은 '모른다'고 말해야 한다 — '합성 데이터'라고 단정하면 거짓이다.

        폴백에 DATA_NOTE를 쓰면 배포에 실린 공개통계 보정 모델이 화면에서 '합성 데이터'로
        소개된다. 신뢰도 서술이 조용히 뒤집히는 방향이라 예외도 경고도 나지 않는다(원칙 2).
        """
        from onjeon.l2 import model as model_mod

        rule = load_rules("risk_model")
        monkeypatch.setattr(
            model_mod, "load_rules", lambda name: {k: v for k, v in rule.items() if k != "data_note"}
        )
        note = load_risk_model().data_note
        assert "합성" not in note, f"출처 없는 룰을 합성 데이터라고 단정했다: {note}"
        assert note, "빈 문자열이면 화면이 출처 칸을 그냥 비운다 — 모른다고 말해야 한다"

    def test_explain_decomposes_logit_exactly(self):
        """base_logit + Σ기여도 = logit(p) — XAI 주장의 근거."""
        import math

        model = load_risk_model()
        x = {"jeonse_ratio": 0.9, "lien_ratio": 0.4, "is_villa": 1, "auction_rate": 0.7}
        out = model.explain(x)
        total = out["base_logit"] + sum(c for _, c in out["contributions"])
        assert math.isclose(total, math.log(out["p"] / (1 - out["p"])), rel_tol=1e-9)

    def test_rule_declares_how_it_was_made(self):
        """계수의 출처가 룰에 적혀 있어야 한다 (원칙 2·5).

        예전 테스트는 `train(generate())`와 일치하는지 봤는데, 그건 순환이었다 —
        지어낸 계수로 만든 데이터를 다시 학습해 "일치한다"고 확인하는 셈이었다.
        지금 검증할 것은 '이 숫자가 어디서 왔는가'다.
        """
        rule = json.loads(
            sorted((SRC / "onjeon/rules").glob("risk_model_*.json"))[-1].read_text("utf-8")
        )
        assert rule.get("calibration") == "aggregate_marginal", "보정 방식이 명시돼야 한다"
        src = rule.get("source", {})
        assert src.get("url") and src.get("name"), "원천 출처가 있어야 한다"
        assert src.get("files"), "어느 파일로 보정했는지 남겨야 한다"
        assert len(rule.get("limitations", [])) >= 4, "한계를 먼저 말한다(원칙 5)"
        assert "[확인" in " ".join(rule["limitations"]), "미검증 항목에 마커가 필요하다"


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
    "kind": "wolse",
    "deposit_krw": 20_000_000,
    "monthly_rent_krw": 550_000,
    "jeonse_deposit_krw": 200_000_000,
    "wolse_deposit_krw": 20_000_000,
    "wolse_monthly_rent_krw": 550_000,
}
RISK_INPUTS = {
    "market_price_krw": 224_000_000,
    "senior_claims_krw": 120_000_000,
    "building_type": "빌라",
}


class TestRiskGate:
    """입력이 없으면 0으로 조용히 계산하지 않고 사유를 남긴다."""

    def test_no_risk_inputs_reports_unadjusted(self):
        r = decide(PROFILE, LISTING)
        risk = r["jeonse_vs_wolse"]["jeonse"]["risk"]
        assert risk["adjusted"] is False
        assert risk["reason"], "왜 미반영인지 사용자에게 말해야 한다"
        assert r["jeonse_vs_wolse"]["jeonse"]["breakdown"]["미회수기대손실"] == 0

    def test_missing_senior_claims_names_that_field(self):
        r = decide(PROFILE, {**LISTING, "market_price_krw": 224_000_000})
        assert "채권최고액" in r["jeonse_vs_wolse"]["jeonse"]["risk"]["reason"]

    def test_missing_market_price_names_that_field(self):
        r = decide(PROFILE, {**LISTING, "senior_claims_krw": 120_000_000})
        assert "시세" in r["jeonse_vs_wolse"]["jeonse"]["risk"]["reason"]

    def test_full_inputs_produce_positive_e_loss(self):
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS})
        jz = r["jeonse_vs_wolse"]["jeonse"]
        assert jz["risk"]["adjusted"] is True
        assert jz["breakdown"]["미회수기대손실"] > 0
        assert 0 < jz["risk"]["p_accident"] < 1
        assert 0 <= jz["risk"]["lgd"] <= 1

    def test_e_loss_is_in_the_total(self):
        """breakdown 합 = annual_krw 불변식이 E[Loss]를 포함해도 성립해야 한다."""
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS})
        for side in ("jeonse", "wolse"):
            s = r["jeonse_vs_wolse"][side]
            assert sum(s["breakdown"].values()) == s["annual_krw"]

    def test_insured_property_has_no_expected_loss(self):
        """보증보험 가입 매물은 LGD 0 (engine.lgd 계약)."""
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS, "insured": True})
        assert r["jeonse_vs_wolse"]["jeonse"]["risk"]["lgd"] == 0.0
        assert r["jeonse_vs_wolse"]["jeonse"]["breakdown"]["미회수기대손실"] == 0

    def test_senior_claims_over_market_price_is_max_loss(self):
        """선순위가 시세를 넘으면 회수 예상액 0 → LGD 1.0."""
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS, "senior_claims_krw": 500_000_000})
        assert r["jeonse_vs_wolse"]["jeonse"]["risk"]["lgd"] == 1.0


class TestSensitivity:
    """시세는 동네 집계 평균 추정치다 — P와 LGD 양쪽에 들어가 오차가 증폭된다."""

    def test_band_brackets_the_point_estimate(self):
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS})
        risk = r["jeonse_vs_wolse"]["jeonse"]["risk"]
        low, high = risk["e_loss_range_krw"]
        assert low <= risk["e_loss_krw"] <= high

    def test_user_entered_price_has_no_price_band(self):
        """직접 입력한 매매가엔 시세 밴드를 붙이지 않는다.

        단 **P의 시점 변동 밴드는 남는다** — 시세를 정확히 알아도 사고확률이
        어느 해 기준이냐에 따라 몇 배 달라지는 건 그대로다.
        """
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS})
        risk = r["jeonse_vs_wolse"]["jeonse"]["risk"]
        assert risk["price_band"] == 0.0, "시세 밴드는 없어야 한다"
        lo, hi = risk["e_loss_range_krw"]
        assert lo <= risk["e_loss_krw"] <= hi
        if load_risk_model().periods:
            assert lo < hi, "시점 변동이 있으면 P 밴드가 남아야 한다"

    def test_estimated_price_gets_band_and_direction_is_right(self):
        """추정 시세면 밴드가 붙고, 시세가 높을수록 기대손실이 작아야 한다."""
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS, "price_level": "dong"})
        risk = r["jeonse_vs_wolse"]["jeonse"]["risk"]
        low, high = risk["e_loss_range_krw"]
        assert risk["price_band"] > 0
        assert low < risk["e_loss_krw"] < high, "상단 시세가 하한, 하단 시세가 상한"

    def test_coarser_aggregation_gives_wider_band(self):
        """구 평균 추정은 동 단위보다 밴드가 넓어야 한다 — 거짓 정밀도 방지."""
        def span(level):
            r = decide(PROFILE, {**LISTING, **RISK_INPUTS, "price_level": level})
            lo, hi = r["jeonse_vs_wolse"]["jeonse"]["risk"]["e_loss_range_krw"]
            return hi - lo

        assert span("jibun") < span("dong") < span("sigungu")

    def test_no_band_when_unadjusted(self):
        r = decide(PROFILE, LISTING)
        assert "e_loss_range_krw" not in r["jeonse_vs_wolse"]["jeonse"]["risk"]


class TestAuctionRateSelection:
    def test_unknown_building_type_falls_back_conservatively(self):
        """테이블에 없는 유형은 가장 보수적(최저) 낙찰가율 — LGD 과소평가 방지.

        `> 0`으로만 검사하면 최댓값을 잘못 골라도 통과한다. 실제 최저값을 못박는다.
        """
        rates = load_rules("auction_rates")["rates"]["default"]
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS, "building_type": "없는유형"})
        assert r["jeonse_vs_wolse"]["jeonse"]["risk"]["auction_rate"] == pytest.approx(
            min(rates.values())
        )

    def test_type_absent_from_region_table_falls_back_to_default_table(self):
        """지역표에 없지만 default표에 있는 유형 — 중간 폴백 경로."""
        auction_rates = {
            "rates": {
                "관악구": {"빌라": 0.74},  # 오피스텔이 없다
                "default": {"빌라": 0.71, "오피스텔": 0.82, "기타": 0.68},
            }
        }
        assert engine.auction_rate("관악구", "오피스텔", auction_rates) == pytest.approx(0.82)
        assert engine.auction_rate("관악구", "빌라", auction_rates) == pytest.approx(0.74)
        assert engine.auction_rate("부산진구", "빌라", auction_rates) == pytest.approx(0.71)

    def test_region_table_beats_default(self):
        """관악구 빌라는 0.74(지역표), default는 0.71."""
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS})
        assert r["jeonse_vs_wolse"]["jeonse"]["risk"]["auction_rate"] == pytest.approx(0.74)


def test_riskmodel_dataclass_still_constructible():
    """compare.py(Streamlit 경로)가 train()의 반환값을 그대로 쓴다 — 계약 유지."""
    m = RiskModel(
        coef=dict.fromkeys(FEATURES, 0.5),
        intercept=-7.5,
        feature_means=dict.fromkeys(FEATURES, 0.5),
    )
    assert 0 < m.predict_proba(dict.fromkeys(FEATURES, 0.5)) < 1


class TestPropertyRegionBeatsPreferredRegion:
    """낙찰가율은 매물 소재지 기준이어야 한다 — profile.region은 사용자의 희망지역이다.

    등기부 없이 채권최고액만 입력하거나, 업로드 후 희망지역을 바꾸면 두 값이 갈린다.
    그때 희망지역의 통계로 계산하면 엉뚱한 매물의 위험을 보여준다.
    """

    def test_listing_region_wins(self):
        # 관악구 빌라 0.74 vs default 빌라 0.71 — 어느 쪽이 쓰였는지로 판별한다
        gwanak = decide(
            {**PROFILE, "region": "강남구"},  # 희망지역은 강남구
            {**LISTING, **RISK_INPUTS, "region": "관악구"},  # 매물은 관악구
        )
        assert gwanak["jeonse_vs_wolse"]["jeonse"]["risk"]["auction_rate"] == pytest.approx(0.74)

    def test_falls_back_to_profile_region_when_listing_has_none(self):
        r = decide(PROFILE, {**LISTING, **RISK_INPUTS})  # PROFILE.region == 관악구
        assert r["jeonse_vs_wolse"]["jeonse"]["risk"]["auction_rate"] == pytest.approx(0.74)

    def test_unknown_listing_region_uses_default_table(self):
        r = decide(
            {**PROFILE, "region": "관악구"},
            {**LISTING, **RISK_INPUTS, "region": "부산진구"},  # 표에 없는 지역
        )
        assert r["jeonse_vs_wolse"]["jeonse"]["risk"]["auction_rate"] == pytest.approx(0.71)
