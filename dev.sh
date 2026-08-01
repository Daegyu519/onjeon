#!/usr/bin/env bash
# 온전 개발 실행 — FastAPI(:8000) + Vite(:5180) 동시 기동.
# 사용: ./dev.sh  → 브라우저에서 http://localhost:5180 접속. 종료는 Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"

# src를 직접 경로에 올린다 — editable install의 .pth는 이 환경에서 못 믿는다(serve.sh 주석 참조).
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src"

# 프론트 의존성 확인
[ -d web/node_modules ] || ( cd web && npm install )

cleanup() { kill "${BACK:-}" "${FRONT:-}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "▶ 백엔드(FastAPI) :8000 …"
.venv/bin/uvicorn api.main:app --port 8000 >/tmp/onjeon-api.log 2>&1 &
BACK=$!

echo "▶ 프론트(Vite) :5180 …"
( cd web && npm run dev ) >/tmp/onjeon-web.log 2>&1 &
FRONT=$!

curl -s --retry-connrefused --retry 30 --retry-delay 1 -o /dev/null localhost:8000/docs || true
cat <<MSG

  ✅ 온전 실행 중
     화면    →  http://localhost:5180   (시세 흐름 / 내 조건 진단)
     API 문서 →  http://localhost:8000/docs
     로그    →  /tmp/onjeon-api.log · /tmp/onjeon-web.log
     종료    →  Ctrl+C
MSG
wait
