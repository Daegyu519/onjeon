#!/usr/bin/env bash
# 제출 zip 조립 — KB Future Finance A.I. Challenge 제8회 (마감 2026-08-03 16:00).
#
#   ./scripts/make_submission.sh
#
# 산출물은 저장소 **밖**에 만든다. 참가신청서에 성명·생년월일·연락처가 들어 있고
# 이 저장소는 공개돼 있어서, 빌드 디렉터리가 리포 안에 있으면 한 번의 `git add .`로
# 개인정보가 공개된다. 기본 위치는 ~/Desktop/온전_제출_<날짜>.
#
# 코드 트리는 git이 "이 프로젝트의 파일"로 보는 것을 기준으로 담는다. .gitignore가 이미
# .env·실물 등기부·캐시를 걸러 두었으므로, 손으로 제외 목록을 다시 쓰면 그게 두 번째
# 진실이 된다. 추적되지 않지만 **필요한** 두 개(합성 픽스처 PDF, 시세 캐시)만 더한다.
#
# `--others --exclude-standard`가 붙은 이유: 그냥 `git ls-files`는 **추적 중인** 파일만
# 낸다. 마감 전에 새로 쓴 파일(테스트·스크립트·문서)이 아직 커밋 전이면 zip에서 조용히
# 빠지고, 실제로 그렇게 됐다 — 방금 추가한 헤드라인 테스트 6개가 제출본에 없었다.
# 커밋 상태에 제출물이 좌우되면 안 된다.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"

STAMP="$(date +%Y%m%d)"
BUILD="${SUBMIT_DIR:-$HOME/Desktop/온전_제출_$STAMP}"
PKG="$BUILD/온전_KB_AI_Challenge_제8회"
FORMS="${FORMS_DIR:-$HOME/Downloads}"

DECK_PPTX="$REPO/dist-docs/온전_기술설명서.pptx"
DECK_PDF="$REPO/dist-docs/온전_기술설명서.pdf"

# ── 0. 전제 확인. 없는 것을 조용히 건너뛰면 빈 칸이 있는 zip을 제출하게 된다.
[ -f "$DECK_PPTX" ] && [ -f "$DECK_PDF" ] || {
  echo "✗ 기술설명서가 없습니다. 먼저: .venv/bin/python scripts/build_deck.py" >&2; exit 1; }

echo "▶ 빌드 위치: $PKG"
rm -rf "$BUILD"
mkdir -p "$PKG"/{01_참가신청서/"서식_원본(서명전)",02_기술설명서,03_프로토타입}

# ── 1. 체크리스트 (최상단)
cp "$REPO/docs/제출_체크리스트.md" "$PKG/00_제출_체크리스트.md"

# ── 2. 참가신청서 + 서식. 서식은 미서명본이라 하위 폴더에 따로 둔다 —
#      서명본으로 교체했는지 눈에 보이게 하려는 것이다(체크리스트 3·4번).
#
#      **한글 리터럴로 파일을 찾지 않는다.** macOS는 브라우저로 받은 파일명을 NFD(분해형)로
#      저장하는 일이 있고, bash 글롭은 정규화를 하지 않아 NFC로 적은 `*참가신청서*`가 그
#      파일을 조용히 놓친다(실측: Downloads의 두 신청서 중 하나만 잡혔다). 하필 작성본이
#      NFD였다면 참가신청서 없는 zip을 제출했을 것이다. 그래서 ASCII 부분으로만 찾는다.
APP_DOC="${APP_DOC:-$(ls -t "$FORMS"/*Challenge*.docx 2>/dev/null | grep -v '/~\$' | head -1)}"
[ -n "$APP_DOC" ] && [ -f "$APP_DOC" ] || {
  echo "✗ 참가신청서 docx를 찾지 못했습니다. APP_DOC=<경로>로 지정하세요. (탐색: $FORMS)" >&2
  exit 1; }
cp "$APP_DOC" "$PKG/01_참가신청서/"
echo "   참가신청서: $(basename "$APP_DOC")   ← 여러 개면 가장 최근 것"

form_count=0
while IFS= read -r -d '' f; do
  cp "$f" "$PKG/01_참가신청서/서식_원본(서명전)/"; form_count=$((form_count + 1))
done < <(find "$FORMS" -maxdepth 2 -type f -name '*.pdf' -path '*AICHALLENGE*' -print0)
[ "$form_count" -gt 0 ] || echo "⚠ 서약서·개인정보 동의서 서식을 못 찾았습니다 — 직접 넣으세요."

# ── 3. 기술설명서
cp "$DECK_PPTX" "$DECK_PDF" "$PKG/02_기술설명서/"

# ── 4. 프로토타입 — git이 프로젝트로 보는 파일 전부(추적 + 미추적, 무시 목록 제외)
git ls-files -z --cached --others --exclude-standard | while IFS= read -r -d '' f; do
  mkdir -p "$PKG/03_프로토타입/$(dirname "$f")"
  cp "$f" "$PKG/03_프로토타입/$f"
done
cp "$REPO/docs/심사용_실행안내.md" "$PKG/03_프로토타입/README_심사용.md"

#    추적되지 않지만 필요한 것: 합성 등기부(업로드 시연용)와 시세 캐시(무키 실행용).
#    둘 다 .gitignore의 `*.pdf` / 런타임 산출물 규칙에 걸려 추적되지 않는다.
mkdir -p "$PKG/03_프로토타입/data/fixtures/fake_registers"
cp "$REPO"/data/fixtures/fake_registers/*.pdf "$PKG/03_프로토타입/data/fixtures/fake_registers/"
cp "$REPO/data/cache.db" "$PKG/03_프로토타입/data/cache.db"

# ── 5. 개인정보·키 방어선. 여기서 걸리면 zip을 만들지 않는다.
#      실물 등기부는 파일명이 아니라 **존재 자체**로 판정한다 — 이름을 바꿔 넣어도 걸리게.
if [ -d "$PKG/03_프로토타입/data/fixtures/real_registers" ]; then
  echo "✗ 실물 등기부가 프로토타입에 들어갔습니다 — 중단합니다." >&2; exit 1
fi
if find "$PKG/03_프로토타입" -name ".env" -o -name "*.env" | grep -q .; then
  echo "✗ .env가 들어갔습니다 — 중단합니다." >&2; exit 1
fi
if grep -rIlE "AIza[0-9A-Za-z_-]{30,}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}" \
     "$PKG/03_프로토타입" 2>/dev/null | grep -q .; then
  echo "✗ API 키 형태의 문자열이 발견됐습니다 — 중단합니다." >&2; exit 1
fi

# ── 6. 압축. -x로 macOS 부산물을 뺀다(__MACOSX·.DS_Store가 들어가면 심사자 눈에 띈다).
ZIP="$BUILD/온전_KB_AI_Challenge_제8회.zip"
( cd "$BUILD" && zip -qr "$ZIP" "$(basename "$PKG")" -x "*.DS_Store" -x "__MACOSX/*" )

echo
echo "✅ $ZIP"
du -h "$ZIP" | cut -f1 | sed 's/^/   크기: /'
echo "   구성:"
( cd "$PKG" && find . -maxdepth 2 -mindepth 1 -not -path "./03_프로토타입/*" | sort | sed 's/^/     /' )
echo "     03_프로토타입/  ($(find "$PKG/03_프로토타입" -type f | wc -l | tr -d ' ')개 파일)"
echo
echo "▶ 다음: $PKG/00_제출_체크리스트.md 의 ☐ 항목을 처리하고 이 스크립트를 다시 돌리세요."
