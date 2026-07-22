# 설계 스펙 — 시세 동향 차트(Toss식) + 등기부 파싱 웹

- 작성일: 2026-07-23
- 상태: 설계 확정 (구현 계획 대기)
- 관련 원칙: [CLAUDE.md](../../../CLAUDE.md) — LLM은 계산 안 함, 출처 명기, 원(₩) 정수, 조회 기준일, `[확인]` 마커

## 1. 목표 (한 줄)

업로드한 등기부등본에서 **주소·전용면적·건물용도**를 추출하고, 그 매물의 **시군구·용도에 맞는 국토부 실거래가**를 집계해 **평당가(만원) 매매/전세 추이**를 Toss 증권식 인터랙티브 차트로 보여준다.

## 2. 범위

### 포함 (In)
- 등기부 PDF 파싱 → 시도/시군구/지번/도로명 주소, 전용면적, 건물용도 추출
- 국토부 실거래가 집계 → 평당가(만원) 매매·전세 시계열
- FastAPI REST 계층 2개 엔드포인트(`/api/register/parse`, `/api/market-trends`)
- SQLite 집계 캐시 DB
- Vite + React + Apache ECharts(`echarts-for-react`) 프론트: 필터 · dataZoom · tooltip

### 제외 (Out) — 명시적 재요청 시까지
- **전세/월세/매매 3안 비교 기능** — 비활성화. `run_comparison` 코드·테스트는 **보존**(삭제 아님).
- R-ONE(한국부동산원) 지수 — 이번 범위 아님(데이터원은 실거래가로 확정).
- 전국 데이터 사전 적재 — 지역은 **업로드 매물의 시군구** 중심 온디맨드.
- **비용 발생 요소 전면 배제**(사용자 지시):
  - 유료 클라우드 호스팅 안 씀 → **현행 로컬 + cloudflared 터널 유지**(무료).
  - 스캔 이미지 PDF용 유료 OCR/비전 LLM 안 씀 → **텍스트 레이어 PDF만 지원**.
  - 이 기능은 LLM을 전혀 호출하지 않는다(무료 로컬 구성만).

## 3. 아키텍처 — 공존 원칙

기존 Python 로직은 그대로 재사용하고 그 위에 얇은 API 계층과 새 프론트를 얹는다. 기존 `src/onjeon/`(L0~L4, parser, molit.py, rules, tests)는 **건드리지 않는다**(molit.py는 신규 엔드포인트 함수 추가만).

```
[유지] src/onjeon/            ← L0~L4, parser, molit.py, rules, tests
            │ import (재사용)
[신규] api/  (FastAPI)         ← onjeon 모듈을 감싸는 REST 계층
            │   POST /api/register/parse   (PDF → 주소·면적·용도)
            │   GET  /api/market-trends    (지역·유형·기간 → 평당가 시계열)
            │   data/cache.db (SQLite)     ← 실거래가 집계 캐시
            ▼
[신규] web/  (Vite + React + echarts-for-react)  ← Toss식 차트
[변경] app.py (Streamlit)      ← 비교 탭만 비활성화(코드 보존)
```

**설계 근거**: `run_comparison` 등 로직이 순수 Python 함수라 FastAPI에서 import해 감싸면 됨. Next.js API route는 로직이 전부 Python이라 Node 왕복이 지저분 → 배제. Streamlit 컴포넌트(streamlit-echarts)는 스펙의 React(Vite) 요구와 배치 → 배제.

## 4. 백엔드 상세

### 4.1 등기부 파싱 (`api/register_parse.py`)
- 입력: 업로드 PDF. `pdfplumber` 또는 `PyMuPDF`로 **텍스트 레이어** 추출(비전 LLM 아님 — 이 기능은 좌표/주소 텍스트가 목적).
- 출력: `{ sido, sigungu, jibun, road_addr, exclusive_area_m2, building_use }`
- `building_use` → 실거래가 엔드포인트 계열 선택 키(§4.3).
- `sigungu` → `resolve_lawd_cd()`로 LAWD_CD 변환. 미해석 시 명시적 오류(수동 지역 선택 폴백).
- `[확인]` 등기부 텍스트 레이아웃별 주소/면적 라벨 패턴 — 실물 PDF로 정규식/파싱 규칙 확정 필요.
- **스캔 이미지 PDF(텍스트 레이어 없음)**: 텍스트 추출 0 → **명확한 오류 안내 후 수동 입력 폴백**. 유료 OCR/비전 LLM 미사용(비용 배제 지시).

