<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/banner-dark.png">
  <img alt="온전 穩全 — 등기부등본을 읽고 보증금 미회수 위험을 원(₩) 단위 기대손실로 환산합니다. 정성 등급 '위험도 — 주의'가 '연 442만원'으로 바뀝니다." src="docs/screenshots/banner-light.png" width="840">
</picture>

![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React_+_Vite-61DAFB?style=flat-square&logo=react&logoColor=black)
![데이터](https://img.shields.io/badge/데이터-국토부·법제처·금감원-F4B400?style=flat-square)
![tests](https://img.shields.io/badge/tests-555-4C9A2A?style=flat-square)

### 이 집, 위험을 감안하면 전세가 월세보다 정말 싼가?

![결론 화면](docs/screenshots/01-answer.png)

**혜택만 반영하면 전세가 연 29만원 싸지만, 미회수 기대손실을 얹으면 결론이 뒤집혀 연 414만원 비쌉니다.**

</div>

<details>
<summary>이 숫자를 만든 조건 — 2026-08-01 배포 경로 실측</summary>

<br>

관악구 빌라 · 전용 40㎡ · 전세 2억 / 월세 보증금 2,000만 + 월 55만 · 선순위 채권최고액 1.2억 ·
4년 거주 · 만 27세 · 월소득 280만 · 보유자산 2,000만.
시세는 국토부 실거래 캐시의 관악구 평당가(2,396만원, 2026-06)로 추정.

</details>

---

## 기존 진단과 무엇이 다른가

|  | 기존 리스크 진단 | **온전** |
|---|---|---|
| 출력 | 위험도 — 주의 | 미회수 기대손실 **연 442만원** |
| 형태 | 정성 등급 | 원(₩) 금액 |
| 다음 행동 | 계약할지는 여전히 본인 몫 | 전세·월세 중 **어느 쪽이 얼마나 유리한지** |
| 불확실성 | 등급 하나 | 범위 + 무엇이 흔들리면 뒤집히는지 |
| 근거 | 대체로 비공개 | 계산식·요율·**법령 원문**을 화면에 |

등급을 받아도 계약 여부는 본인이 판단해야 합니다. 온전은 그 등급을 **금액**으로 바꿔서, 전세와 월세를 같은 자로 잽니다.

## 숫자를 어떻게 만드나

### 항목별로 쪼갭니다

![항목별 연비용](docs/screenshots/02-breakdown.png)

전세를 비싸게 만든 것은 대출이자가 아니라 **미회수 기대손실 442만원** 한 줄입니다. 그 줄이 없으면 전세가 이깁니다.

### 그 442만원의 출처까지 함께

<img alt="근거 패널 — 사고확률 4.19% × 미회수율 52.7% × 보증금 2억원 = 442만원. 회수 예상액과 시세 추정 근거, 범위 35만~4,418만원을 함께 표시한다." src="docs/screenshots/03-evidence.png" width="632">

$$E[Loss] = P(사고) \times LGD \times 보증금$$

회수 예상액은 `시세 × 낙찰가율 − 선순위`로 계산하고, 쓰인 시세·낙찰가율·선순위를 전부 화면에 답니다.

> [!NOTE]
> **범위가 붙는 이유.** 사고확률이 공개 통계 4개 시점에서 1.16~11.63%로 움직였습니다.
> 점추정 하나만 내면 "어느 시점 기준이냐"가 숨습니다. 등기부를 올리면 동 단위로 좁혀져 범위가 줄어듭니다.

### 동네 시세는 지도로

![동네 지도](docs/screenshots/04-map.png)

서울 법정동별 평당가. 색이 진할수록 비싸고 원이 클수록 거래가 많습니다. 동네 간 가격 차가 10배를 넘어 **색은 로그 눈금**입니다 — 선형이면 최고가 몇 곳이 스케일을 독점해 나머지가 전부 같은 색으로 뭉칩니다. 거래 5건 미만인 동은 평균 대신 회색으로 두고 건수만 보여줍니다.

## 왜 필요한가

청년은 인생 최대 금액의 금융 의사결정(보증금)을 가장 적은 정보와 경험으로 내립니다. 위험 정보(전세사기·보증사고)와 비용 정보(정책상품·세제)가 서로 다른 서비스에 분리되어 있어, 정작 필요한 질문 — *"이 위험을 감안한 실질 비용은 얼마인가"* — 에는 아무도 답하지 않습니다.

## 어떻게 동작하는가

<div align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshots/arch-dark.png">
  <img alt="온전 아키텍처 — 등기부 PDF·소득·자산이 L1 문서 이해, L2 리스크 예측, L3 결정론 계산 엔진을 거쳐 결론으로 나온다. L0 룰 파이프라인이 L3에 룰 JSON을 공급하고, L4 에이전트는 결론에 문단을 덧붙이는 선택 경로다." src="docs/screenshots/arch-light.png" width="900">
</picture>
</div>

가운데 굵은 상자 하나만 숫자를 만듭니다. **L3는 순수 함수고 AI가 아닙니다** — 의도된 설계입니다. 금융에서 숫자가 틀리면 안 되므로, 재현되지 않는 것에 계산을 맡기지 않습니다. LLM은 문서에서 읽고(L1 — 그마저도 지금은 텍스트 파싱입니다), 룰을 만들고(L0, 오프라인), 다 끝난 결과를 설명합니다(L4).

점선으로 매달린 **L4는 꺼져도 됩니다.** 키가 없거나 공개 배포면 `None`이 오고 문단만 빠집니다. 화면도 숫자도 그대로입니다.

<details>
<summary>계층별 구현 — 표로 보기</summary>

<br>

| 계층 | 하는 일 | 구현 |
|:---:|---|---|
| **L0** | 법령·공고 → 자격요건 JSON 룰 DB | 법제처 API(조문·별표) + 사람 검수. 오프라인 |
| **L1** | 등기부 PDF → 채권최고액·선순위·면적 | pdfplumber 텍스트 파싱 + 취소선 제거, 실패 시 OCR 폴백 |
| **L2** | 사고확률 P(사고) + 기여도 분해 | 로지스틱 회귀. 공개통계 집계 마진 보정, 추론은 stdlib |
| **L3** | 세후 총비용 + E[Loss] + 등기부 등급 | 순수 함수. **AI 아님 — 의도된 설계** |
| **L4** | 해석 문단, what-if 번역 | LLM. 실패하면 `None`이고 화면은 그대로 |

L1은 비전 LLM이 아닙니다. 원안([docs/design.md](docs/design.md))엔 그렇게 적혀 있지만 구현은 텍스트 파싱입니다. 계획과 구현이 갈라진 지점 전체는 [docs/architecture.md](docs/architecture.md) §1 표에 있습니다.

</details>

## 문서 안내

| 문서 | 내용 | 이런 질문에 답함 |
|---|---|---|
| [docs/summary.md](docs/summary.md) | **과제 요약** — 제출·발표용 (150자/400자/전문) | "이 과제가 뭔데?" |
| [CLAUDE.md](CLAUDE.md) | 프로젝트 원칙·구조·컨벤션 + **실측 함정 12건** | "이 프로젝트의 규칙은?" |
| [docs/problem.md](docs/problem.md) | 문제 정의 — 가치·경쟁·범위 밖·한계 | "왜 이걸 만드는가? 뭘 안 푸는가?" |
| [docs/architecture.md](docs/architecture.md) | **as-built** 설계도 — 계층별 실제 구현, 데이터 흐름 | "지금 실제로 어떻게 돌아가는가?" |
| [docs/design.md](docs/design.md) | 원안(2026-07-19) — 모듈 스펙, 수식, 스키마, 화면 | "무엇을 만들 **계획**이었나?" |
| [docs/workflow.md](docs/workflow.md) | 4주 MVP 계획, 역할 분담, 데모 시나리오 | "누가 언제 무엇을 하는가?" |
| [docs/data-pipeline.md](docs/data-pipeline.md) | 외부 데이터 출처·수집 스크립트·갱신 주기 | "데이터는 어디서 어떻게 채우는가?" |

## 실행 방법

FastAPI 단일 서버 + React(Vite) 프론트입니다. `web/dist`를 FastAPI가 `/api`와 함께 한 포트에서 서빙합니다.

```bash
# 최초 1회 — 의존성
uv venv --python 3.12 .venv
uv pip install -p .venv -e ".[dev,llm]"
( cd web && npm ci )

# API 키 — 시세는 MOLIT_API_KEY가 있어야 실데이터가 나온다
cp .env.example .env   # MOLIT_API_KEY(필수), FSS_API_KEY·GEMINI·ANTHROPIC(선택)

# 전체 테스트 555개
.venv/bin/python -m pytest
```

목적에 맞는 것 하나만 쓰면 된다.

| 목적 | 명령 | 접속 |
|---|---|---|
| 개발 (핫리로드) | `./dev.sh` | http://localhost:5180 · API 문서 `:8000/docs` |
| 로컬 프로덕션 확인 | `./serve.sh` | http://localhost:8000 |
| 외부 공개 (시연·심사) | `./tunnel.sh` | 고정 URL (`./tunnel.sh url`로 확인, `stop`으로 종료) |

`./run.sh`는 구 Streamlit 데모(`app.py`, :8501)다. 전세/월세 비교·시세 차트·동네 지도는 위 FastAPI 경로에만 있다.

### 화면 구성

상단 탭 세 개다.

1. **전세 vs 월세** (메인) — 두 집의 조건과 내 소득·자산을 넣으면 리스크 조정 연비용 비교, 적정 주거비(RIR) 진단, 받을 수 있는 청년 금융지원(미자격 시 어느 조항에서 얼마 초과인지 반증까지)이 나온다. 등기부 PDF를 올리면 지역·유형·전용면적·선순위 채권최고액을 자동으로 채운다(스캔본은 OCR로 읽고, 값이 틀릴 수 있어 확인 후 적용). 금액 칸은 `1억 2천 3백만원`처럼 한글 단위로 써도 된다.
2. **근거** — 위 숫자를 만든 계산식·요율·법령 원문. 항목을 누르면 해당 계산식으로 이동한다.
3. **동네 지도** — 서울 법정동별 평당가 버블. 버블을 누르면 그 동네, 구 경계를 누르면 그 구 전체의 시세 흐름 차트가 그 자리에 열린다.

### 시세 캐시 워밍 (외부 API를 호출하는 유일한 경로)

`./tunnel.sh`는 **읽기 전용**으로 뜬다(`ONJEON_PUBLIC_READONLY=1`). 인증 없는 공개 경로가 국토부 API를 직접 타면 1요청이 최대 183회(5년=61개월×3종) 호출을 유발해, 누구나 운영자의 실명 인증 서비스키 쿼터를 소진시킬 수 있기 때문이다. 그래서 공개 전에 캐시를 채운다.

```bash
# 기본: 관악구·빌라 1년
.venv/bin/python scripts/warm_cache.py
# 원하는 범위로
.venv/bin/python scripts/warm_cache.py --regions 관악구 강남구 --types rh apt --period 1y
```

이미 받은 달은 건너뛰고, 예상 호출량을 먼저 출력한 뒤 1,000회를 넘으면 `--yes` 없이는 거절한다(쿼터 사고 방지). 로컬 개발(`dev.sh`/`serve.sh`)은 온디맨드로 조회하므로 워밍이 없어도 된다.

### 동네 지도 좌표 채우기 (1회)

`동네 지도` 탭은 법정동 중심좌표를 `cache.db`의 `dong_geo`에서 읽는다. 좌표가 없는 동은 지도에서 빠지므로, 캐시를 워밍한 뒤 한 번 돌린다. 키·가입·카드가 필요 없다(OSM Nominatim).

```bash
.venv/bin/python scripts/geocode_dongs.py     # 미저장 동만, 서울 417개에 약 8분
```

Nominatim 약관상 초당 1회라 느리다. 이미 저장된 동은 건너뛰므로 중간에 끊겨도 재실행이 싸다. `deploy-hf.sh`는 `dong_geo`를 그대로 동봉하므로 컨테이너 배포에도 따라간다.

## 배포

**현재 경로: 로컬 + ngrok 고정 도메인** (`./tunnel.sh`). 무료, 카드 불필요.

```bash
brew install --cask ngrok
ngrok config add-authtoken <대시보드에서 복사>   # https://dashboard.ngrok.com
echo 'ONJEON_NGROK_DOMAIN=<배정받은-도메인>.ngrok-free.dev' >> .env
```

이후 `./tunnel.sh`를 몇 번을 껐다 켜도 **주소가 같다** — 제출 서류·QR에 그대로 쓸 수 있다. `./tunnel.sh`는 시세 캐시가 비어 있으면 기동을 거부한다(빈 차트가 공개되는 것을 막는다).

> [!WARNING]
> **시연할 때만 켜라.** 고정 주소는 곧 영구히 발견 가능한 주소이고, 이 터널 뒤에 있는 건
> `.env`에 실제 API 키가 로드된 개인 맥이다(앱에 인증 계층 없음). 예전 랜덤 URL은 끄면 주소가
> 죽었지만 지금은 꺼도 링크가 유지되므로, 안 쓸 땐 끄는 데 비용이 없다.
> 무료 한도는 1GB·20k요청/월이고 방문자에게 ngrok 경고 페이지가 한 번 뜬다.

**컨테이너 배포(미채택, 폴백)**: `Dockerfile`·`render.yaml`·`deploy-hf.sh`는 검증된 채로 남아 있지만 현재 쓰지 않는다. Render 무료는 결제수단 미등록 워크스페이스의 무료 서비스를 그 달 남은 기간 정지시키고, Koyeb 무료는 신규 가입이 닫혔으며, HF Spaces Docker는 PRO($9/mo) 전용이기 때문이다(2026-07 확인). `Dockerfile`이 COPY하는 `data/cache.db.gz`(시세 캐시 동봉본)는 저장소에서 지웠으므로 빌드 전에 `./deploy-hf.sh`를 한 번 돌려 재생성해야 한다. HF Space 설정(`app_port` 등)은 이 저장소에 두지 않고 `deploy-hf.sh`가 배포 직전 임시 커밋으로만 얹는다.

LLM 키(`GEMINI_API_KEY` 우선, 없으면 `ANTHROPIC_API_KEY`)는 등기부 설명·what-if 질의·L0 룰 추출에만 쓰이고, 없으면 해당 기능만 빠진 채 나머지는 그대로 돈다. 기본 모델은 `gemini-2.5-flash`, `ONJEON_MODEL`로 교체 가능.

## 상태

**현재 단계** — L0~L4 전 레이어 + FastAPI/React 웹(전세vs월세·근거·동네 지도) + 테스트 555건. 실거래가는 국토부 6종(아파트·연립다세대·오피스텔·단독다가구 × 매매·전월세) 실키 연동. 매수안 세제는 법령 원문 대조 완료(취득세 지방세법 §11①8호 3구간 + §151①1호 지방교육세, 중개보수 공인중개사법 시행규칙 별표 1).

**남은 작업** — 실제 등기부 샘플 10건 L1 정확도 표, `[확인]` 수치 전수 재검증, 근저당비율 계수 실측, 보유세 구간 누진화, 임대차 중개보수 반영 ([docs/workflow.md](docs/workflow.md) 체크리스트).

> [!CAUTION]
> **이 계산이 다루지 못하는 것.** 서울 25개 구만 다루고 그 밖의 지역은 계산을 막는다(근거가 반쪽인
> 결론을 내지 않기 위해서다). 등기부에 안 적히는 위험 — 임대인 국세 체납, 다가구 선순위 임차인 — 은
> 못 본다. 집계 마진 보정은 지역 평균 계수를 개별 매물에 적용하므로 생태학적 오류가 있다.
> `[확인]` 마커가 붙은 수치는 최신 기준 검증 전이므로 확정된 사실로 취급하지 말 것.
> 자세한 것은 [docs/problem.md](docs/problem.md).
