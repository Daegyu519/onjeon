# CLAUDE.md — 온전(穩全) 프로젝트 가이드

> KB Future Finance A.I. Challenge 출품작. 리스크 조정 주거비용 기반 청년 주거 의사결정 AI.
> 이 파일은 Claude Code 세션이 프로젝트 맥락을 즉시 파악하기 위한 기준 문서다.

## 한 줄 요약

**"이 집, 위험을 감안하면 전세가 월세보다 정말 싼가?"** — 등기부등본을 AI로 읽고, 보증금 미회수 위험을 원(₩) 단위 기대손실로 환산하여, 전세/월세/매수 3안의 *리스크 조정 세후 총비용*을 비교해주는 청년 주거 금융 의사결정 서비스.

- 기존 서비스 출력: "위험도 — 주의" (정성 등급, 정보 제공에서 종료)
- 온전의 출력: "이 매물은 미회수 기대손실 연 764만원(범위 93만~4,019만)을 반영하면 월세보다 연 736만원 비쌉니다" (의사결정)

> 2026-07-27 배포 경로 실측(관악구 봉천동 빌라 전용 40㎡·전세 2억·선순위 1.2억).
> **범위가 붙는 이유**: 사고확률이 공개 통계 4개 시점에서 1.35~14.51%로 움직였다.
> 점추정 하나만 내면 어느 시점 기준이냐가 숨는다. 페르소나·매물이 바뀌면 달라진다.

## 절대 원칙 (모든 구현·문서에 적용)

1. **LLM은 계산하지 않는다.** 숫자·판정은 결정론적 계산 엔진(L3)과 ML 모델(L2)이 담당. LLM은 문서 추출(L1), 파라미터 조작(L4), 해석·인용만 한다. 금융에서 숫자가 틀리면 안 된다.
2. **모든 출력에 원문 출처.** 등기부 조항 위치, 법령 조문, 공고 원문을 인용해야 한다.
3. **룰은 코드가 아니라 데이터.** 세법·정책상품 자격요건은 버전 태그가 붙은 JSON 룰 DB로 분리한다. "2026년 ○월 기준" 명기 필수.
4. **추출과 검증의 분리.** L0 파이프라인에서 추출 LLM과 검증 LLM은 반드시 분리하고, 경계값 테스트를 통과해야 룰 DB에 반영한다.
5. **한계를 먼저 말한다.** 집계 마진 보정의 생태학적 오류, 등기부 외 리스크(체납 등) 미커버 등 한계는 숨기지 않고 명시한다. 불확실하면 점추정 대신 범위를 낸다.
6. **`[확인]` 마커.** 문서에서 `[확인]`으로 표시된 수치·요강은 최신 기준으로 검증 전이므로, 확정된 사실로 취급하지 말 것. 검증 완료 시 마커를 제거하고 출처·기준일을 남긴다.

## 시스템 구조 (5계층)

```
L0  정책 룰 자동화 파이프라인 (오프라인) — 공고 → 자격요건 JSON 룰 DB
L1  문서 이해 — 등기부 PDF → LLM 비전 파싱 → 구조화 JSON
L2  리스크 예측 (ML + XAI) — 로지스틱 회귀 P(사고) + SHAP 설명
L3  결정론적 계산 엔진 (AI 아님, 의도된 설계) — 3안 세후 총비용 + E[Loss]
L4  에이전트 레이어 (LLM) — 해석·인용, what-if 번역기 (function calling)
```

핵심 수식: `전세 실질비용 = 명목비용(이자+기회비용) + E[Loss]`, `E[Loss] = P(사고) × LGD × 보증금`

상세: [docs/architecture.md](docs/architecture.md)

## 2개 코어 모듈

- **모듈 C — 계약 리스크 스캐너**: 등기부 PDF → 파싱 → 채권최고액·선순위 추출 → 경매 시 회수 예상액/미회수 위험액 산출 (L1+L2)
- **모듈 A — 주거 의사결정 엔진**: 전세/월세/매수 3안 세후 총비용 비교 + 정책상품 자격 판정(미자격 반증 포함) (L3+L4)

