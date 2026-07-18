"""L2 리스크 예측 테스트 — 합성 데이터는 '구조 시연 목적'임을 출력에 명시한다."""

import math

import pandas as pd
import pytest

from onjeon.l2.synth import FEATURES, generate
from onjeon.l2.model import train

RISKY = {"jeonse_ratio": 0.80, "lien_ratio": 0.48, "is_villa": 1, "auction_rate": 0.78}
SAFE = {"jeonse_ratio": 0.05, "lien_ratio": 0.0, "is_villa": 0, "auction_rate": 0.85}


class TestSynth:
    def test_same_seed_same_data(self):
        pd.testing.assert_frame_equal(generate(200, seed=7), generate(200, seed=7))

    def test_columns(self):
        df = generate(100, seed=1)
        assert list(df.columns) == FEATURES + ["accident"]

    def test_label_rate_sane(self):
        df = generate(2000, seed=42)
        assert 0.01 < df["accident"].mean() < 0.4


@pytest.fixture(scope="module")
def risk_model():
    return train(generate(1500, seed=42))


class TestModel:
    def test_predict_proba_in_range(self, risk_model):
        p = risk_model.predict_proba(RISKY)
        assert 0.0 < p < 1.0

    def test_risky_higher_than_safe(self, risk_model):
        assert risk_model.predict_proba(RISKY) > risk_model.predict_proba(SAFE)

    def test_safe_property_low_probability(self, risk_model):
        assert risk_model.predict_proba(SAFE) < 0.05

    def test_explain_contributions_sum_to_logit(self, risk_model):
        result = risk_model.explain(RISKY)
        p = result["p"]
        logit = math.log(p / (1 - p))
        total = result["base_logit"] + sum(c for _, c in result["contributions"])
        assert total == pytest.approx(logit, abs=1e-6)

    def test_explain_covers_all_features(self, risk_model):
        result = risk_model.explain(RISKY)
        assert [name for name, _ in result["contributions"]] == FEATURES

    def test_synthetic_data_disclosure(self, risk_model):
        # 정직성 원칙: 합성 데이터임을 출력 구조에 명시 (CLAUDE.md 원칙 5)
        assert "합성" in risk_model.explain(RISKY)["data_note"]
