---
title: 온전
emoji: 🏠
colorFrom: yellow
colorTo: gray
sdk: streamlit
sdk_version: 1.44.0
app_file: app.py
pinned: false
---

<!-- 위 YAML은 Hugging Face Spaces 배포 설정입니다 (GitHub에서는 무시됨).
     Space 생성 시 HF가 보여주는 sdk_version과 다르면 그 값으로 바꾸세요. -->

# 온전(穩全) — 리스크 조정 주거비용 기반 청년 주거 의사결정 AI

> KB Future Finance A.I. Challenge 출품 프로젝트 (2026년 7월 기준 기획)

**"이 집, 위험을 감안하면 전세가 월세보다 정말 싼가?"**

등기부등본을 AI로 읽고, 보증금 미회수 위험을 원(₩) 단위 **기대손실**로 환산하여, 전세/월세/매수 3안의 *리스크 조정 세후 총비용*을 비교해주는 서비스입니다.

기존 리스크 진단 서비스가 "위험도 — 주의"라는 정성 등급에서 멈추는 것과 달리, 온전은 **"이 매물은 미회수 기대손실 연 180만원을 반영하면 월세보다 연 80만원 비쌉니다"**라는 의사결정을 출력합니다.

## 왜 필요한가

청년은 인생 최대 금액의 금융 의사결정(보증금)을 가장 적은 정보와 경험으로 내립니다. 위험 정보(전세사기·보증사고)와 비용 정보(정책상품·세제)가 서로 다른 서비스에 분리되어 있어, 정작 필요한 질문 — *"이 위험을 감안한 실질 비용은 얼마인가"* — 에는 아무도 답하지 않습니다.

## 어떻게 동작하는가 (한 눈에)

```
등기부 PDF 업로드
  → L1: LLM 비전 파싱 (채권최고액·선순위 추출, 원문 위치 인용)
  → L2: ML 사고확률 P(사고) + SHAP 설명
  → L3: 결정론적 계산 — 3안 세후 총비용 + 기대손실 E[Loss] = P(사고)×LGD×보증금
  → L4: LLM 해석·인용 + what-if 질의응답
  (L0: 정책 공고 → 자격요건 JSON 룰 DB, 오프라인 파이프라인)
```

핵심 설계 철학: **"LLM에게 계산을 시키지 않는다."** 숫자는 결정론, LLM은 읽기·조작·설명만.

## 문서 안내

| 문서 | 내용 | 이런 질문에 답함 |
|---|---|---|
| [CLAUDE.md](CLAUDE.md) | 프로젝트 원칙·구조·컨벤션 | "이 프로젝트의 규칙은?" |
| [docs/architecture.md](docs/architecture.md) | L0~L4 5계층 아키텍처 | "시스템이 왜 이렇게 나뉘는가?" |
| [docs/design.md](docs/design.md) | 상세 설계도 — 모듈 스펙, 수식, 데이터 스키마, 화면 | "정확히 무엇을 어떻게 만드는가?" |
| [docs/workflow.md](docs/workflow.md) | 4주 MVP 계획, 역할 분담, 데모 시나리오 | "누가 언제 무엇을 하는가?" |
| [docs/data-pipeline.md](docs/data-pipeline.md) | 데이터 수집 방향 — 소스 5종, 갱신 절차, 사용법 | "데이터는 어디서 어떻게 채우는가?" |

## 실행 방법

```bash
# 의존성 설치 (최초 1회 — uv 필요)
uv venv --python 3.12 .venv
uv pip install -p .venv -e ".[dev,llm]"

# API 키 설정 (선택 — 없어도 오프라인 데모 동작)
cp .env.example .env   # GEMINI_API_KEY, MOLIT_API_KEY 등 입력

# 전체 테스트
.venv/bin/python -m pytest

# 데모 실행 → http://localhost:8501
./run.sh                # 원클릭 (권장 — 올바른 .venv로 자동 기동)
# 또는 직접:
.venv/bin/python -m streamlit run app.py
# ⚠️ 그냥 'streamlit run app.py'는 의존성 없는 전역 Python으로 실행돼 실패합니다
```

## 배포

Hugging Face Spaces(무료 16GB)로 배포합니다 — 절차는 [docs/deploy-hf.md](docs/deploy-hf.md) 참조.
(Streamlit Community Cloud는 무료 1GB라 이 ML 스택엔 부족해 이전했습니다.)

- **API 키 없이 전 구간 데모 가능** (MockLLM 오프라인 경로).
- `GEMINI_API_KEY`(우선) 또는 `ANTHROPIC_API_KEY` 설정 시 what-if 질의·L0 룰 추출이 실제 LLM으로 동작. 기본 모델은 `gemini-2.5-flash`이며 `ONJEON_MODEL`로 교체 가능.

## 상태

- 현재 단계: MVP 수직 슬라이스 구현 완료 — L0~L4 전 레이어 + Streamlit UI + 테스트 81건
- 남은 작업: 실제 등기부 샘플 10건 L1 정확도 표, `[확인]` 수치 전수 재검증 ([docs/workflow.md](docs/workflow.md) 체크리스트)
- 원본 제안서: `KB_AI_Challenge_제안서_초안.md` (⚠️ `[확인]` 마커 항목은 최신 수치 검증 필요)
