#!/usr/bin/env bash
# 온전(穩全) — 로컬 실행 + ngrok 고정 도메인으로 공개.
#   시작:  ./tunnel.sh          (기본 포트 8000)
#   주소:  ./tunnel.sh url
#   종료:  ./tunnel.sh stop
#
# 왜 ngrok인가 (2026-07 조사):
#   cloudflared quick tunnel은 실행할 때마다 URL이 바뀌어 제출 서류·QR에 쓸 수 없었다.
#   ngrok 무료 플랜은 계정당 영구 dev 도메인(*.ngrok-free.dev)을 하나 준다 — 재시작해도
#   그대로다. Render/Koyeb/HF Spaces는 각각 카드 필수·무료 폐쇄·Docker 유료라 배제했다.
#   무료 한도: 엔드포인트 3개, 1GB·20k요청/월(번들 gzip 440KB → 실질 2,000회 방문).
#
# 보안 자세 — 시연할 때만 켠다:
#   도메인이 고정이라는 건 곧 영구히 발견 가능하다는 뜻이고, 이 터널 뒤에 있는 건
#   .env에 실제 API 키가 로드된 개인 맥이다(인증 계층 없음). 예전 랜덤 URL은 끄면
#   주소가 죽었지만 지금은 꺼도 링크가 유지되므로, 안 쓸 땐 끄는 것이 공짜다.
#   → 시연·심사 시간에만 켜고 끝나면 ./tunnel.sh stop.
#
# 공개하는 앱: FastAPI 단일 서버(api.main:app)가 web/dist 프론트 + /api를 한 포트에서
# 서빙한다(serve.sh와 동일 경로). 구 Streamlit(app.py)이 아니다.
set -euo pipefail
cd "$(dirname "$0")"

APP_PATTERN="uvicorn api.main:app"

# 고정 도메인. ngrok 대시보드(Domains)에서 무료로 배정받은 값을 .env에 넣는다:
#   ONJEON_NGROK_DOMAIN=abc123.ngrok-free.dev
# .env를 통째로 source하지 않는 이유: 임의 셸 코드 실행을 피한다.
DOMAIN="${ONJEON_NGROK_DOMAIN:-$(grep -m1 '^ONJEON_NGROK_DOMAIN=' .env 2>/dev/null | cut -d= -f2- | tr -d "\"' " || true)}"

if [ "${1:-}" = "stop" ]; then
  pkill -f "$APP_PATTERN" 2>/dev/null || true
  pkill -f "ngrok http" 2>/dev/null || true
  pkill -f "cloudflared tunnel" 2>/dev/null || true  # 구 경로 잔존 프로세스
  echo "🛑 앱·터널 종료됨. (도메인은 유지되므로 다시 켜면 같은 주소다)"
  exit 0
fi

if [ "${1:-}" = "url" ]; then
  [ -n "$DOMAIN" ] && echo "🌐 https://$DOMAIN" || echo "❌ ONJEON_NGROK_DOMAIN 미설정 — .env에 추가하세요"
  exit 0
fi

PORT="${1:-8000}"

command -v ngrok >/dev/null || { echo "❌ ngrok 필요: brew install --cask ngrok"; exit 1; }
[ -x .venv/bin/python ] || { echo "❌ .venv 필요: uv venv --python 3.12 .venv && uv pip install -p .venv -e ."; exit 1; }

# 예시 값이 그대로 남아 있는 경우를 따로 잡는다. 그냥 넘기면 ngrok이
# "Only paid plans may create endpoints with custom subdomains"(ERR_NGROK_313)를 뱉는데,
# 유료 플랜 문제로 오해하기 쉽다 — 실제로는 '내 계정에 없는 도메인'을 요청한 것이다.
if [ "$DOMAIN" = "abc123.ngrok-free.dev" ]; then
  cat <<'EOF'
❌ .env의 ONJEON_NGROK_DOMAIN이 예시 값(abc123.ngrok-free.dev) 그대로입니다.
   내 계정에 배정된 실제 도메인으로 바꿔야 합니다(남의/없는 도메인은 유료 오류로 거절됨).

   1) https://dashboard.ngrok.com/domains 접속
   2) 이미 도메인이 있으면 그 값을 복사, 없으면 [+ New Domain] → 무료 dev 도메인 생성
      (무료 플랜은 계정당 1개, 영구 유지)
   3) .env의 값을 교체:
        ONJEON_NGROK_DOMAIN=<복사한-도메인>.ngrok-free.dev
EOF
  exit 1
fi

if [ -z "$DOMAIN" ]; then
  cat <<'EOF'
❌ 고정 도메인이 설정되지 않았습니다.
   설정 안 하고 띄우면 예전처럼 매번 주소가 바뀝니다 — 그걸 없애려고 ngrok으로 온 겁니다.

   1) https://dashboard.ngrok.com 가입 (무료, 카드 불필요)
   2) Getting Started → Your Authtoken 복사 후:
        ngrok config add-authtoken <토큰>
   3) Domains 메뉴에서 배정된 무료 도메인(예: abc123.ngrok-free.dev) 확인
   4) .env 에 추가:
        ONJEON_NGROK_DOMAIN=abc123.ngrok-free.dev
