---
name: verify
description: 온전(穩全) 프로젝트의 빌드·기동·구동 검증 레시피
---

# 온전 검증 레시피

## 기동 (Streamlit 서버)

```bash
pkill -f "streamlit run app.py"; sleep 1
nohup .venv/bin/python -m streamlit run app.py --server.port 8501 --server.headless true > /tmp/onjeon-st.log 2>&1 &
curl -s http://localhost:8501/_stcore/health   # → "ok"
```

- 8501이 이미 점유돼 있으면 `lsof -nP -iTCP:8501 -sTCP:LISTEN`으로 **어느 프로젝트의 프로세스인지** 먼저 확인 (과거에 ~/Desktop/KB_AI_Challenge의 고아 서버가 점유했던 이력 있음).

## 전체 스크립트 실행 (렌더 경로 오류 탐지)

```bash
.venv/bin/python app.py   # bare 모드 — st.* 는 no-op, Python 예외는 그대로 드러남. exit 0 기대
```

## 패키지 경계 구동 (수직 슬라이스)

```bash
.venv/bin/python -c "import onjeon" || uv pip install -p .venv -e . -q
```

- **주의**: 이 환경에서는 editable install이 수시로 풀린다(세션 롤백). import 실패 시 재설치가 먼저다.
- 시나리오 구동: `data/fixtures/`의 페르소나·매물 2건을 `onjeon.compare.run_comparison`에 넣고 `best`/`e_loss`/`citations` 확인. 위험 빌라 → "월세" 기대.
- what-if는 `MockLLM` 스크립트 응답으로 구동 (API 키 불필요). L0는 `pipeline(공고, extract_llm=..., verify_llm=...)`.

## 가치 있는 프로브

- 갑구(압류) 항목 추가한 등기부 → citation_label에 "None" 없이 라벨 생성되는지
- building_type "기타"/미지 유형 → 낙찰가율 폴백으로 완주하는지
- 깨진 룰 JSON → pipeline이 크래시 없이 approved=False + "룰 스키마 위반" 사유인지
- what-if에서 tool 미호출 final 반복 → grounded=False인지
