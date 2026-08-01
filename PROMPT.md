# 온전(穩全) 세션 이어받기

새 Claude Code 세션이나 팀원이 이 저장소에서 작업을 이어받을 때 읽는다.
작업 디렉터리: `/Users/odaegyu/Desktop/idea`

> 2026-08-02 갱신. 이 파일에 **상태를 적지 않는다** — 예전 버전이 "디렉터리 스캐폴드 생성
> 완료(전부 빈 폴더)"와 11단계 구현 순서를 담고 있었고, 그게 다 끝난 뒤에도 그대로 남아
> 새로 온 사람에게 없는 과거를 알려줬다. 상태는 코드·테스트·`TODOS.md`에만 둔다.

## 1. 먼저 읽을 것 (이 순서로)

| 파일 | 왜 |
|---|---|
| [CLAUDE.md](CLAUDE.md) | 절대 원칙 6가지 · 5계층 구조 · **실측 함정 13개** · 컨벤션. 코드를 건드리기 전에 함정 색인에서 "내가 만질 파일이 여기 있는가"를 본다 |
| [TODOS.md](TODOS.md) | 대기 항목. 각 항목에 배경·현재상태·시작점이 있다. 여기서 하나 골라 시작한다 |
| [docs/architecture.md](docs/architecture.md) | §1이 **계획과 구현이 갈라진 지점**을 표로 보여준다. `docs/design.md`는 원안이라 지금 코드와 다른 곳이 있다 |
| [README.md](README.md) | 화면 · 실행 방법 · 한계 |

## 2. 어기면 안 되는 것

1. **LLM은 계산하지 않는다.** 숫자·판정은 L3(순수 함수)·L2(로지스틱 회귀). LLM은 해석 문단과 what-if 조작만 하고, 실패하면 `None`이 와서 화면이 그대로 돌아야 한다.
2. **모든 출력에 원문 출처** — 등기부 위치, 법령 조문, 공고 원문.
3. **룰은 코드가 아니라 데이터** — `src/onjeon/rules/*.json`(YYYY-MM 버전 태그). 로더는 `rules_io`가 단일 경로다.
4. **금액은 원(₩) 정수.** 만원 변환은 `display.py`에서만(함정 1).
5. **모르는 것은 채우지 않는다** — 못 읽은 필드는 예외 대신 `None` + 사유(함정 6·7·10·13). 불확실하면 점추정 대신 범위.
6. **`[확인]` 마커** = 아직 원문 대조 안 한 수치. 확정 사실로 취급 금지. 대조했으면 마커를 지우고 출처·기준일을 남긴다.
7. **위험의 정의를 두 개 만들지 않는다** — `l3/risk.py`가 P→LGD→E[Loss]의 단일 정의다. `l3/register_risk.py`는 **다른 축**(등기부에 적힌 권리 제한)이므로 섞지 않는다.

## 3. 작업 방식

- **금융 계산(engine·affordability·eligibility·risk)은 테스트 먼저.** 숫자가 틀리면 사용자가 손해를 본다. 나머지는 상황에 맞게.
- **픽스처는 실물 형식으로.** 합성 픽스처가 실물과 달라서 버그가 테스트를 통과한 일이 **세 번** 있었다(함정 4·10·13). 실물 발급본이 생기면 `data/fixtures/real_registers/`에 넣는다 — 개인정보라 저장소에는 안 올라가고, 있으면 `tests/test_register_real.py`가 파이프라인 전체를 거기에 고정한다.
- **룰 JSON에 필드를 추가하면** `l3/recommend.py`의 `_CARRIED`도 같이 갱신한다. 안 하면 조용히 사라진다(함정 3).
- **의존성을 건드리면 배포 경로 셋을 다 확인한다** — 로컬 venv · HF Spaces · Render(함정 2·5).

## 4. 실행

```bash
uv venv --python 3.12 .venv && uv pip install -p .venv -e ".[dev,llm]"
( cd web && npm ci )
cp .env.example .env        # MOLIT_API_KEY(시세 실데이터), FSS_API_KEY(공시금리)

.venv/bin/python -m pytest  # 실물 등기부가 없는 환경은 31건 skip
./dev.sh                    # 개발 — http://localhost:5180, API 문서 :8000/docs
./serve.sh                  # 로컬 프로덕션(프론트 빌드 + 단일 포트 8000)
./tunnel.sh                 # 외부 공개 — ONJEON_PUBLIC_READONLY=1로 뜬다(캐시만 읽음)
```

명령별 상세와 배포 경로 셋의 차이는 [CLAUDE.md](CLAUDE.md) '실행·테스트'에 있다.