### 4.2 평당가 집계 (`src/onjeon/data_pipeline/molit.py` 확장 + `api/aggregate.py`)
- 기존 `fetch_period` / `month_range`(방금 추가됨) 재사용.
- **평당가(원/평) = 거래금액(원) ÷ (전용면적_m2 ÷ 3.3058)**. 표시 시 만원 = ÷10,000 (표시 계층에서만).
- 월별/주별 버킷 평균:
  - 기간 ≤ 6개월 → **주차 단위**(계약일 기준 "YYYY년 M월 W주")
  - 그 외 → **월 단위**(YYYY-MM)
- 각 버킷에 거래건수(n)·조회 기준일 동반 저장.

### 4.3 실거래가 엔드포인트 계열 (용도별) — 신규 추가
현재 molit.py는 연립다세대 매매(`RHTrade`)만. 아래 계열을 추가한다. **정확한 오퍼레이션 ID는 `[확인]`(data.go.kr 카탈로그로 검증 후 확정):**

| 용도 | 매매 | 전월세 |
|---|---|---|
| 아파트 | `getRTMSDataSvcAptTradeDev` `[확인]` | `getRTMSDataSvcAptRent` `[확인]` |
| 연립다세대(빌라) | `getRTMSDataSvcRHTrade` (보유) | `getRTMSDataSvcRHRent` `[확인]` |
| 오피스텔 | `getRTMSDataSvcOffiTrade` `[확인]` | `getRTMSDataSvcOffiRent` `[확인]` |

- **전세 판정**: 전월세 응답에서 **월세금 = 0** 인 건만 전세. 평당가는 **보증금 ÷ 평수**. (필드 태그 `deposit`/`monthlyRent` 신·구형 `[확인]`.)
- 매매·전월세 응답의 금액/면적 태그가 계열마다 미세하게 다를 수 있음 → `_TAGS` 확장 `[확인]`.

### 4.4 캐시 DB (SQLite, `api/db.py`)
스펙 테이블에 용도·건수·조회일 추가:
```sql
CREATE TABLE market_price (
  date         TEXT NOT NULL,   -- 'YYYY-MM' 또는 'YYYY-MM-W' (INDEX)
  region_code  TEXT NOT NULL,   -- LAWD_CD 5자리
  building_type TEXT NOT NULL,  -- apt|rh|offi
  deal_type    TEXT NOT NULL,   -- 매매|전세
  price_per_pyung INTEGER NOT NULL,  -- 원/평 (표시 시 만원 변환)
  n_deals      INTEGER NOT NULL,
  queried_at   TEXT NOT NULL,
  PRIMARY KEY (date, region_code, building_type, deal_type)
);
CREATE INDEX idx_lookup ON market_price(region_code, building_type, date);
```
(지역, 용도, 계약월) 첫 조회 시 API→집계→저장, 이후 캐시. 일일 호출 한도·지연 완화.

### 4.5 REST 계약
```
POST /api/register/parse   (multipart: file=PDF)
  → { sigungu, region_code, building_use, exclusive_area_m2, road_addr, ... }

GET /api/market-trends?region={LAWD_CD}&buildingType={apt|rh|offi}&period={1m|6m|1y|3y|5y}
  → { "dates": ["2021-07", ...], "mae_price": [1580, ...], "jun_price": [1120, ...] }
```
- `mae_price`(매매)·`jun_price`(전세) 단위 = 평당 만원(정수 반올림).
- 데이터 없는 버킷은 결측(프론트에서 라인 끊김 처리).

## 5. 프론트 (`web/`, Vite + React + ECharts)