상세 설계: [docs/design.md](docs/design.md)

## 기술 스택 (MVP 데모 기준)

| 레이어 | 도구 |
|---|---|
| L1 문서 이해 | Claude/GPT 비전 API (이미지+프롬프트 → JSON) |
| L2 리스크 ML | 로지스틱 회귀 — **공개 통계 집계 마진 보정**(부동산테크 시군구 920관측)
|              | 학습이 아니다. 추론은 stdlib, 보정은 `scripts/calibrate_risk_model.py`(오프라인) |
| L3 계산 엔진 | Python 순수 함수 + pandas, 단위 테스트 필수 |
| L4 에이전트 | LLM API tool use (function calling) |
| L0 룰 파이프라인 | LLM API + JSON 스키마 검증 |
| 프론트 (배포) | React + Vite + ECharts (`web/`) — 시세 차트·동네 지도·조건 진단 |
| 프론트 (연구용) | Streamlit (`app.py`) — RAG·3안 비교 실험 전용, **배포 미포함** |
| API | FastAPI (`api/main.py`) — `web/dist`까지 한 포트에서 서빙 |

## 프로젝트 구조

```
idea/
├── CLAUDE.md            ← 이 파일
├── README.md            ← 프로젝트 소개 + 실행 방법
├── PROMPT.md            ← 세션 이어받기 프롬프트
├── TODOS.md             ← 대기 항목 (배경·현재상태·시작점까지 적는다)
├── pyproject.toml       ← 개발 의존성 (.venv, Python 3.12, uv 관리)
├── requirements-api.txt ← 컨테이너 런타임 최소 의존성 — numpy·pandas·sklearn 없음(함정 참조)
├── dev.sh serve.sh tunnel.sh  ← 개발 / 로컬 프로덕션 / 공개(ngrok 고정 도메인)
├── run.sh               ← 구 Streamlit 데모(:8501) 전용
├── Dockerfile render.yaml     ← 컨테이너 배포 폴백 경로
├── app.py               ← Streamlit 연구용 UI (RAG·3안 비교, 배포 미포함)
├── api/main.py          ← 배포 REST 계층 — 시세/지도/등기부/의사결정 4개 엔드포인트 + web/dist 서빙
├── web/                 ← 배포 프론트 (React+Vite). App.jsx=시세, MarketMap.jsx=지도, Decision.jsx=진단
├── scripts/             ← warm_cache.py · geocode_dongs.py · gen_fake_registers.py
│                          calibrate_risk_model.py(공개통계 보정) · check_api_deps.sh(컨테이너 검증)
├── docs/
│   ├── architecture.md  ← L0~L4 아키텍처 (설명 + 참조)
│   ├── design.md        ← 상세 설계도: 모듈 스펙, 수식, 데이터 스키마, 화면
│   └── workflow.md      ← 4주 MVP 워크플로우, 역할, 데모 시나리오
├── src/onjeon/
│   ├── llm.py           ← LLMClient / MockLLM / GeminiLLM / AnthropicLLM
│   ├── config.py        ← .env 로더 (키: .env.example 참조)
│   ├── display.py       ← 표시 계층 (만원 변환·인용 라벨은 여기서만)
│   ├── data_pipeline/   ← 데이터 수집 (실거래가 API, 낙찰가율 룰 생성기)
│   ├── rag/             ← 조항 색인 — Qdrant 하이브리드(dense+sparse RRF) + 골든셋 평가(eval.py)
│   │                       인용·검색 전용, 판정 금지. 임베딩: ONJEON_EMBED_MODEL(로컬 e5-large 권장)
│   │                       ⚠️ 배포 제품(api.main) 미포함 — app.py(Streamlit) 전용 연구 모듈.
│   │                       배포 경로의 인용은 rules JSON의 clause → eligibility가 담당한다.
│   ├── compare.py       ← 3안 비교 오케스트레이터 — app.py 전용. 위험 계산은 l3/risk.py에 위임
│   ├── decision.py      ← 배포 의사결정 오케스트레이터 (api.main이 쓰는 경로)
│   │                       전세vs월세 리스크조정 비교 + 적정주거비(RIR) + 금융지원 추천
│   ├── market/          ← 시세 추이·지도·캐시 — trends.py는 평당가를 **만원**으로 반환(함정 참조)
│   ├── register/parse.py ← 등기부 PDF 텍스트 파싱 (주소·면적·용도·채권최고액)
│   ├── rules_io.py      ← 버전 태그 룰 DB 로더
│   ├── l0/rule_pipeline.py  ← 공고 → 룰 JSON (추출/검증 LLM 분리 강제)
│   ├── l1/schema.py, parser.py  ← 스키마 게이트 + 등기부 파서
│   ├── l2/synth.py, model.py    ← 로지스틱 회귀/기여도. 계수는 공개 통계 보정(rules/risk_model_*)
│   │                       synth.py는 파이프라인 테스트용 픽스처 — 배포 계수를 만들지 않는다
│   ├── l3/engine.py, eligibility.py, affordability.py, recommend.py, risk.py
│   │                    ← 결정론 계산 + 자격 판정 + RIR 진단 + 상품 랭킹
│   │                       risk.py = 보증금 미회수 위험의 **단일 정의**(P→LGD→E[Loss]).
│   │                       compare.py·decision.py 둘 다 여기를 쓴다 — 따로 구현하지 말 것
│   ├── l4/agent.py      ← what-if 에이전트 (LLM은 조작만)
│   └── rules/           ← 세제·시장·낙찰가율·상품 룰 JSON (YYYY-MM 버전)
├── data/fixtures/       ← 페르소나·매물 2건·공고 샘플 (2건이 전부다 — 늘리기 전에 쓰는 곳부터 만들 것)
├── data/reference/      ← 리스크 모델 보정 원본 (Rtech 시군구 .xls 4개 시점). calibrate_risk_model.py의 유일한 입력
├── data/cache.db        ← 시세 SQLite 캐시 (WAL. 공개 배포는 이것만 읽는다)
└── tests/               ← pytest 스위트 (TDD, 380 tests)
```

