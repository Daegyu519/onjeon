"""학습된 L2 로지스틱 계수를 룰 JSON으로 덤프한다 (오프라인 전용).

왜 필요한가: 배포 런타임(requirements-api.txt)에는 numpy·pandas·scikit-learn이
없다. 그런데 로지스틱 회귀의 **추론**은 시그모이드 한 줄이라 계수·절편·학습평균만
있으면 stdlib으로 충분하다. 학습만 여기(개발 환경)에서 하고 결과를 버전 태그
붙은 룰 데이터로 남긴다 — CLAUDE.md 원칙 3(룰은 코드가 아니라 데이터).

사용:
    .venv/bin/python scripts/dump_risk_model.py            # 최신 버전 파일 갱신
    .venv/bin/python scripts/dump_risk_model.py 2026-08    # 새 버전으로 저장

synth.generate()는 seed 고정이라 같은 입력이면 같은 계수가 나온다. 계수가 바뀌면
tests/test_risk_wiring.py::test_matches_sklearn_training 이 실패하므로, synth나
학습 설정을 건드렸으면 이 스크립트를 다시 돌려야 한다.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from onjeon.l2.model import FEATURES, train  # noqa: E402
from onjeon.l2.synth import (  # noqa: E402
    DATA_NOTE,
    HUG_BASE_ACCIDENT_RATE,
    TRUE_INTERCEPT,
    generate,
)

RULES = Path(__file__).resolve().parent.parent / "src" / "onjeon" / "rules"


def main() -> int:
    version = sys.argv[1] if len(sys.argv) > 1 else "2026-07"
    n, seed = 1500, 42
    df = generate(n=n, seed=seed)
    model = train(df)

    measured = float(df["accident"].mean())
    out = {
        "version": version,
        "queried_at": date.today().isoformat(),
        "model": "logistic_regression",
        "features": FEATURES,
        "coef": {f: model.coef[f] for f in FEATURES},
        "intercept": model.intercept,
        "feature_means": {f: model.feature_means[f] for f in FEATURES},
        "data_note": DATA_NOTE,
        "prob_timescale": "annual",
        "prob_timescale_note": (
            f"P(사고)는 연간 확률이다. 절편이 HUG 전세보증금반환보증 연 사고율 "
            f"{HUG_BASE_ACCIDENT_RATE:.1%}(2025-08)에 앵커돼 있고(생성 절편 "
            f"{TRUE_INTERCEPT}), 합성 모집단 실측 평균은 {measured:.2%}다. "
            "engine.expected_loss가 이 값을 곱해 연간 기대손실을 낸다 — "
            "계약기간(2년) 확률로 오해해 나누면 안 된다."
        ),
        "train_note": (
            f"scripts/dump_risk_model.py로 생성. onjeon.l2.synth.generate(n={n}, seed={seed}) "
            "합성 데이터 + sklearn LogisticRegression(max_iter=1000). 재현 가능."
        ),
        "limitations": [
            "합성 데이터 학습 — 성능 주장 아님, 구조 시연 목적 (CLAUDE.md 원칙 5)",
            "등기부 외 리스크(체납·다가구 선순위 임차인 등) 미커버",
            "실데이터(KB 전세대출·보증사고) 결합은 고도화 로드맵",
        ],
    }

    path = RULES / f"risk_model_{version}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")
    print(f"  intercept {out['intercept']:.4f}  실측 사고율 {measured:.2%}")
    for f in FEATURES:
        print(f"  {f:16s} coef {out['coef'][f]:+.4f}  mean {out['feature_means'][f]:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
