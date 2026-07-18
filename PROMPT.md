# 온전(穩全) 개발 이어받기 프롬프트

> 이 프롬프트는 지금까지의 문서화·개발 착수 상태를 그대로 이어받아 MVP를 완성하기 위한 자기완결형 지시문이다.
> 새 Claude Code 세션(또는 팀원)에게 그대로 붙여넣어 사용한다. 작업 디렉토리: `/Users/odaegyu/Desktop/idea`

---

## 프로젝트

**온전(穩全)** — KB Future Finance A.I. Challenge 출품작. 등기부등본을 AI로 읽고, 보증금 미회수 위험을 원(₩) 단위 기대손실로 환산하여, 전세/월세/매수 3안의 리스크 조정 세후 총비용을 비교하는 청년 주거 금융 의사결정 서비스.

핵심 출력: "이 매물은 미회수 기대손실 연 180만원을 반영하면 월세보다 연 80만원 비쌉니다" (정성 등급이 아닌 의사결정).

## 기준 문서 (이미 작성 완료 — 반드시 먼저 읽을 것)

| 파일 | 내용 |
|---|---|
| `CLAUDE.md` | 절대 원칙 6가지, 기술 스택, 코드 컨벤션, 도메인 용어 |
| `docs/architecture.md` | L0~L4 5계층 아키텍처, 계층별 입출력/제약, 설계 트레이드오프 |
| `docs/design.md` | 모듈 C/A 스펙, E[Loss] 수식, L1 추출 JSON 스키마, 룰 DB 스키마, 화면 설계 |
| `docs/workflow.md` | 4주 계획, 역할 분담, 데모 시나리오, 제출 전 체크리스트 |

## 절대 원칙 (요약 — 위반 금지)

1. **LLM은 계산하지 않는다.** 숫자·판정은 L3(결정론)·L2(ML). LLM은 추출(L1)·조작(L4)·해석만.
2. **모든 출력에 원문 출처** (등기부 `source_loc`, 법령 조항, 공고 원문).
3. **룰은 데이터** — 버전 태그 JSON 룰 DB, "2026년 ○월 기준" 명기.
4. **추출 LLM ↔ 검증 LLM 분리** + 경계값 테스트 통과 후에만 룰 DB 반영.
5. **한계 선명시** (합성 데이터, 등기부 외 리스크 미커버 등).
6. **`[확인]` 마커** = 미검증 수치. 확정 사실로 취급 금지.
7. **TDD 필수**: 테스트 먼저 작성 → 실패 확인(RED) → 최소 구현(GREEN) → 리팩터. L3는 전 함수 단위 테스트.
8. 금액은 원(₩) 정수. 만원 변환은 표시 계층에서만. 데이터 소스에 조회 기준일 저장.

## 현재 개발 상태 (여기까지 완료됨)

- 문서 4종 작성 완료 (위 표).
- `uv`로 Python 3.12 가상환경 생성: `.venv` (활성화: `source .venv/bin/activate`, 실행: `.venv/bin/python`)
- `pyproject.toml` 작성 완료, 의존성 설치 완료: pandas, numpy, scikit-learn, streamlit, jsonschema, matplotlib, pytest, anthropic.
  - ⚠️ **shap은 설치 실패** (llvmlite 빌드 오류) → L2 설명은 **계수 기반 기여도 폴백**(`coef × (x − 학습평균)`)으로 구현할 것. shap은 optional extra `[xai]`로 남겨둠.
- 디렉토리 스캐폴드 생성 완료 (아직 전부 빈 폴더):

```
src/onjeon/{l0,l1,l2,l3,l4}/   # 파이썬 패키지 (모듈 미작성)
src/onjeon/rules/products/     # 룰 DB JSON (미작성)
data/fixtures/                 # 매물·페르소나 픽스처 (미작성)
tests/                         # 테스트 (미작성)
```

- git 저장소 아님 (사용자가 요청하면 init).

## 남은 작업 — 이 순서로 TDD로 구현하라

### 1. 데이터 파일 생성