원본 제안서: `KB_AI_Challenge_제안서_초안.md` — **로컬 전용, 저장소에 없다**(공개 저장소라
의도적으로 미추적). 저장소 루트에 파일이 보이면 그건 작업자 로컬 사본이다.

## 실행·테스트

```bash
# 최초 1회
uv venv --python 3.12 .venv
uv pip install -p .venv -e ".[dev,llm]"
( cd web && npm ci )
cp .env.example .env          # MOLIT_API_KEY 필수(시세 실데이터)

.venv/bin/python -m pytest    # 전체 380개
```

| 목적 | 명령 | 접속 |
|---|---|---|
| 개발 (핫리로드) | `./dev.sh` | http://localhost:5180 · API 문서 `:8000/docs` |
| 로컬 프로덕션 확인 | `./serve.sh` | http://localhost:8000 (프론트 빌드 + 단일 포트) |
| 외부 공개 (시연·심사) | `./tunnel.sh` | ngrok 고정 도메인. `url`로 주소 확인, `stop`으로 종료 |
| 구 Streamlit 데모 | `./run.sh` | http://localhost:8501 — 연구용, 배포 제품 아님 |

`./tunnel.sh`는 `ONJEON_PUBLIC_READONLY=1`로 뜬다(캐시만 읽고 국토부 API 미호출 — 1요청 최대 183회라 공개 경로가 키 쿼터를 소진시킬 수 있다). 캐시 갱신은 `scripts/warm_cache.py` 전담.

## 실측 함정