스펙 그대로:
- **상단 필터**: [지역] 드롭다운(기본값 = 파싱된 시군구), [매매/전세/전체], [면적], 기간 퀵버튼 [1M/6M/1Y/3Y/5Y].
- **차트**: X=날짜(년.월/주차), Y=평당가(만원). Line1 매매 `#00a84d`, Line2 전세 `#0066ff`.
- **인터랙션**: `dataZoom:[{type:'inside'},{type:'slider'}]` 드래그/스크롤/스와이프 줌·이동. tooltip `trigger:'axis'` → `[2026년 7월 1주 | 매매 1,889만 | 전세 1,184만]`.
- 기간 버튼 → state 변경으로 X축 범위 재설정(필요 시 API 재요청).
- 개발: Vite dev proxy로 FastAPI(`/api`) 프록시. `/frontend-design` 스킬은 구현 단계 적용.

## 6. 기타

- **MPS**: torch 사용 경로에 `resolve_device()`(mps 가용 시 mps, 아니면 cpu) 헬퍼 기본 적용. 단 이번 차트 기능은 torch 불필요이며, fastembed는 ONNX(onnxruntime)라 MPS 대상 아님 — 정직하게 명시.
- **지역 커버리지**: `regions.py`의 LAWD_CD 맵은 현재 서울 25구. 업로드 매물이 서울 외면 미해석 → 지역 선택 폴백. **전국 법정동 시군구 코드표 추가**는 별도 태스크로 남김 `[확인]`.
- **테스트(TDD)**: 평당가 계산·전세 필터·주/월 집계는 순수 함수 단위테스트 필수. API는 `http_get` 주입으로 네트워크 없이 검증. 파서는 고정 텍스트 픽스처.
- **한계 명시**(UI 노출): 실거래가 당월 불완전, 지역별 첫 조회 지연, 특정 매물이 아닌 지역·용도 단위 시세, 서울 외 커버리지 제한.

## 7. 구현 순서(계획 단계에서 상세화)

1. 백엔드 집계 코어 — 용도별 실거래가 엔드포인트 + 평당가/전세필터/주월집계 (TDD, 네트워크 없이)
2. SQLite 캐시 + `/api/market-trends` (FastAPI)
3. 등기부 파싱 + `/api/register/parse`
4. Vite+React+ECharts 프론트 (필터·dataZoom·tooltip)
5. Streamlit 비교 탭 비활성화(코드 보존)

## 8. 비용

**핵심: 이 아키텍처는 사실상 무료.** 이 기능은 LLM을 전혀 호출하지 않으며(등기부 파싱은 pdfplumber/PyMuPDF 로컬 텍스트 추출), 오히려 비전 LLM 기반 비교 기능을 끄면서 토큰 비용이 감소한다.

| 구성 | 비용 |
|---|---|
| 국토부 실거래가 API (data.go.kr) | 무료. 일일 호출 한도는 요금이 아닌 제한 → SQLite 캐시로 완화 |
| 등기부 PDF 파싱 (pdfplumber/PyMuPDF) | 무료(로컬, LLM 아님) |
| SQLite 캐시 / MPS 연산 | 무료(로컬) |
| LLM 호출 | 0 (이 기능은 LLM 미사용) |
| Vite 정적 프론트 | 무료(정적 호스팅 무료 티어 또는 터널 서빙) |
| 로컬 + cloudflared 터널 | 무료(구축됨) |

**유료화 가능 지점 — 둘 다 채택 안 함(사용자 비용 배제 지시):**
1. ~~"항상 켜진" 클라우드 백엔드(~$5–7/월)~~ → **채택 안 함.** 현행 로컬 + cloudflared 터널 유지.
2. ~~스캔 이미지 등기부 OCR/비전 LLM~~ → **채택 안 함.** 텍스트 레이어 PDF만 지원, 스캔본은 수동 입력 폴백.

## 9. 가정 / 미해결 (`[확인]`)
- 실거래가 아파트/오피스텔/전월세 오퍼레이션 ID·응답 태그 — 실키로 검증 후 확정.
- 등기부 텍스트 레이아웃별 주소/면적/용도 파싱 규칙 — 실물 PDF로 확정.
- 서울 외 지역 지원 여부(전국 코드표) — MVP 이후.
- data.go.kr 실거래가 키 보유(확인됨, `MOLIT_API_KEY`). R-ONE 키는 불필요(범위 제외).
