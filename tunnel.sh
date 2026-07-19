#!/usr/bin/env bash
# 온전(穩全) — 로컬 실행 + cloudflared 무료 공개 URL 발급.
#   시작:  ./tunnel.sh          (기본 포트 8501)
#   종료:  ./tunnel.sh stop
# 이 Mac이 켜져 있고 프로세스가 살아있는 동안 공개 URL이 유효하다 (계정 불필요).
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" = "stop" ]; then
  pkill -f "streamlit run app.py" 2>/dev/null || true
  pkill -f "cloudflared tunnel" 2>/dev/null || true
  echo "🛑 앱·터널 종료됨."
  exit 0
fi

PORT="${1:-8501}"
command -v cloudflared >/dev/null || { echo "❌ cloudflared 필요: brew install cloudflared"; exit 1; }
[ -x .venv/bin/python ] || { echo "❌ .venv 필요: uv venv --python 3.12 .venv && uv pip install -p .venv -e ."; exit 1; }

mkdir -p .run
# 기존 정리
pkill -f "streamlit run app.py" 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 1

# 1) 앱 기동 (풀 기능 — .env의 e5-large RAG·Gemini·MOLIT 로드)
nohup .venv/bin/python -m streamlit run app.py --server.port "$PORT" --server.headless true > .run/app.log 2>&1 &
echo "🚀 앱 기동 중…"
for i in $(seq 1 120); do
  curl -s "http://localhost:$PORT/_stcore/health" 2>/dev/null | grep -q ok && break
  sleep 0.5
done
curl -s "http://localhost:$PORT/_stcore/health" 2>/dev/null | grep -q ok \
  || { echo "❌ 앱 기동 실패 — .run/app.log 확인"; tail -12 .run/app.log; exit 1; }

# 2) 터널 기동 + 공개 URL 추출
nohup cloudflared tunnel --url "http://localhost:$PORT" > .run/tunnel.log 2>&1 &
echo "🌐 공개 URL 발급 중…"
URL=""
for i in $(seq 1 40); do
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" .run/tunnel.log 2>/dev/null | head -1)
  [ -n "$URL" ] && break
  sleep 0.5
done

echo ""
if [ -n "$URL" ]; then
  echo "✅ 공개 URL:  $URL"
  echo "   • 이 Mac이 켜져 있는 동안 유효 (재시작하면 URL이 바뀜)"
  echo "   • 종료: ./tunnel.sh stop"
else
  echo "❌ URL 발급 실패 — .run/tunnel.log 확인"; tail -12 .run/tunnel.log
fi
