"""MOLIT 키가 없는 환경에서 시세 엔드포인트가 400으로 죽지 않는다.

실제로 났던 사고(2026-08-02, 제출 zip을 심사위원 환경으로 풀어 실행):
`data/cache.db`는 수집 시점(2026-06)까지만 차 있는데 날짜가 지나 최근 두 달이
빈 채로 조회 창에 들어왔다. 그러면 `market_trends`가 그 달을 채우러 국토부 API로
들어가고, 키가 없으니 `ValueError: MOLIT_API_KEY가 없다`가 400으로 나갔다.
README_심사용.md는 "API 키 없이 그대로 동작합니다"라고 약속하는데 첫 화면이 죽었다.

키 없음은 **에러가 아니라 캐시 전용 모드**여야 한다. 캐시가 낡을수록 조용히
빈 화면이 되는 게 아니라, 가진 데이터까지는 그려야 한다.
"""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _app_without_key(monkeypatch, tmp_path):
    """MOLIT_API_KEY 없이 api.main을 다시 읽어들인다(플래그가 import 시점에 정해진다)."""
    monkeypatch.delenv("MOLIT_API_KEY", raising=False)
    # load_env()가 .env에서 키를 다시 채워 넣으면 이 테스트가 개발 기기에서만 통과한다.
    monkeypatch.setattr("onjeon.config.load_env", lambda *a, **k: None)
    main = importlib.reload(importlib.import_module("api.main"))
    monkeypatch.setattr(main, "_CACHE_PATH", tmp_path / "cache.db")  # 빈 캐시
    return main


def test_no_key_serves_cache_only_instead_of_400(monkeypatch, tmp_path):
    main = _app_without_key(monkeypatch, tmp_path)
    assert main._CAN_FETCH_MOLIT is False

    res = TestClient(main.app).get(
        "/api/market-trends", params={"region": "관악구", "buildingType": "rh", "period": "1y"}
    )
    assert res.status_code == 200, f"키 없음이 400이 됐다: {res.text}"
    assert res.json()["cache_only"] is True


def test_readonly_flag_does_not_depend_on_molit_key(monkeypatch, tmp_path):
    """_READONLY(공개 배포 자세)와 키 유무는 별개다.

    묶어버리면 GEMINI 키만 있는 로컬에서 L4 등기부 해설이 통째로 꺼진다 —
    시세 키가 없다는 것과 해설을 끄는 것은 아무 상관이 없다.
    """
    main = _app_without_key(monkeypatch, tmp_path)
    assert main._READONLY is False