세션에서 실제로 밟은 것만 적는다. 추측은 넣지 않는다.

1. **`market/trends.py`는 평당가를 만원 단위로 반환한다.** 원(₩)으로 쓰려면 `×10000`이 필요하다. 빼먹으면 시세 2.24억이 22,385원이 되고 `engine.lgd`가 0.172 → **1.000으로 고정**, E[Loss]가 5.8배로 튄다. 예외도 `None`도 나지 않고 그럴듯한 큰 숫자만 나오므로 눈으로는 못 잡는다 — 경계 테스트가 유일한 방어선이다.
2. **`requirements-api.txt`에 numpy·pandas·scikit-learn이 없다** (커밋 `7485de9`, 의존성 11배 축소). `l2/model.py`는 이 셋을 모듈 최상단에서 import하므로 **컨테이너 경로에서 import 자체가 실패**한다. 배포 런타임에서 L2를 쓰려면 학습된 계수를 룰 JSON으로 빼고 추론은 `math.exp`로 해야 한다.
3. **`l3/recommend.py`는 룰의 필드를 `_CARRIED`에 적힌 것만 결과에 실어보낸다** (`terms`·`product_type`·`applies_to`·`source`). 룰 JSON에 새 필드를 넣고 호출측에서 읽으려 하면 조용히 빈값이 온다 — 예외가 아니라 **정책 혜택이 사라지거나 인용의 조항이 비는** 형태로 나타나 눈에 안 띈다. 이 함정에 두 번 당했다(`applies_to`, `source`). 룰에 호출측이 읽을 필드를 추가하면 `_CARRIED`와 `tests/test_eligibility.py::TestRecommendCarriesRuleMetadata`를 같이 갱신한다.
4. **실제 등기부 발급본은 끝에 '주요 등기사항 요약(참고용)'을 붙이고 을구의 유효 근저당을 되풀이한다.** 문서 전체를 `findall`로 훑으면 채권최고액이 **2배**가 되고, 그러면 `engine.lgd`의 회수 예상액이 0으로 깎여 LGD가 1.0에 고정된다(실측 E[Loss] 348만 → 660만원/년). `extract_senior_claims`는 요약 절 앞의 본문만 센다. **`data/fixtures/fake_registers`의 가짜 등기부에 이 절이 없어서 테스트 12개가 전부 통과하면서도 버그가 살아 있었다** — 픽스처가 실제 형식과 다르면 테스트는 아무것도 보증하지 않는다.
5. **배포 경로가 2개다.** `./tunnel.sh`(로컬 venv = pyproject 전체 의존성)와 컨테이너(`requirements-api.txt`). 의존성을 건드릴 때마다 **둘 다** 확인해야 한다. 컨테이너 검증:
   ```bash
   uv venv /tmp/api-check && uv pip install -p /tmp/api-check -r requirements-api.txt \
     && /tmp/api-check/bin/python -c "import api.main"
   ```
