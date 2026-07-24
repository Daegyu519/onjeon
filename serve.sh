#!/usr/bin/env bash
# 프로덕션 단일 서버: 프론트 빌드 후 FastAPI가 프론트+API를 한 포트에서 서빙.
# 사용: ./serve.sh  → http://localhost:8000  (외부 공유는 ./tunnel.sh 병행)
set -euo pipefail
cd "$(dirname "$0")"

if ! .venv/bin/python -c "import onjeon" 2>/dev/null; then
  chflags nohidden .venv/lib/python*/site-packages/*.pth 2>/dev/null || true
  .venv/bin/python -c "import onjeon" 2>/dev/null || uv pip install -p .venv -e . -q
fi

echo "▶ 프론트 빌드…"
( cd web && [ -d node_modules ] || npm ci; npm run build )

echo "▶ 단일 서버 기동 → http://localhost:${PORT:-8000}"
exec .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