- `src/onjeon/rules/tax_rules_2026-07.json` — 월세 세액공제(조특법 §95-2: 총급여 5,500만 이하 17%, 8,000만 이하 15%, 연 월세 한도 1,000만원 `[확인]`), 취득세율 0.011, 보유세 추정율 0.0015, 중개보수율 0.005 — 모두 `clause`·`[확인]` 표기 포함.
- `src/onjeon/rules/market_params_2026-07.json` — 전세대출금리 0.035, 매수대출금리 0.04, 기회비용수익률 0.04(청년도약계좌 `[확인]`).
- `src/onjeon/rules/auction_rates_2026-07.json` — 지역·유형별 낙찰가율 (관악구 빌라 0.78, 오피스텔 0.85 `[확인: 법원경매정보]`).
- `src/onjeon/rules/products/youth-jeonse-loan-2026-07.json` — 페르소나가 **자격 통과**하는 상품 (age≤34, 소득≤5,000만, 자산≤3.37억, 보증금≤3억; 각 criterion에 `clause` + `boundary_tests` 포함 — docs/design.md §5 스키마 준수).
- `src/onjeon/rules/products/sme-youth-jeonse-2026-07.json` — 페르소나가 **미자격**인 상품 (소득≤3,500만 → 100만원 초과 탈락, `alternatives: ["youth-jeonse-loan-2026-07"]`) — 미자격 반증 데모용.
- `data/fixtures/persona_kim.json` — 김서연: age 26, 연소득 36,000,000, 자산 30,000,000, 거주예정 4년.
- `data/fixtures/register_risky_villa.json` — L1 추출 결과 형태(docs/design.md §2 스키마): 관악구 빌라, 시세 1.5억, 전세보증금 1.2억(전세가율 80%), 을구 근저당 채권최고액 7,200만(`source_loc: 을구 3번` 포함), 깡통전세 신호.
- `data/fixtures/register_safe_officetel.json` — 오피스텔, 시세 2억, 보증금 1,000만/월세 65만, 근저당 없음.
- `data/fixtures/announcement_sample.txt` — L0 라이브 추출 데모용 정책 공고 텍스트 1건.

### 2. L3 계산 엔진 (`src/onjeon/l3/`) — TDD, 최우선

`tests/test_engine.py` 먼저 작성 → RED 확인 → 구현. API:

```python
split_funding(amount_needed, user_assets) -> (own, loan)
annual_cost_jeonse(*, deposit, user_assets, loan_rate, opportunity_rate, e_loss) -> int
  # = loan×loan_rate + own×opportunity_rate + e_loss
annual_cost_wolse(*, deposit, monthly_rent, annual_income, user_assets, loan_rate, opportunity_rate, tax_rules) -> int
  # = 연월세 − 세액공제(구간·한도 적용) + 보증금 자금비용
annual_cost_buy(*, price, user_assets, loan_rate, opportunity_rate, stay_years, tax_rules) -> int
  # = 취득세/중개보수(거주연수 상각) + 보유세 + 이자 + 기회비용
lgd(*, market_price, auction_rate, senior_claims, deposit, insured=False) -> float
  # = 1 − min(max(시세×낙찰가율 − 선순위, 0), 보증금)/보증금, [0,1] 클램프, insured→0.0
expected_loss(p_accident, lgd_value, deposit) -> int
```

검증용 기대값 예시: deposit 1.2억·자산 3,000만·전세금리 3.5%·기회 4%·E[Loss] 180만 → 615만/연. 월세: 65만×12=780만 − 공제 132.6만(17%) + 보증금 1,000만×4%=40만 → 687.4만/연.

`tests/test_eligibility.py` → `src/onjeon/l3/eligibility.py`:

```python
check_criterion(value, op, limit) -> bool   # ops: <=, >=, ==, in
evaluate(user, rule) -> {eligible, failed: [{field, op, limit, actual, gap, clause}], alternatives, version}
```

미자격 시 `gap`(얼마 초과)과 `clause`(조항) 필수 — 미자격 반증의 근거.

### 3. L1 스키마 게이트 (`src/onjeon/l1/schema.py`) — TDD

jsonschema 기반 `REGISTER_SCHEMA`(docs/design.md §2), `validate_extraction(doc) -> [errors]`, `gate(doc)`(실패 시 `ExtractionInvalid` — **통과 전 하위 레이어 전달 금지**), `senior_claims(register) -> int`(말소 안 된 을구 채권최고액 합 + 선순위 임차보증금). 모든 을구/갑구 항목에 `source_loc` 필수.

### 4. LLM 추상화 (`src/onjeon/llm.py`)

