# 설계 스펙 — 주거 의사결정 슬라이스 (적정 주거비 진단 + 청년 금융지원 추천)

- 작성일: 2026-07-24
- 상태: 설계 초안 (plan-ceo-review·plan-eng-review 대기)
- 관련: [CLAUDE.md](../../../CLAUDE.md) 절대원칙 — LLM 계산 안 함(L3 결정론), 원(₩) 정수, 룰=데이터, 미자격 반증, `[확인]`

## 1. 목표 (사용자 정의 2개)

1. **월세·관리비·생활비를 종합 고려해 "적정 주거비"를 제안** → 합리적 주거 의사결정 지원.
2. **소득·자산·희망지역을 분석해 이용 가능한 청년 금융지원 제도·주거 금융정보를 추천.**

## 2. 확정 결정 (브레인스토밍)

- **적정 주거비 기준 = RIR 상한.** 적정 월주거비 = 월소득 × RIR상한(기본 30%, 룰 데이터로 조정). 생활비는 RIR이 암묵 반영(별도 입력 불필요, 가처분 표시는 부가).
- **범위 = 통합 얇은 수직 슬라이스.** 프로필 1건 → ①주거비 진단 + ②금융지원 추천을 둘 다 얇게 관통.
- **금융제도 = 핵심 국가상품 5~6종.** 지자체·희망지역별 상품은 이후.

## 3. 현 자산 재사용 (신규 최소화)

- ✅ `l3/engine.py`: `annual_cost_jeonse/wolse/buy`, `lgd`, `expected_loss` — 3안 총비용.
- ✅ `l3/eligibility.py`: `evaluate(user, rule)` — 자격 판정 + **미자격 반증(gap)**.
- ✅ `compare.run_comparison`: 3안 비교 오케스트레이션(비활성 UI였음, 코드 보존).
- ✅ `rules/products/*.json`: 정책상품 룰(현 2종) + `rules_io` 로더.
- ✅ 신규 파이프라인: `register/parse`(등기부→주소·용도·면적), `market/trends`(시세).

## 4. 신규·확장 범위

### 4.1 사용자 프로필 (신규 입력)
`Profile = { monthly_income_krw, assets_krw, age, region(시군구), is_homeless(무주택), works_at_sme, married? }`
- 프론트 폼으로 수집. 매물 조건은 등기부/시세 파이프라인 + 후보 임대조건(전세보증금 또는 월세+보증금+관리비).

### 4.2 적정 주거비 진단 (Goal 1) — `l3/affordability.py`(신규, 순수함수)
- `monthly_housing_cost(wolse, maintenance, deposit, opp_rate)` = 월세 + **관리비** + 보증금 월환산 기회비용.
  - **관리비를 월세 총비용에 새로 반영**(현 엔진 미반영分 보강).
- `appropriate_rent(monthly_income, rir_cap)` = 월소득 × rir_cap.
- `diagnose(...)` → `{ housing_cost, appropriate, over_under_krw, rir_actual }`. 초과/여유를 원 단위로.
- RIR 상한은 `rules/market_params`에 `rir_cap`(기본 0.30, 기준일 명기) 추가.
- 기존 3안 비교(`run_comparison`)와 연결: 각 안의 월환산 주거비 vs 적정선.

### 4.3 청년 금융지원 추천 (Goal 2) — `l3/recommend.py`(신규) + 룰 확장
- **상품 룰 2→5~6종 확장**(`rules/products/`): 버팀목 전세, 중기청 전세(기존), 디딤돌 매입, 청년월세지원, 청년도약계좌, (LH 청년전세임대) — 각 `[확인]` 기준일·출처·boundary_tests.
- `recommend(profile, products)`:
  - 각 상품 `eligibility.evaluate` → 자격/미자격.
  - 자격 상품: 한도·금리 유리 순 랭킹 + 조항 인용.
  - 미자격 상품: **반증(gap)** — 어느 조항 얼마 초과 + 차선 상품.
- 희망지역: 국가상품은 지역 무관, 보증금 상한 등 지역 파라미터만 반영.

### 4.4 API (FastAPI 확장)
- `POST /api/decision` : `{profile, listing}` → `{ affordability, comparison(3안), recommendations }`. compare/engine/eligibility/affordability/recommend 재사용, LLM 없음.

