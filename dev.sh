#!/usr/bin/env bash
# 온전 개발 실행 — FastAPI(:8000) + Vite(:5173) 동시 기동.
# 사용: ./dev.sh  → 브라우저에서 http://localhost:5173 접속. 종료는 Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"

# editable install 확인 (이 환경은 .pth 숨김/롤백으로 수시로 풀림)
if ! .venv/bin/python -c "import onjeon" 2>/dev/null; then
  chflags nohidden .venv/lib/python*/site-packages/*.pth 2>/dev/null || true
  .venv/bin/python -c "import onjeon" 2>/dev/null || uv pip install -p .venv -e . -q
fi

# 프론트 의존성 확인
[ -d web/node_modules ] || ( cd web && npm install )

cleanup() { kill "${BACK:-}" "${FRONT:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "▶ 백엔드(FastAPI) :8000 …"
.venv/bin/uvicorn api.main:app --port 8000 >/tmp/onjeon-api.log 2>&1 &
BACK=$!

echo "▶ 프론트(Vite) :5173 …"
( cd web && npm run dev ) >/tmp/onjeon-web.log 2>&1 &
FRONT=$!

curl -s --retry-connrefused --retry 30 --retry-delay 1 -o /dev/null localhost:8000/docs || true
cat <<MSG

  ✅ 온전 실행 중
     화면    →  http://localhost:5173   (시세 흐름 / 내 조건 진단)
     API 문서 →  http://localhost:8000/docs
     로그    →  /tmp/onjeon-api.log · /tmp/onjeon-web.log
     종료    →  Ctrl+C
MSG
wait
