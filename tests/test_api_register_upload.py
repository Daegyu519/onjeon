"""등기부 업로드 → 의사결정, 비서울·건물등기부 경로 end-to-end.

첨부된 실물(대전 유성구 궁동 다중주택)에서 드러난 경로다. 서울 집합건물만
테스트하면 이 조합은 아무것도 보증하지 않는다:
  - 시세 수집 범위 밖(서울 25개 구 외) → region_code가 None
  - 건물 등기부 → 전용면적 미확정
두 조건이 겹쳐도 **채권최고액은 살아남고, 사용자가 시세·면적을 직접 넣으면
미회수 기대손실까지 그대로 계산돼야 한다.**
"""

import pathlib

import pytest
from fastapi.testclient import TestClient

from api.main import app, get_cache
from onjeon.market.cache import open_cache

FIXTURES = pathlib.Path(__file__).resolve().parent.parent / "data/fixtures/fake_registers"
DAEJEON = FIXTURES / "대전-유성구-다중주택-건물등기부.pdf"
SEOUL = FIXTURES / "서울-강남구-다세대주택.pdf"


@pytest.fixture
def client(tmp_path):
    conn = open_cache(tmp_path / "cache.db")
    app.dependency_overrides[get_cache] = lambda: conn
    yield TestClient(app)
    app.dependency_overrides.clear()
    conn.close()


def upload(client, path):
    if not path.exists():
        pytest.skip("가짜 등기부 PDF 없음 — scripts/gen_fake_registers.py로 생성")
    with open(path, "rb") as fh:
        r = client.post("/api/register/parse", files={"file": (path.name, fh, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


class TestBuildingRegisterUpload:
    def test_claims_survive_when_area_undecidable(self, client):
        """면적을 못 정해도 200이어야 한다 — 예전엔 422로 전부 버렸다."""
        b = upload(client, DAEJEON)
        assert b["senior_claims_krw"] == 120_000_000
        assert b["exclusive_area_m2"] is None
        assert b["area_note"]

    def test_unsupported_region_is_stated_not_silent(self, client):
        """지역 칸이 조용히 비는 대신 이유가 보여야 한다."""
        b = upload(client, DAEJEON)
        assert b["region_supported"] is False
        assert b["region_code"] is None
        # 비서울이면 두 가지가 함께 막힌다 — 하나만 말하면 나머지를 나중에 발견한다
        joined = " ".join(b["warnings"])
        assert "서울 25개 구만" in joined, "지원 범위를 말해야 한다"
        assert "실거래가 시세" in joined, "시세 자동 추정이 막히는 것을 말해야 한다"
        assert "최우선변제" in joined, "최우선변제가 0이 되는 것을 말해야 한다"

    def test_document_limits_reach_the_client(self, client):
        b = upload(client, DAEJEON)
        joined = " ".join(b["warnings"])
        assert "토지 등기부" in joined       # 건물 등기부는 짝이 따로 있다
        assert "확정일자" in joined          # 다중주택 다른 세입자 선순위

    def test_seoul_jiphap_still_supported(self, client):
        """회귀 방지 — 서울 집합건물은 지역·면적이 그대로 채워져야 한다."""
        b = upload(client, SEOUL)
        assert b["region_supported"] is True
        assert b["region_code"] == "11680"
        assert b["exclusive_area_m2"] > 0
        assert not any("서울 25개 구만" in w for w in b["warnings"])


class TestManualInputCompletesTheCalculation:
    """자동으로 못 채운 값을 사용자가 넣으면 E[Loss]까지 계산돼야 한다.

    이게 안 되면 "못 읽었으니 수동 입력하세요" 안내가 거짓말이 된다.
    """

    def test_expected_loss_computed_from_manual_price_and_area(self, client):
        b = upload(client, DAEJEON)
        body = {
            "profile": {"monthly_income_krw": 2_800_000, "assets_krw": 20_000_000, "age": 27},
            "listing": {
                "jeonse_deposit_krw": 150_000_000,
                "wolse_deposit_krw": 20_000_000,
                "wolse_monthly_rent_krw": 600_000,
                # 등기부에서 자동으로 온 값
                "senior_claims_krw": b["senior_claims_krw"],
                "building_type": b["building_type"],
                # 사용자가 직접 넣는 값 — 자동으로는 못 정한 것들
                "market_price_krw": 300_000_000,
                "exclusive_area_m2": 25.0,
            },
        }
        r = client.post("/api/decision", json=body)
        assert r.status_code == 200, r.text
        risk = r.json()["jeonse_vs_wolse"]["jeonse"]["risk"]
        assert risk["adjusted"] is True, f"위험 미반영: {risk}"
        assert risk["senior_claims_krw"] == 120_000_000
        assert r.json()["jeonse_vs_wolse"]["jeonse"]["breakdown"]["미회수기대손실"] > 0
