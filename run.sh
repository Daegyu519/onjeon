#!/usr/bin/env bash
# 온전(穩全) 실행 — 반드시 프로젝트 .venv(Python 3.12)로 기동한다.
# 전역 streamlit은 의존성이 없어 실패하므로 절대 'streamlit run'을 직접 쓰지 말 것.
#
# 사용법:  ./run.sh            (기본 포트 8501)
#         ./run.sh 8600       (포트 지정)
set -euo pipefail
cd "$(dirname "$0")"

PORT="${1:-8501}"

if [ ! -x ".venv/bin/python" ]; then
  echo "❌ .venv가 없습니다. 먼저 설치하세요:"
  echo "   uv venv --python 3.12 .venv && uv pip install -p .venv -e ."
  exit 1
fi

# 같은 포트를 물고 있는 유령 프로세스 정리 (재실행 시 'Address in use' 방지)
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⚠️  포트 $PORT 사용 중 — 기존 streamlit 종료 후 재기동합니다."
  pkill -f "streamlit run app.py.*--server.port $PORT" 2>/dev/null || true
  sleep 1
fi

echo "🚀 온전 기동 → http://localhost:$PORT"
exec .venv/bin/python -m streamlit run app.py --server.port "$PORT"