### 4.5 프론트 (Vite, 기존 시세 화면에 통합)
- "내 조건" 프로필 폼 → **주거비 진단 게이지**(적정선 대비 초과/여유) + **3안 비교 카드** + **금융지원 카드**(자격/한도/금리/조항 인용, 미자격은 반증).
- 등기부·시세 컨텍스트와 한 화면 공유.

## 5. 범위 밖 (이번 슬라이스)
- 지자체·지역별 청년 상품, 생활비 실입력 정밀 모델, 세대/혼인 복합 시나리오, 신용점수 기반 금리.

## 6. 원칙·한계
- L3는 순수 함수(단위테스트 — 단, 현재 세션 사용자 지시로 테스트 보류 상태이면 명시), 원 정수, 표시만 만원.
- 룰은 버전 태그 JSON, `[확인]` 미검증 표시. 미자격은 반드시 반증.
- 한계 명시: 상품 요건은 기준일 스냅샷, 실제 승인은 기관 심사.

## 7. 구현 접근 (확정) + CEO 리뷰 리포트

**접근 = B (이상적).** `run_comparison`을 페르소나·용도 하드코딩(빌라 vs 오피스텔 고정)에서 분리해 **범용 3안 엔진** `compare_options(profile, options)`로 리팩터한 뒤, 그 위에 `affordability`(RIR)·`recommend`를 구축. **모드 = HOLD SCOPE**(해커톤 MVP — 선택 접근을 견고히, 추가 확장 없음).

### CEO 리스크 (반드시 반영)
1. **[금융 correctness — 최우선]** 상품 룰 5~6종의 금리·한도·자격은 실제 금융사실. 틀리면 사용자 위해. 각 criterion에 `[확인]` 출처+기준일+`boundary_tests` 필수 (CLAUDE.md 원칙1: 숫자 틀리면 안 됨).
2. **[리팩터 회귀]** `run_comparison` 리팩터가 기존 compare 테스트·보존 코드를 깨면 안 됨 — 구 데모 케이스 결과 **동등성 유지**를 회귀로 확인.
3. **[테스트 공백 — CEO 최대 우려]** 세션 지시로 TDD 보류 중이나, affordability·eligibility·engine은 **금융 결정 로직**. 미검증 금융계산 배포는 최대 리스크 → 이 3개 모듈만은 **테스트 재개 강력 권고**.
4. **[적정선 규범성]** RIR cap 출처·기준일 명시, "적정"이 규범적 판단임을 UI에 노출(신뢰).
5. **[입력 shadow path]** 프로필 nil / 음수 소득 / 자산 0 / 미지원 지역 에러 경로 명시.

→ plan-eng-review로 구현 경계·테스트·에러경로를 추가 검증.

## 8. Eng(CTO) 리뷰 + 최종 실행 결정

**단계 분리 (확정, HOLD SCOPE).** 각 단계 독립 검증·커밋, subagent 병렬은 단계 내 독립 파일에만:
1. `compare_options(profile, options)` 리팩터 — run_comparison의 페르소나·용도 하드코딩 제거. **기존 compare 테스트 패리티 필수**(구조 변경만, 행동 불변).
2. `l3/affordability.py` — RIR 적정선 + 관리비 반영 월주거비.
3. 상품 룰 5~6종 + `l3/recommend.py` — 자격 랭킹 + 미자격 반증.
4. `POST /api/decision` — 프로필+매물 → 진단·비교·추천.
5. 프론트(프로필 폼·진단 게이지·금융카드). UI는 ui-ux-pro·frontend-design·apple-design 사용.

**테스트 정책 (사용자 확정).** 금융 로직(engine·affordability·recommend·상품룰 boundary)에 한해 **이번엔 테스트 작성 허가**. 단 **검증 완료 즉시 테스트 소거**. 그리고 **실입력 형태의 데이터셋**(샘플 프로필·매물)을 제작해 사용자에게 전달 → 사용자가 직접 입력해 확인.

**Eng 리스크 (반영):** ①리팩터-먼저(구조/행동 분리) ②compare_options 계약 — 옵션별 리스크 주입, 매수엔 E[Loss] 없음 ③상품룰 boundary 실행 ④/api/decision shadow path(nil·음수소득·자산0·미지원지역) 명명 400 ⑤단위 원(₩) 정수 통일(월/연 소득 일치, 보증금 월환산=deposit×opp_rate/12).

**코딩 출력 게이트:** 사용자 규칙상 코드 출력은 `ponytail` 플러그인을 거쳐야 함 — 현재 미확인/미설치. Phase 1 착수 전 해소 필요.
