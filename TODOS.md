# TODOS

작업 대기 항목. 각 항목은 3개월 뒤에 읽어도 배경·현재상태·시작점을 알 수 있게 적는다.

---

## 1. 배포 API에 E[Loss] 배선 — `decision.py`의 `e_loss=0` 연결

**What:** `src/onjeon/decision.py`의 `_rental_annual_cost()`(L35)와 `compare_jeonse_wolse()`(L79)가
`engine.annual_cost_jeonse(..., e_loss=0)`으로 호출한다. 여기에 실제 기대손실
(`P(사고) × LGD × 보증금`)을 연결한다.

**Why:** 프로젝트 한 줄 요약이 *"보증금 미회수 위험을 원(₩) 단위 기대손실로 환산하여
리스크 조정 총비용을 비교"*다. 배포 API(`api.main` → `onjeon.decision`)가 산출하는
전세 비용에 그 항이 빠져 있어서, 공개 URL 사용자는 프로젝트의 대표 숫자를 볼 수 없다.
README 헤드라인 *"미회수 기대손실 연 180만원을 반영하면…"*이 배포 화면에서 재현되지 않는다.

**현재 상태 — 버그가 아니라 의도된 슬라이스 경계다.** `decision.py:4-5` 주석:
*"3안 비교(compare_options)는 전체 매물문서·리스크모델이 필요해 이번 슬라이스에선
제외한다(연결은 이후)."* `engine.expected_loss()`는 구현돼 있고 `compare.py:70`에서
호출되지만, `compare.py`는 Streamlit(app.py) 전용이라 배포 경로에 없다.

**Pros:** 출품작 차별점이 배포된 제품에서 실제로 동작한다. 심사에서 헤드라인 주장과
화면이 일치한다. `engine.expected_loss()`·`l2` 모델이 이미 있어 신규 수식은 없다.

**Cons:** L2 리스크 모델(`scikit-learn`)과 등기부 파싱 입력을 배포 경로로 끌고 와야 한다.
`requirements-api.txt`가 63MB로 슬림해진 근거(런타임 미사용 ML 스택 제외, 커밋 `7485de9`)가
깨진다. 컨테이너 크기·콜드스타트 재검토 필요.

**시작점:**
1. `src/onjeon/compare.py:70` — `engine.expected_loss(p, lgd, deposit)` 호출부가 레퍼런스.
2. `api/main.py:85` `/api/decision`이 받는 body에 등기부 유래 필드(채권최고액·선순위·시세)가
   없다 — 입력 스키마 확장이 선행돼야 한다.
3. L2 없이 가는 경로도 검토: 지역·전세가율 기반 룰 테이블로 P(사고)를 근사하면
   `scikit-learn`을 배포에 안 넣어도 된다. 정확도 vs 컨테이너 크기 트레이드오프.

**Depends on / blocked by:** `/api/decision` 입력 스키마 확장. 등기부 파싱 결과를
API로 넘기는 경로(현재 업로드는 되지만 decision과 연결 안 됨).

**출처:** 2026-07-25 `/plan-eng-review` 아웃사이드 보이스가 발견, D5=A로 분리 결정.

---
