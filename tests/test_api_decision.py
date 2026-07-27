"""/api/decision 경계 테스트 — 스키마 검증 · 시세 추정 · 실패 경로.

이 경계가 왜 중요한가: `_estimate_price`가 캐시 평당가로 추정한 시세를 그대로
`decide()`에 넣고, 그 값이 engine.lgd → E[Loss] → 헤드라인 숫자까지 간다.
여기서 조용히 실패하면 화면은 "위험 미반영"만 보여주고 사용자는 이유를 모른다.
"""



import pytest
from fastapi.testclient import TestClient

from api.main import app, get_cache
from onjeon.market.cache import open_cache

BODY = {
    "profile": {
        "monthly_income_krw": 2_800_000,
        "assets_krw": 20_000_000,
        "age": 27,
        "region": "관악구",
        "expected_stay_years": 4,
        "works_at_sme": True,
    },
    "listing": {
        "deposit_krw": 20_000_000,
        "monthly_rent_krw": 550_000,
        "jeonse_deposit_krw": 200_000_000,
        "wolse_deposit_krw": 20_000_000,
        "wolse_monthly_rent_krw": 550_000,
    },
}


@pytest.fixture
def client(tmp_path):
    """빈 캐시를 물린 클라이언트 — 실거래가 데이터가 없는 상태가 기본값이다."""
    conn = open_cache(tmp_path / "cache.db")
    app.dependency_overrides[get_cache] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()
    conn.close()


def post(client, **listing_overrides):
    body = {"profile": BODY["profile"], "listing": {**BODY["listing"], **listing_overrides}}
    return client.post("/api/decision", json=body)


class TestSchemaValidation:
    """extra=forbid — 필드명 오타가 조용히 무시되면 위험 입력이 사라진다."""

    def test_misspelled_field_is_rejected(self):
        with TestClient(app) as c:
            r = c.post(
                "/api/decision",
                json={
                    "profile": {"monthly_income_krw": 2_800_000},
                    "listing": {"senior_claim_krw": 120_000_000},  # senior_claims_krw 오타
                },
            )
        assert r.status_code == 422
        assert "senior_claim_krw" in r.text

    def test_zero_income_accepted_not_rejected(self):
        """무소득은 유효한 입력이다 — 거절이 아니라 결과로 답한다.

        예전엔 `Field(gt=0)`로 422를 냈는데, 청년전용 버팀목전세자금대출은 소득
        **상한**만 있고 하한이 없어 무소득도 신청 대상이다. 소득 때문에 못 받는
        상품이 있으면 그건 미자격 반증으로 나와야 한다(tests/test_zero_income.py).
        """
        with TestClient(app) as c:
            r = c.post("/api/decision", json={"profile": {"monthly_income_krw": 0}, "listing": {}})
        assert r.status_code == 200

    def test_negative_income_rejected(self):
        with TestClient(app) as c:
            r = c.post("/api/decision", json={"profile": {"monthly_income_krw": -1}, "listing": {}})
        assert r.status_code == 422

    def test_negative_deposit_rejected(self):
        with TestClient(app) as c:
            r = c.post(
                "/api/decision",
                json={
                    "profile": {"monthly_income_krw": 2_800_000},
                    "listing": {"jeonse_deposit_krw": -1},
                },
            )
        assert r.status_code == 422


