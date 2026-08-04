#!/usr/bin/env python3
"""기술설명서 덱(HTML) → 슬라이드 PNG → .pdf, 그리고 편집 가능한 .pptx.

    uv pip install -p .venv -e ".[docs]"      # python-pptx (문서 빌드 전용)
    .venv/bin/python scripts/build_deck.py

`docs/deck/*.html`이 원본이다. PNG·PPTX·PDF는 전부 산출물이라 `dist-docs/`로 나가고
저장소가 추적하지 않는다 — 원본만 고치고 이 스크립트를 다시 돌린다.

역할을 나눴다. **PDF는 픽셀 정본**이다 — 덱이 vmin 기반 CSS라 브라우저 렌더가 원본에
가장 가깝고, 그래서 헤드리스 캡처 PNG를 그대로 인쇄한다. **PPTX는 편집본**이다 —
이미지 25장을 붙여 두면 심사자도 팀원도 한 글자 못 고친다. `build_pptx.py`가 같은
HTML을 읽어 네이티브 텍스트 상자·도형·표로 다시 그린다. 문구는 여전히 HTML 한 곳에서만
나오므로 두 산출물이 내용으로 갈라질 일은 없다(조판은 줄바꿈 위치 정도가 다르다).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECK = ROOT / "docs" / "deck" / "온전_기술설명서.html"
TEAM = ROOT / "docs" / "deck" / "team.local.json"
OUT = ROOT / "dist-docs"
PNG_DIR = OUT / "slides"
W, H = 1920, 1080  # 16:9. vmin = 1080 → 화면에서 보던 배치가 그대로 나온다.

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def find_chrome() -> str:
    for p in CHROME_CANDIDATES:
        if Path(p).exists():
            return p
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found

    sys.exit("Chrome/Chromium을 찾지 못했습니다 — CHROME_CANDIDATES에 경로를 추가하세요.")


def deck_source() -> tuple[Path, bool]:
    """빌드에 쓸 덱 경로 → (경로, 임시사본인가).

    표지의 팀명·팀원·소속은 원본 HTML에서 점선 공란으로 남겨 둔다. **이 저장소는
    공개돼 있어서 실명·학교를 커밋하면 히스토리에 영구히 남는다.** 그래서 값은
    `docs/deck/team.local.json`(gitignore)에만 두고 빌드할 때 사본에 주입한다.
    파일이 없으면 원본을 그대로 쓴다 — 표지에 공란이 보이는 편이, 이름이 빠진 걸
    모르고 제출하는 것보다 낫다.

    사본을 **같은 디렉터리**에 만드는 이유: 덱이 스크린샷을 `../screenshots/`
    상대경로로 참조한다. 다른 곳에 쓰면 그림이 전부 깨진 채로 캡처된다.

        {"팀명": "...", "팀원": "홍길동(팀장) · 김서연", "소속": "○○대 ○○학과"}
    """
    if not TEAM.exists():
        return DECK, False
    team = json.loads(TEAM.read_text(encoding="utf-8"))
    src = DECK.read_text(encoding="utf-8")
    for key, value in team.items():
        # 표지 메타는 `<dt>키</dt><dd>값</dd>` 한 줄뿐이라 dd 안쪽만 갈아끼운다.
        src, hit = re.subn(
            rf"(<dt>{re.escape(key)}</dt><dd>).*?(</dd>)",
            lambda m: m.group(1) + escape(str(value)) + m.group(2),
            src, count=1,
        )
        if not hit:
            sys.exit(f"표지에 '{key}' 칸이 없습니다 — team.local.json의 키를 확인하세요.")
    copy = DECK.with_name(f".build-{DECK.name}")
    copy.write_text(src, encoding="utf-8")
    return copy, True


def slide_count(html: str) -> int:
    # <section class="slide ..."> 개수. 덱의 슬라이드 정의는 이 한 패턴뿐이다.
    return len(re.findall(r'<section class="slide', html))


def chrome_run(chrome: str, *args: str) -> None:
    # --force-prefers-reduced-motion: 덱의 등장 애니메이션을 끈다. 안 끄면 캡처 시점에
    # 따라 요소가 opacity 0에서 잡혀 슬라이드가 반쯤 빈 채로 나온다.
    base = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-prefers-reduced-motion", "--allow-file-access-from-files",
        "--virtual-time-budget=4000", "--no-first-run", "--no-default-browser-check",
    ]
    subprocess.run([*base, *args], check=True, capture_output=True)


def main() -> None:
    if not DECK.exists():
        sys.exit(f"덱 원본이 없습니다: {DECK}")
    chrome = find_chrome()
    deck, is_copy = deck_source()
    print(f"▶ 표지 팀 정보: {'team.local.json 주입' if is_copy else '공란 (team.local.json 없음)'}")
    try:
        n = slide_count(deck.read_text(encoding="utf-8"))
        if n == 0:
            sys.exit("슬라이드를 하나도 찾지 못했습니다 — 덱 구조가 바뀌었는지 확인하세요.")

        PNG_DIR.mkdir(parents=True, exist_ok=True)
        pngs: list[Path] = []
        for i in range(1, n + 1):
            png = PNG_DIR / f"slide-{i:02d}.png"
            chrome_run(chrome, f"--window-size={W},{H}", f"--screenshot={png}",
                       f"{deck.as_uri()}?s={i}")
            if not png.exists() or png.stat().st_size < 5_000:
                sys.exit(f"슬라이드 {i} 캡처가 비었습니다({png}) — 렌더 실패를 조용히 넘기지 않습니다.")
            pngs.append(png)
            print(f"  slide {i:02d}/{n}  {png.stat().st_size // 1024:>4} KB")

        # ── PPTX: 같은 HTML을 네이티브 도형으로 다시 그린다(편집 가능)
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import build_pptx

        pptx_path = OUT / "온전_기술설명서.pptx"
        if build_pptx.build(deck, pptx_path) != n:
            sys.exit("PPTX 슬라이드 수가 캡처와 다릅니다 — 덱 구조를 확인하세요.")
    finally:
        # 실명이 든 사본을 저장소 안에 남기지 않는다. gitignore가 걸려 있어도
        # `git add -f`나 백업 도구는 그걸 안 본다.
        if is_copy:
            deck.unlink(missing_ok=True)

    # ── PDF: 같은 PNG를 한 장/페이지로 깔고 Chrome으로 인쇄
    imgs = "\n".join(f'<img src="{p.as_uri()}">' for p in pngs)
    printable = PNG_DIR / "_print.html"
    printable.write_text(
        "<!DOCTYPE html><meta charset='utf-8'>"
        "<style>@page{size:13.333in 7.5in;margin:0}"
        "html,body{margin:0;padding:0;background:#1b1917}"
        "img{display:block;width:13.333in;height:7.5in;page-break-after:always}"
        "img:last-child{page-break-after:auto}</style>" + imgs,
        encoding="utf-8",
    )
    pdf_path = OUT / "온전_기술설명서.pdf"
    chrome_run(chrome, "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}",
               printable.as_uri())

    for path in (pptx_path, pdf_path):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")
    print(f"슬라이드 {n}장 · PNG {PNG_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