`LLMClient` 프로토콜(`complete(prompt, *, system=None, images=None) -> str`), `MockLLM(responses)`(순차 반환, `.calls` 기록 — API 키 없이 전체 데모 가능해야 함), `AnthropicLLM`(anthropic SDK, 키는 `ANTHROPIC_API_KEY` 환경변수, lazy import). **⚠️ Anthropic 클라이언트 작성 전 `claude-api` 스킬(사용 가능 시)로 최신 모델 ID·SDK 사용법 확인할 것.**

### 5. L1 파서 (`src/onjeon/l1/parser.py`) — TDD (MockLLM으로)

등기부 이미지→JSON 추출 프롬프트(표제부/갑구/을구 구조 명시) + `parse_register(images, llm)` → JSON 파싱(``` 펜스 처리) → `gate()` 통과 후 반환.

### 6. L2 리스크 모델 (`src/onjeon/l2/`) — TDD

- `synth.py`: `generate(n, seed)` — 피처 [전세가율, 근저당/시세비, 빌라여부, 낙찰가율], 진짜 로지스틱 모형(계수 예: +5.0, +3.0, +0.8, −2.0, 절편 −5.5)에서 라벨 생성. 같은 seed → 동일 결과(테스트).
- `model.py`: `train(df) -> RiskModel`, `predict_proba(x: dict) -> float`, `explain(x) -> {base_logit, contributions: [(피처, 기여도)], p}` — 기여도 = `coef×(x−학습평균)`, 합 + base_logit ≈ logit(p) 검증 테스트. **합성 데이터임을 출력에 명시하는 필드 포함** (`"data_note": "합성 데이터 — 구조 시연 목적"`).

### 7. L0 룰 파이프라인 (`src/onjeon/l0/rule_pipeline.py`) — TDD (MockLLM으로)

`extract_rule(공고, llm)` → 룰 JSON, `verify_rule(rule, 공고, llm)` → `{consistent, confidence, issues}`, `run_boundary_tests(rule)` (eligibility.check_criterion 재사용), `pipeline(공고, extract_llm, verify_llm)` — **extract_llm과 verify_llm이 같은 객체면 ValueError** (분리 원칙), confidence low → `needs_human=True`, 경계값 테스트 실패 → 반영 거부.

### 8. L4 what-if 에이전트 (`src/onjeon/l4/agent.py`) — TDD (MockLLM으로)

`WhatIfAgent(llm, base_params, tools)` — LLM이 JSON 액션(`{"action":"call_tool","tool":"run_comparison","params_patch":{...}}` / `{"action":"final","answer":...}`)을 내면 파라미터 병합 → L3 재실행 → 결과를 LLM에 되돌려 해석. **LLM 응답의 숫자는 반드시 tool 결과에서 온 것** — 계산 금지 원칙의 코드화. 최대 반복 가드.

### 9. 수직 슬라이스 통합 테스트 (`tests/test_vertical_slice.py`)

픽스처 로드 → 스키마 게이트 → senior_claims → L2 P(사고)(위험 빌라 > 안전 오피스텔 확인) → LGD → E[Loss] → 3안 비용 → **위험 빌라는 "월세 유리", 인용용 `source_loc` 존재** 단언.

### 10. Streamlit UI (`app.py`)

매물 픽스처 선택 → 3안 막대(전세 막대 위 기대손실 스택) → 기여도 워터폴(계수 폴백) → 근거 패널(등기부 을구 위치·데이터 출처·기준일) → 자격 판정 카드(자격/미자격 반증/차선 상품) → what-if 입력(키 없으면 MockLLM 데모 경로). L0 라이브 추출 탭: 공고 텍스트 붙여넣기 → 룰 JSON → 자격 판정 즉시 갱신.

### 11. 마무리

`.venv/bin/python -m pytest` 전체 통과 확인 → `docs/workflow.md`의 제출 전 체크리스트 대조 → README에 실행 방법(`streamlit run app.py`) 추가.

## 검증 기준 (완료 정의)

- 전 테스트 통과, L3 전 함수 단위 테스트 존재
- 위험 빌라 vs 안전 오피스텔이 UI에서 서로 다른 결론
- API 키 없이(MockLLM) 데모 전 구간 동작
- 모든 출력 수치에 출처·기준일 표시