6. **등기부는 한 종류가 아니다 — 건물 등기부(단독·다가구·다중)엔 전용면적이 없다.** 표제부에 층별 면적이 여러 줄 나온다. 첫 `N㎡`를 집으면 **1층 면적을 전용면적이라 부르게 된다**(실측: 3층 다중주택에서 106.53㎡ → 시세 4.83억 추정, 원룸 25㎡ 기준 1.13억의 4.3배). 시세 과대 → LGD 과소 → **E[Loss] 과소평가**, 즉 위험한 집이 안전해 보이는 방향이다. `_extract_area`는 후보가 2개 이상이면 `None` + `area_note`를 낸다. 후보 목록을 화면에 보여주는 것도 금지 — 다중주택 임차인은 층이 아니라 **방**을 빌리므로 어느 후보를 골라도 오답이다.
7. **"못 읽음"을 예외로 올리면 문서 전체를 버린다.** `extract_fields`가 면적 실패에 `ValueError`를 던졌더니, OCR을 이미 돌린 뒤에도 같은 예외가 나서 **잘 읽힌 채권최고액 1.2억까지 통째로 사라지고 422**가 됐다(건물 등기부 촬영본이 전부 수동 입력으로 떨어졌다). 지금은 어떤 필드도 예외를 올리지 않고 `None` + 사유를 남기며, OCR 폴백 여부는 `is_useless()`(주소·근저당·면적을 하나도 못 건졌는가)로 판단한다.
8. **OCR은 숫자 뒤에 자릿수를 덧붙인다.** ㎡를 숫자로 읽어 `70.94`가 `70.941`·`70.9407`이 됐다. 등기부 면적은 항상 소수 2자리이므로 `_AREA_RE`가 딱 2자리에서 끊어 잡음을 자른다. 오른쪽 앵커가 없는 숫자 정규식은 OCR 경로에서 전부 이 위험이 있다. 렌더 배율은 3이 최적 — 2는 열화된 촬영본에서 **채권최고액을 통째로 놓쳤고**, 4는 깨끗한 스캔에서 오히려 면적을 놓쳤다(과확대 아티팩트).

## MVP 범위 (학부 3인 × 4주)

수직 슬라이스 원칙 — 페르소나 1명(김서연, 26세), 매물 2건(위험 빌라 vs 안전 오피스텔)으로 전 레이어 관통. 주차별 계획과 역할 분담은 [docs/workflow.md](docs/workflow.md) 참조.

## 코드 작성 시 컨벤션

- L3 계산 함수는 순수 함수로 작성하고 모든 함수에 단위 테스트를 붙인다. 세제 항목은 엑셀 명세 → 코드 순서로 구현한다.
- L1/L0의 LLM 추출 결과는 JSON 스키마로 필수 필드를 검증한 뒤에만 하위 레이어에 넘긴다.
- 금액 단위는 원(₩) 정수로 통일한다. 만원 단위 변환은 표시 계층에서만 한다.
- 데이터 소스(실거래가 API, 낙찰가율 통계 등)에는 조회 기준일을 함께 저장한다.

## 도메인 용어

| 용어 | 의미 |
|---|---|
| 채권최고액 | 근저당권이 담보하는 최대 채권액 (등기부 을구) |
| 선순위 임차권 | 대상 임차인보다 먼저 배당받는 임차 보증금 |
| 낙찰가율 | 경매 낙찰가 / 감정가(시세) 비율 |
| LGD | Loss Given Default — 사고 발생 시 보증금 대비 손실률 |
| 전세가율 | 전세보증금 / 매매시세 비율 (위험 피처) |
| 미자격 반증 | 자격 미달 시 어느 조항·얼마 초과인지 + 차선 상품 제시 |

## 스킬·플러그인·워크플로우 라우팅 규칙 (사용자 지정, 2026-07-24)

이 흐름을 기본 규제로 따른다:

- **계획 수립·검토**: 브레인스토밍(superpowers:brainstorming) → 계획 → **plan-ceo-review**(가치·전제·리스크) → **plan-eng-review**(CTO/엔지니어 관점: 구현 경계·테스트·에러경로). CEO 리뷰 후에는 반드시 Eng 리뷰를 거친다.
- **실행**: 가능한 작업은 **subagent를 구성해 병렬 처리**한다.
- **코딩 출력물**: 플러그인 **`ponytail`을 반드시 거쳐** 나온다. (미설치/미확인 시 사용자에게 확인하고, 없는 것을 통과한 척하지 않는다.)
- **UI/UX 수정**: **ui-ux-pro · frontend-design · apple-design** 스킬/플러그인을 사용해 진행한다.
- **기억**: 계획·작업·결정은 claude-mem 및 파일 메모리에 남긴다.
- **테스트**: 현재 세션은 사용자 지시로 테스트 미작성 보류. 단 **금융 결정 로직(engine·affordability·eligibility)은 테스트 재개 권고**(숫자 틀리면 안 됨).