class TestPriceEstimation:
    def test_empty_cache_degrades_to_unadjusted_not_500(self, client):
        """캐시가 비면 시세를 못 구한다 — 500이 아니라 '미반영 + 사유'여야 한다."""
        r = post(client, senior_claims_krw=120_000_000, building_type="rh", exclusive_area_m2=40)
        assert r.status_code == 200
        risk = r.json()["jeonse_vs_wolse"]["jeonse"]["risk"]
        assert risk["adjusted"] is False
        assert "시세" in risk["reason"]
        assert "market_price_estimate" not in r.json()["sources"]

    def test_missing_area_skips_estimation(self, client):
        """면적이 없으면 평당가를 곱할 수 없다 — 조용히 넘어가고 사유를 남긴다."""
        r = post(client, senior_claims_krw=120_000_000, building_type="rh")
        assert r.status_code == 200
        assert r.json()["jeonse_vs_wolse"]["jeonse"]["risk"]["adjusted"] is False

    def test_unsupported_region_does_not_raise(self, client):
        """market_trends가 ValueError를 던지는 지역 — 500으로 새면 안 된다."""
        body = {
            "profile": {**BODY["profile"], "region": "존재하지않는구"},
            "listing": {**BODY["listing"], "building_type": "rh", "exclusive_area_m2": 40},
        }
        r = client.post("/api/decision", json=body)
        assert r.status_code == 200

    def test_user_price_wins_and_is_not_marked_estimated(self, client):
        """사용자가 넣은 매매가는 추정치가 아니다 — 화면이 둘을 다르게 표시한다."""
        r = post(
            client,
            market_price_krw=289_910_000,
            senior_claims_krw=120_000_000,
            building_type="rh",
        )
        assert r.status_code == 200
        d = r.json()
        assert d["jeonse_vs_wolse"]["jeonse"]["risk"]["market_price_krw"] == 289_910_000
        assert "market_price_estimate" not in d["sources"]

    def test_cached_deals_produce_estimate_flagged_as_such(self, tmp_path):
        """캐시에 거래가 있으면 평당가 × 면적으로 추정하고 estimated=True를 남긴다.

        캐시는 평당가(원/평)를 저장한다. 3억 / (40㎡ ÷ 3.3058)평 = 평당 2,479만원.
        여기에 전용 40㎡를 되곱하면 다시 3억이 나와야 한다 — 만원↔원 변환이
        경계에서 정확히 왕복하는지를 API 레벨에서 확인한다(결함 G 방어).
        """
        from onjeon.data_pipeline.regions import resolve_lawd_cd
        from onjeon.market.cache import save_month
        from onjeon.market.pyeong import price_per_pyeong

        conn = open_cache(tmp_path / "cache.db")
        # 캐시는 지역 **코드**로 키를 잡는다(trends.py가 resolve_lawd_cd를 거친다).
        # 한글 이름으로 저장하면 load_deals가 못 찾고 추정이 조용히 실패한다.
        save_month(
            conn, resolve_lawd_cd("관악구"), "rh", "trade", "202606",
            [{
                "deal_date": "2026-06-01",
                "pyeong_krw": price_per_pyeong(300_000_000, 40.0),
                "dong": "봉천동", "jibun": "100-1", "area_m2": 40.0,
            }],
            "2026-07-27",
        )
        app.dependency_overrides[get_cache] = lambda: conn
        try:
            r = TestClient(app).post(
                "/api/decision",
                json={
                    "profile": BODY["profile"],
                    "listing": {
                        **BODY["listing"],
                        "senior_claims_krw": 120_000_000,
                        "building_type": "rh",
                        "exclusive_area_m2": 40,
                    },
                },
            )
            assert r.status_code == 200
            d = r.json()
            src = d["sources"].get("market_price_estimate")
            assert src, "캐시에 거래가 있으면 추정이 되어야 한다"
            assert src["estimated"] is True
            assert src["area_m2"] == 40
            # 왕복 오차는 평당가 만원 절삭(// 10_000) 때문에 생긴다 — 0.1% 이내
            price = d["jeonse_vs_wolse"]["jeonse"]["risk"]["market_price_krw"]
            assert abs(price - 300_000_000) < 300_000, f"단위 왕복 실패: {price:,}원"
        finally:
            app.dependency_overrides.clear()
            conn.close()


class TestHappyPath:
    def test_full_inputs_return_comparison_and_citations(self, client):
        r = post(
            client,
            market_price_krw=289_910_000,
            senior_claims_krw=120_000_000,
            building_type="rh",
        )
        assert r.status_code == 200
        jw = r.json()["jeonse_vs_wolse"]
        assert jw["cheaper"] in ("전세", "월세")
        assert jw["jeonse"]["risk"]["adjusted"] is True
        assert jw["jeonse"]["breakdown"]["미회수기대손실"] > 0
        # 원칙 2 — 적용된 상품에 인용이 붙어야 한다
        assert jw["jeonse"]["loan_source"]["clause_refs"]
        for side in ("jeonse", "wolse"):
            s = jw[side]
            assert sum(s["breakdown"].values()) == s["annual_krw"]

    def test_building_type_code_is_normalized_for_auction_table(self, client):
        """프론트는 코드(rh)를 보내고 낙찰가율 룰은 한글(빌라)을 쓴다 — 경계에서 변환."""
        r = post(
            client,
            market_price_krw=289_910_000,
            senior_claims_krw=120_000_000,
            building_type="rh",
        )
        # 관악구 빌라 = 0.74 (코드가 변환되지 않으면 '기타' 폴백 0.70이 된다)
        assert r.json()["jeonse_vs_wolse"]["jeonse"]["risk"]["auction_rate"] == pytest.approx(0.74)
