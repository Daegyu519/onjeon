#!/usr/bin/env bash
# 컨테이너 런타임 의존성 검증 — requirements-api.txt만으로 api.main이 뜨는가.
#
# 왜: 배포 경로가 둘이다. ./tunnel.sh는 로컬 .venv(pyproject 전체)로 돌아서
# numpy·pandas·sklearn이 다 있지만, 컨테이너(Dockerfile/render.yaml)는
# requirements-api.txt만 설치한다. l2/model.py 같은 파일에 최상단 import를
#하나 되돌리면 로컬 테스트는 전부 통과하는데 컨테이너만 죽는다 — 그래서
# 의존성이나 import를 건드렸으면 이걸 돌린다.
#
# 사용: ./scripts/check_api_deps.sh
set -euo pipefail
cd "$(dirname "$0")/.."

VENV="${TMPDIR:-/tmp}/onjeon-api-deps-check"
rm -rf "$VENV"
uv venv "$VENV" --python 3.12 -q
uv pip install -p "$VENV" -r requirements-api.txt -q

PYTHONPATH=src "$VENV/bin/python" - <<'PY'
import sys

import api.main  # noqa: F401 — 이게 컨테이너에서 죽던 지점

from onjeon.decision import decide
from onjeon.l2.model import load_risk_model

# 추론이 stdlib만으로 되는지 — 계수 JSON 경로
p = load_risk_model().predict_proba(
    {"jeonse_ratio": 0.89, "lien_ratio": 0.54, "is_villa": 1, "auction_rate": 0.74}
)
r = decide(
    {"monthly_income_krw": 2_800_000, "assets_krw": 20_000_000, "region": "관악구"},
    {
        "jeonse_deposit_krw": 200_000_000,
        "wolse_deposit_krw": 20_000_000,
        "wolse_monthly_rent_krw": 550_000,
        "senior_claims_krw": 120_000_000,
        "market_price_krw": 289_910_000,
        "building_type": "빌라",
    },
)
e_loss = r["jeonse_vs_wolse"]["jeonse"]["risk"]["e_loss_krw"]

banned = [m for m in ("numpy", "pandas", "sklearn", "scipy") if m in sys.modules]
print(f"  api.main import      OK")
print(f"  P(사고)              {p * 100:.2f}%")
print(f"  E[Loss]              {e_loss:,}원/년")
print(f"  금지 모듈 로드됨     {banned or '없음'}")
if banned:
    raise SystemExit(f"FAIL: 배포 런타임에 없는 모듈이 로드됐다 — {banned}")
PY

echo "PASS: requirements-api.txt만으로 E[Loss]까지 동작한다"
