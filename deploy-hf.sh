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

# 2) Space 생성 (이미 있으면 통과) — huggingface_hub Python API(안정적)
.venv/bin/python - "$REPO" <<'PY'
import sys
from huggingface_hub import create_repo
repo = sys.argv[1]
# HF는 streamlit 네이티브 SDK 폐지 → Docker SDK로 Streamlit 구동(Dockerfile)
url = create_repo(repo, repo_type="space", space_sdk="docker", exist_ok=True)
print("✅ Space 준비:", url)
PY

# 3) HF 원격 추가 + 푸시 (git credential에 캐시된 토큰 사용)
git remote remove hf 2>/dev/null || true
git remote add hf "https://huggingface.co/spaces/$REPO"
echo "🚀 푸시 중 → $REPO"
git push hf main

echo ""
echo "✅ 배포 완료 → https://huggingface.co/spaces/$REPO"
echo "   빌드는 1~3분 소요. 이후 Settings → Secrets에 GEMINI_API_KEY 추가하세요."
