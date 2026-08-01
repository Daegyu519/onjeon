#!/usr/bin/env bash
# 프로덕션 단일 서버: 프론트 빌드 후 FastAPI가 프론트+API를 한 포트에서 서빙.
# 사용: ./serve.sh  → http://localhost:8000  (외부 공유는 ./tunnel.sh 병행)
set -euo pipefail
cd "$(dirname "$0")"

# src를 직접 경로에 올린다. editable install의 .pth에 맡기면 안 되는 이유:
# 이 환경은 .venv에 macOS UF_HIDDEN을 수시로 다시 붙이고, python3.12의
# site.addpackage는 hidden .pth를 **경고 없이** 건너뛴다(python -v로만 보인다).
# 그러면 import onjeon이 죽어서 uvicorn이 기동 직후 종료한다.
# chflags nohidden으로 풀어도 몇 분 뒤 되돌아온다 — PYTHONPATH는 인터프리터가
# 직접 읽으므로 그 필터를 아예 안 거친다. (서드파티 의존성은 site-packages 그대로)
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src"

echo "▶ 프론트 빌드…"
( cd web && [ -d node_modules ] || npm ci; npm run build )

echo "▶ 단일 서버 기동 → http://localhost:${PORT:-8000}"
exec .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
