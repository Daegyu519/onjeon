#!/usr/bin/env bash
# 온전 → Hugging Face Spaces 배포. 사용법: ./deploy-hf.sh <HF사용자명>
# 전제: 먼저 `.venv/bin/hf auth login` 으로 로그인돼 있어야 함(토큰은 로컬 캐시).
set -euo pipefail
cd "$(dirname "$0")"

HF_USER="${1:?사용법: ./deploy-hf.sh <HF사용자명>}"
REPO="$HF_USER/onjeon"

# 1) 로그인 확인
if ! .venv/bin/hf auth whoami >/dev/null 2>&1; then
  echo "❌ HF 로그인이 필요합니다. 먼저 실행:"
  echo "   .venv/bin/hf auth login   (Write 토큰 붙여넣기, git credential 추가는 Y)"
  exit 1
fi
echo "✅ 로그인: $(.venv/bin/hf auth whoami 2>/dev/null | head -1)"

# 2) 시세 캐시 동봉본 재생성 — 컨테이너는 휘발성이라 이게 없으면 화면 데이터가 0이 된다.
#    Dockerfile이 data/cache.db.gz를 COPY해서 푼다. 커밋돼 있어야 HF가 받는다.
if [ ! -f data/cache.db ]; then
  echo "❌ data/cache.db 가 없습니다. 먼저 캐시를 채우세요:"
  echo "   .venv/bin/python scripts/warm_cache.py --regions 관악구 --types rh --period 1y"
  exit 1
fi
# 동봉본은 최근 6개월치 — 서울 25구×4유형 전체를 담되 gz 7MB로 git 한도(10MB, 초과 시
# git-lfs 필요) 안에 들어온다. 1년치는 15MB로 LFS가 필요해 도구 의존이 생긴다.
# 지역 커버리지는 그대로(100조합)이고 기간 창만 짧다. 로컬 캐시는 건드리지 않고 사본을 다듬는다.
SHIP_PERIOD="${SHIP_PERIOD:-6m}"
.venv/bin/python - "$SHIP_PERIOD" <<'PY'
import shutil
import sqlite3
import sys

from onjeon.market.period import period_months

keep = tuple(period_months(sys.argv[1]))
shutil.copy("data/cache.db", "data/cache.ship.db")
conn = sqlite3.connect("data/cache.ship.db")
placeholders = ",".join("?" * len(keep))
for table in ("deal_cache", "fetched_months"):
    conn.execute(f"DELETE FROM {table} WHERE ym NOT IN ({placeholders})", keep)
conn.commit()
conn.execute("VACUUM")
conn.close()
PY
# -n: 타임스탬프/이름을 넣지 않아 내용이 같으면 결과도 같다(불필요한 diff 방지)
gzip -nc data/cache.ship.db > data/cache.db.gz
rm -f data/cache.ship.db
echo "📦 캐시 동봉본: $(du -h data/cache.db.gz | cut -f1) (원본 $(du -h data/cache.db | cut -f1))"
if ! git diff --quiet data/cache.db.gz 2>/dev/null || [ -n "$(git status --porcelain data/cache.db.gz)" ]; then
  echo "⚠️  data/cache.db.gz 가 갱신됐습니다. 커밋 후 다시 실행하세요:"
  echo "   git add data/cache.db.gz && git commit -m 'chore: 시세 캐시 동봉본 갱신'"
  exit 1
fi

# 3) Space 생성 (이미 있으면 통과) — huggingface_hub Python API(안정적)
.venv/bin/python - "$REPO" <<'PY'
import sys
from huggingface_hub import create_repo
repo = sys.argv[1]
# Docker SDK로 FastAPI 단일 서버 구동(Dockerfile). README의 app_port와 EXPOSE가 같아야 한다.
url = create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True)
print("✅ Space 준비:", url)
PY

# 4) HF 원격 추가 + 푸시 (git credential에 캐시된 토큰 사용)
# HF Space는 main 브랜치를 빌드한다 — 현재 작업 브랜치를 main으로 매핑해 올린다.
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git remote remove hf 2>/dev/null || true
git remote add hf "https://huggingface.co/spaces/$REPO"

# Space 설정은 README.md 최상단 YAML로만 읽힌다(HF는 별도 설정 파일을 안 본다).
# 그런데 GitHub은 그 YAML을 7행짜리 표로 렌더해서 저장소 첫 화면을 통째로 잡아먹는다.
# 그래서 저장소엔 두지 않고 배포 직전 임시 커밋으로만 얹는다 — main에는 남지 않는다.
# app_port는 Dockerfile의 EXPOSE/PORT와 반드시 같아야 한다(8000).
HF_BRANCH="hf-deploy-$$"
cleanup() { git checkout -q "$BRANCH" 2>/dev/null || true
            git branch -qD "$HF_BRANCH" 2>/dev/null || true; }
trap cleanup EXIT
git checkout -q -b "$HF_BRANCH"
{ cat <<'YAML'
---
title: 온전
emoji: 🏠
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
---

YAML
  cat README.md; } > README.hf && mv README.hf README.md
git add README.md
git commit -q -m "chore(hf): Space 설정 헤더 주입 — 배포 전용 커밋"
echo "🚀 푸시 중 → $REPO ($HF_BRANCH → main)"
git push -f hf "$HF_BRANCH:main"

echo ""
echo "✅ 배포 완료 → https://huggingface.co/spaces/$REPO"
echo "   빌드 1~3분. 이후 Settings → Variables and secrets 에서:"
echo "     • MOLIT_API_KEY (필수 — 없으면 캐시 워밍만 반영되고 라이브 조회는 비활성)"
echo "     • GEMINI_API_KEY (선택 — what-if 질의용)"
echo "   시세는 읽기 전용(ONJEON_PUBLIC_READONLY=1)으로 동작합니다 — 동봉 캐시 범위만 표시."
