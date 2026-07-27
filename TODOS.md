# TODOS

작업 대기 항목. 각 항목은 3개월 뒤에 읽어도 배경·현재상태·시작점을 알 수 있게 적는다.

---

## 1. ~~배포 API에 E[Loss] 배선~~ — 완료 (2026-07-27)

**해결:** `decision.py::_risk()`가 `P(사고) × LGD × 보증금`을 계산해
`breakdown["미회수기대손실"]`로 넣는다. 전세·월세 대칭 계산(월세는 보증금이 작아
회수액이 덮으면 자연히 0). 입력이 없으면 `risk.adjusted=False` + 사유를 남기고
0으로 조용히 계산하지 않는다.

**Cons로 적혔던 것이 해결된 방식:** "scikit-learn을 배포 경로로 끌고 와야 한다 →
`requirements-api.txt`가 슬림해진 근거가 깨진다"였는데, 그럴 필요가 없었다.
로지스틱 회귀의 추론은 시그모이드 한 줄이라 학습된 계수만 있으면 stdlib으로 충분하다.
`scripts/dump_risk_model.py`가 계수를 `rules/risk_model_2026-07.json`으로 덤프하고
`l2.model.load_risk_model()`이 읽는다. numpy·pandas·sklearn import는 학습 함수 안으로
옮겼고, `tests/test_risk_wiring.py`가 최상단 import를 정적으로 검사한다.
실측: `requirements-api.txt`만 설치한 venv에서 `import api.main` + E[Loss] 산출 성공.

**선행조건도 해결:** `/api/decision`이 pydantic 스키마(`extra="forbid"`)를 쓰고
`senior_claims_krw`·`building_type`·`exclusive_area_m2`·`insured`를 받는다. 시세 미입력 시
캐시 평당가 × 전용면적으로 추정한다(`market.pyeong.estimate_market_price_krw`, 항상 캐시만).

**남은 것:** 채권최고액 regex 자동 추출(현재는 수동 입력). `register/parse.py`에
을구 근저당 패턴을 추가하면 등기부 업로드로 자동 채움 — 실패해도 수동 입력이
1차 경로라 기능은 동작한다.

---
