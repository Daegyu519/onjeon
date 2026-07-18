"""L2 XGBoost 백엔드 테스트 — LR와 동일 인터페이스 계약 + TreeSHAP 불변식.

기존 tests/test_l2.py(LR 경로)는 무변경 유지. 이 파일은 XGB 스왑 백엔드와
train_risk_model 팩토리만 검증한다.
"""

import math

import pytest

from onjeon.l2.model import RiskModel, XGBRiskModel, train_risk_model, train_xgb
from onjeon.l2.synth import FEATURES, generate

RISKY = {"jeonse_ratio": 0.80, "lien_ratio": 0.48, "is_villa": 1, "auction_rate": 0.78}
SAFE = {"jeonse_ratio": 0.05, "lien_ratio": 0.0, "is_villa": 0, "auction_rate": 0.85}


@pytest.fixture(scope="module")
def xgb_model():
    return train_xgb(generate(1500, seed=42))


class TestXGBInterfaceContract:
    """RiskModel과 동일 인터페이스(덕타이핑) — compare.py 무수정 호환 계약."""

    def test_predict_proba_in_range(self, xgb_model):
        for x in (RISKY, SAFE):
            p = xgb_model.predict_proba(x)
            assert 0.0 < p < 1.0

    def test_risky_higher_than_safe(self, xgb_model):
        assert xgb_model.predict_proba(RISKY) > xgb_model.predict_proba(SAFE)

    def test_explain_keys_match_lr_contract(self, xgb_model):
        result = xgb_model.explain(RISKY)
        assert set(result) == {"p", "base_logit", "contributions", "data_note"}

    def test_explain_covers_all_features(self, xgb_model):
        result = xgb_model.explain(RISKY)
        assert [name for name, _ in result["contributions"]] == FEATURES

    def test_has_data_note_attribute(self, xgb_model):
        # compare.py가 model.data_note를 sources.risk_model_note로 직접 인용한다
        assert isinstance(xgb_model.data_note, str)


class TestTreeShapInvariant:
    """base_logit(bias) + Σ SHAP 기여도 ≈ logit(p) — margin 단위 pred_contribs."""

    @pytest.mark.parametrize("x", [RISKY, SAFE], ids=["risky", "safe"])
    def test_contributions_plus_base_equal_logit(self, xgb_model, x):
        result = xgb_model.explain(x)
        p = result["p"]
        logit = math.log(p / (1 - p))
        total = result["base_logit"] + sum(c for _, c in result["contributions"])
        assert total == pytest.approx(logit, abs=1e-3)

    def test_explain_p_matches_predict_proba(self, xgb_model):
        assert xgb_model.explain(RISKY)["p"] == pytest.approx(
            xgb_model.predict_proba(RISKY), abs=1e-9
        )


class TestDataNote:
    def test_synthetic_disclosure_kept(self, xgb_model):
        # 정직성 원칙(CLAUDE.md 원칙 5): 합성 데이터 고지는 백엔드가 바뀌어도 유지
        note = xgb_model.explain(RISKY)["data_note"]
        assert "합성 데이터 — 구조 시연 목적" in note

    def test_backend_marked(self, xgb_model):
        assert "XGBoost 백엔드" in xgb_model.explain(RISKY)["data_note"]


class TestFactory:
    def test_default_is_lr(self, monkeypatch):
        # 합성 데이터 단계에서는 단순·정직한 LR가 기본 (CLAUDE.md 원칙 5)
        monkeypatch.delenv("ONJEON_L2_BACKEND", raising=False)
        model = train_risk_model(generate(300, seed=1))
        assert isinstance(model, RiskModel)

    def test_explicit_xgb(self, monkeypatch):
        monkeypatch.delenv("ONJEON_L2_BACKEND", raising=False)
        model = train_risk_model(generate(300, seed=1), backend="xgb")
        assert isinstance(model, XGBRiskModel)

    def test_env_override_to_xgb(self, monkeypatch):
        monkeypatch.setenv("ONJEON_L2_BACKEND", "xgb")
        model = train_risk_model(generate(300, seed=1))
        assert isinstance(model, XGBRiskModel)

    def test_unknown_backend_raises(self, monkeypatch):
        monkeypatch.delenv("ONJEON_L2_BACKEND", raising=False)
        with pytest.raises(ValueError):
            train_risk_model(generate(300, seed=1), backend="rf")