EOF
  exit 1
fi

# 시세 캐시 확인 — 앱은 캐시가 비어도 200을 반환한다(=/openapi.json 헬스체크 통과).
# 그래서 여기서 안 막으면 "서버는 정상인데 차트가 전부 빈" 화면이 공개된다.
# 읽기 전용 모드에선 앱이 스스로 채울 수도 없다. mode=ro: 없는 파일을 만들지 않는다.
ROWS=$(.venv/bin/python -c "
import sqlite3
print(sqlite3.connect('file:data/cache.db?mode=ro', uri=True)
      .execute('SELECT count(*) FROM deal_cache').fetchone()[0])
" 2>/dev/null || echo 0)
if [ "$ROWS" -lt 1 ] 2>/dev/null; then
  echo "❌ 시세 캐시가 비어 있습니다(deal_cache 0행) — 공개해도 차트가 전부 빈 화면입니다."
  echo "   먼저 채우세요:"
  echo "     .venv/bin/python scripts/warm_cache.py --regions 관악구 --types rh --period 1y"
  exit 1
fi
echo "✅ 시세 캐시 ${ROWS}행"

mkdir -p .run
pkill -f "$APP_PATTERN" 2>/dev/null || true
pkill -f "ngrok http" 2>/dev/null || true
sleep 1

# editable install 확인 (이 환경은 .pth 숨김/롤백으로 수시로 풀림 — serve.sh와 동일)
if ! .venv/bin/python -c "import onjeon" 2>/dev/null; then
  chflags nohidden .venv/lib/python*/site-packages/*.pth 2>/dev/null || true
  .venv/bin/python -c "import onjeon" 2>/dev/null || uv pip install -p .venv -e . -q
fi

# 1) 프론트 빌드 — 공개할 화면이 web/dist다(빌드 안 하면 옛 화면이 나간다)
echo "▶ 프론트 빌드…"
( cd web && { [ -d node_modules ] || npm ci; } && npm run build ) > .run/build.log 2>&1 \
  || { echo "❌ 프론트 빌드 실패 — .run/build.log 확인"; tail -12 .run/build.log; exit 1; }

# 2) 앱 기동 (FastAPI 단일 서버 — .env의 MOLIT 키 로드)
# 공개 URL이므로 읽기 전용이 기본: 시세는 캐시만 읽고 외부 국토부 API를 호출하지 않는다.
# (인증 없는 공개 경로가 외부 호출을 타면 1요청 최대 183회로 운영자 키 쿼터가 털린다)
# 의도적으로 라이브 조회를 열려면: ONJEON_PUBLIC_READONLY=0 ./tunnel.sh
export ONJEON_PUBLIC_READONLY="${ONJEON_PUBLIC_READONLY:-1}"
nohup .venv/bin/uvicorn api.main:app --host 0.0.0.0 --port "$PORT" > .run/app.log 2>&1 &
echo "🚀 앱 기동 중…"
for i in $(seq 1 120); do
  curl -sf -o /dev/null "http://localhost:$PORT/openapi.json" 2>/dev/null && break
  sleep 0.5
done
curl -sf -o /dev/null "http://localhost:$PORT/openapi.json" 2>/dev/null \
  || { echo "❌ 앱 기동 실패 — .run/app.log 확인"; tail -12 .run/app.log; exit 1; }

# 3) 터널 기동 — --url로 고정 도메인 지정(구 --domain은 deprecated).
#    --log stdout: TTY가 아니면 ngrok이 TUI 대신 로그를 쓴다(명시해 확실히 한다).
nohup ngrok http "$PORT" --url "https://$DOMAIN" --log stdout > .run/tunnel.log 2>&1 &
echo "🌐 터널 연결 중… (https://$DOMAIN)"

# 공개 URL로 실제 응답이 오는지 확인 — 로그 문구에 의존하지 않는 직접 검증.
# ngrok-skip-browser-warning: 무료 플랜 경고 페이지 대신 실제 응답을 받기 위한 헤더.
UP=""
for i in $(seq 1 60); do
  curl -sf -o /dev/null -H "ngrok-skip-browser-warning: 1" \
    "https://$DOMAIN/openapi.json" 2>/dev/null && { UP=1; break; }
  sleep 1
done

echo ""
if [ -n "$UP" ]; then
  echo "════════════════════════════════════════════════════════════"
  echo "✅ 공개 URL:  https://$DOMAIN"
  echo "════════════════════════════════════════════════════════════"
  echo "   • 이 주소는 고정입니다 — 껐다 켜도 그대로"
  echo "   • 방문자는 ngrok 경고 페이지를 한 번 클릭해야 합니다(무료 플랜)"
  echo "   • 시연이 끝나면 꺼주세요: ./tunnel.sh stop"
else
  echo "❌ 터널이 응답하지 않습니다 — .run/tunnel.log 확인"
  echo "   흔한 원인: 인증 토큰 미등록 → ngrok config add-authtoken <토큰>"
  echo "             도메인 오타 → ngrok 대시보드 Domains와 .env 값 대조"
  tail -15 .run/tunnel.log
  exit 1
fi
