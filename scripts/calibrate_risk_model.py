"""공개 통계에 보정한 L2 위험 계수 생성 (오프라인 전용).

왜 필요한가 — 이전 방식의 문제:
    synth.py가 지어낸 계수로 합성 데이터를 만들고, 그걸 다시 학습해 배포 계수로 썼다.
    순환이다. 게다가 사고 표본이 ~32건뿐이라 sklearn L2 정규화가 계수를 40~60%
    수축시켜서, 결과는 "현실에서 온 것도 아니고 합성 설계에 충실하지도 않은" 값이었다.
    헤드라인 E[Loss]는 전세가율 계수에 16배 민감하다(0.5x~2x → 130만~2,110만원).

이 스크립트가 하는 일:
    한국부동산원·국토부가 공개한 시군구별 (전세가율, 보증사고율, 경매낙찰가율)을
    관측치로 삼아 로지스틱 계수를 적합한다. 마이크로데이터 없이 집계 마진에 맞추는
    표준 기법이다. 계수 4개 중 3개가 실측에서 나오고, lien_ratio만 가정으로 남는다.

    데이터: data/reference/rtech_rental_market_2026-06.xls
    출처:   https://rtech.or.kr/portal/rental/rentalMarket.do (부동산테크, 국토부·한국부동산원)

사용:
    .venv/bin/python scripts/calibrate_risk_model.py            # 2026-08 버전 생성
    .venv/bin/python scripts/calibrate_risk_model.py --dry-run  # 파일 안 쓰고 진단만

반드시 함께 읽을 한계 (rules JSON의 limitations에도 기록된다):
    1. 생태학적 오류 — 지역 집계로 구한 계수를 개별 매물에 적용하는 건 비약이다.
    2. 사고율이 금액 기준(사고금액/만기도래금액)이라 건 단위 확률과 정의가 다르다.
    3. HUG 보증 **가입** 매물만의 통계다. 미가입 매물은 더 위험할 수 있다(과소평가 방향).
    4. lien_ratio(근저당비율)는 이 데이터에 없어 여전히 가정값이다.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from onjeon.l2.model import FEATURES  # noqa: E402

REFERENCE = ROOT / "data/reference"
# 시점별 파일: rtech_rental_market_YYYY-MM.xls (서울 전용 파일은 _seoul_ 로 제외)
SOURCE_GLOB = "rtech_rental_market_[0-9]*.xls"
RULES = ROOT / "src" / "onjeon" / "rules"
SOURCE_URL = "https://rtech.or.kr/portal/rental/rentalMarket.do"
SOURCE_NAME = "한국부동산원 부동산테크 — 임대차 시장 정보(국토교통부 공동)"
PERIOD_NOTE = "보증사고·경매낙찰은 최근 3개월 누계, 전세가율은 최근 3개월"

# 다운로드 파일은 확장자만 .xls이고 실제로는 HTML 테이블이다(정부 사이트 관행).
_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
_TD = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
_AGGREGATE_ROWS = {"전국", "수도권", "지방"}

# 컬럼 순서(파일 헤더 기준):
#  0 시도 | 1 시군구 | 2~3 아파트 전세가율(1년, 3개월) | 4~5 연립다세대 전세가율(1년, 3개월)
#  6 사고건수 | 7 사고금액(원) | 8 사고율(%) | 9 경매건수 | 10 낙찰건수 | 11 낙찰률(%) | 12 낙찰가율(%)
COL = {"apt_3m": 3, "rh_3m": 5, "acc_cnt": 6, "acc_amt": 7, "acc_rate": 8, "auction_rate": 12}


def _num(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def read_rows(path: Path) -> list[list[str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    out = []
    for tr in _TR.findall(raw):
        cells = [html.unescape(_TAG.sub("", c)).replace("\xa0", " ").strip() for c in _TD.findall(tr)]
        if len(cells) == 13:
            out.append(cells)
    return out


def build_observations(rows: list[list[str]]) -> list[dict]:
    """시군구 × 주택유형 → 관측치. 집계행(전국/수도권/지방/소계)은 중복이라 제외한다.

    노출액(만기도래금액)은 사고금액 ÷ 사고율로 역산한다. 이게 있어야 사고율 100%인
    소규모 시군구가 회귀를 지배하는 걸 막을 수 있다.
    """
    obs = []
    for r in rows:
        sido, sigungu = r[0], r[1]
        if sido in _AGGREGATE_ROWS or sigungu in ("-", "소계"):
            continue
        acc_rate = _num(r[COL["acc_rate"]])
        acc_amt = _num(r[COL["acc_amt"]])
        auction = _num(r[COL["auction_rate"]])
        if acc_rate is None or acc_rate <= 0 or not acc_amt or not auction:
            continue
        exposure = acc_amt / (acc_rate / 100.0)  # 만기도래금액 역산
        for key, is_villa in (("apt_3m", 0), ("rh_3m", 1)):
            jeonse = _num(r[COL[key]])
            if not jeonse:
                continue
            obs.append({
                "region": f"{sido} {sigungu}",
                "jeonse_ratio": jeonse / 100.0,
                "lien_ratio": None,  # 이 데이터에 없다 — 가정값으로 남긴다
                "is_villa": is_villa,
                "auction_rate": auction / 100.0,
                "accident_rate": acc_rate / 100.0,
                "exposure_krw": exposure,
            })
    return obs


def fit(obs: list[dict], lien_coef: float, lien_mean: float) -> dict:
    """노출액 가중 이항 로지스틱 적합.

    각 관측치의 사고율은 비율이므로, 노출액에 비례한 (사고, 무사고) 가중치를 준
    두 행으로 펼쳐서 표준 로지스틱에 넣는다. 규제는 끄고(C 크게) 집계 마진을 그대로
    재현하게 한다 — 여기서 수축시키면 지금 고치려는 문제가 재발한다.
    """
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    fit_features = ["jeonse_ratio", "is_villa", "auction_rate"]
    X, y, w = [], [], []
    scale = max(o["exposure_krw"] for o in obs)  # 가중치 수치 안정화
    for o in obs:
        row = [o[f] for f in fit_features]
        weight = o["exposure_krw"] / scale
        X += [row, row]
        y += [1, 0]
        w += [weight * o["accident_rate"], weight * (1 - o["accident_rate"])]
    clf = LogisticRegression(max_iter=5000, C=1e6)  # 사실상 무규제
    clf.fit(np.array(X), np.array(y), sample_weight=np.array(w))

    coef = dict(zip(fit_features, (float(c) for c in clf.coef_[0])))
    coef["lien_ratio"] = lien_coef
    means = {f: float(np.average([o[f] for o in obs], weights=[o["exposure_krw"] for o in obs]))
             for f in fit_features}
    means["lien_ratio"] = lien_mean

    # lien_ratio는 적합에 없었으므로 절편이 그 항 없이 보정됐다. 그대로 두고 나중에
    # lien 항을 더하면 모든 예측이 lien_coef × lien_mean 만큼 부풀어 마진이 깨진다
    # (실측: 전국 1.05% → 예측 3.40%). 평균 근저당비율에서 중립이 되도록 절편을 옮긴다 —
    # 그러면 평균에서는 보정된 사고율이 그대로 나오고, 평균 대비 편차만 위험을 움직인다.
    intercept = float(clf.intercept_[0]) - lien_coef * lien_mean
    return {
        "coef": {f: coef[f] for f in FEATURES},
        "intercept": intercept,
        "feature_means": {f: means[f] for f in FEATURES},
        "n_obs": len(obs),
    }


def diagnostics(obs: list[dict], model: dict) -> dict:
    """보정이 실제로 마진을 재현하는지 — 이게 검증 가능한 주장의 근거다."""
    import math

    def predict(o):
        z = model["intercept"] + sum(
            model["coef"][f] * (o[f] if f != "lien_ratio" else model["feature_means"]["lien_ratio"])
            for f in FEATURES
        )
        return 1 / (1 + math.exp(-z))

    def weighted(items, value):
        tot = sum(o["exposure_krw"] for o in items)
        return sum(o["exposure_krw"] * value(o) for o in items) / tot if tot else 0.0

    out = {"overall": {"actual": weighted(obs, lambda o: o["accident_rate"]),
                       "predicted": weighted(obs, predict)}}
    for label, flag in (("아파트", 0), ("연립·다세대", 1)):
        sub = [o for o in obs if o["is_villa"] == flag]
        if sub:
            out[label] = {"actual": weighted(sub, lambda o: o["accident_rate"]),
                          "predicted": weighted(sub, predict), "n": len(sub)}
    lo = [o for o in obs if o["jeonse_ratio"] < 0.7]
    hi = [o for o in obs if o["jeonse_ratio"] >= 0.7]
    for label, sub in (("전세가율<70%", lo), ("전세가율>=70%", hi)):
        if sub:
            out[label] = {"actual": weighted(sub, lambda o: o["accident_rate"]),
                          "predicted": weighted(sub, predict), "n": len(sub)}
    return out


def _period_of(path: Path) -> str:
    m = re.search(r"(\d{4}-\d{2})", path.stem)
    return m.group(1) if m else path.stem


def main() -> int:
    dry = "--dry-run" in sys.argv
    version = next((a for a in sys.argv[1:] if not a.startswith("--")), "2026-08")
    files = sorted(p for p in REFERENCE.glob(SOURCE_GLOB) if "_seoul" not in p.name)
    if not files:
        print(f"원천 파일 없음: {REFERENCE}/{SOURCE_GLOB}", file=sys.stderr)
        return 1

    from onjeon.l2.synth import TRUE_COEF  # 가정값 출처를 명시적으로 가져온다

    lien_coef, lien_mean = TRUE_COEF["lien_ratio"], 0.4

    # 시점별 적합 — 계수가 시점에 얼마나 흔들리는지가 곧 P의 불확실성이다.
    periods, all_obs = [], []
    for path in files:
        obs = build_observations(read_rows(path))
        if len(obs) < 50:
            print(f"  건너뜀 {path.name}: 관측치 {len(obs)}개 (전국 데이터인지 확인)", file=sys.stderr)
            continue
        m = fit(obs, lien_coef, lien_mean)
        periods.append({"period": _period_of(path), "file": path.name,
                        "n_obs": m["n_obs"], "coef": m["coef"], "intercept": m["intercept"],
                        "actual_overall": diagnostics(obs, m)["overall"]["actual"]})
        all_obs += obs
    if not periods:
        print("쓸 수 있는 시점이 없다", file=sys.stderr)
        return 1

    pooled = fit(all_obs, lien_coef, lien_mean)
    diag = diagnostics(all_obs, pooled)

    print(f"시점 {len(periods)}개 · 관측치 합계 {pooled['n_obs']}개 (시군구 × 주택유형, 노출액 가중)")
    for p in periods:
        print(f"  {p['period']}  n={p['n_obs']:>3}  전국 사고율 {p['actual_overall']*100:5.2f}%  "
              f"절편 {p['intercept']:+.3f}  전세가율 {p['coef']['jeonse_ratio']:+.3f}  "
              f"빌라 {p['coef']['is_villa']:+.3f}  낙찰가율 {p['coef']['auction_rate']:+.3f}")
    print(f"\n통합(pooled) 절편 {pooled['intercept']:+.4f}")
    for f in FEATURES:
        tag = "  [확인·가정값]" if f == "lien_ratio" else ""
        print(f"  {f:14s} {pooled['coef'][f]:+.4f}{tag}")
    print("\n마진 재현 (노출액 가중, 전체 시점):")
    for k, v in diag.items():
        n = f"  n={v['n']}" if "n" in v else ""
        print(f"  {k:16s} 실측 {v['actual']*100:5.2f}%  모델 {v['predicted']*100:5.2f}%{n}")
    if len(periods) == 1:
        print("\n⚠️ 시점이 1개뿐이라 P 밴드를 만들 수 없다 — 다른 연도 파일을 추가하면 밴드가 생긴다")

    if dry:
        print("\n--dry-run: 파일을 쓰지 않았다")
        return 0

    out = {
        "version": version,
        "queried_at": date.today().isoformat(),
        "model": "logistic_regression",
        "calibration": "aggregate_marginal",
        "features": FEATURES,
        "coef": pooled["coef"],
        "intercept": pooled["intercept"],
        "feature_means": pooled["feature_means"],
        # 시점별 계수 — 런타임이 P의 밴드를 만드는 근거. 사고율은 시점에 크게 흔들리므로
        # (2023-05 8.1% → 2026-06 1.0%) 점추정 하나만 내면 거짓 정밀도다.
        "periods": [{k: p[k] for k in ("period", "coef", "intercept", "n_obs", "actual_overall")}
                    for p in periods],
        "data_note": (
            f"공개 통계 보정 — {SOURCE_NAME}. 시점 {len(periods)}개"
            f"({', '.join(p['period'] for p in periods)}), 시군구×주택유형 {pooled['n_obs']}개 관측치. "
            "학습 데이터가 아니라 집계 마진 보정이다."
        ),
        "prob_definition": (
            "사고율 = 보증사고금액 ÷ 보증만기도래금액. **만기 도래 1회당** 금액 기준 비율이며, "
            "건 단위 연간 확률이 아니다. 계약기간(보통 2년)당 확률에 가깝게 읽어야 한다."
        ),
        "source": {"name": SOURCE_NAME, "url": SOURCE_URL, "period_note": PERIOD_NOTE,
                   "files": [p["file"] for p in periods]},
        "calibration_check": diag,
        "limitations": [
            "생태학적 오류 — 시군구 집계로 구한 계수를 개별 매물에 적용하는 것은 비약이다. "
            "마이크로데이터가 없을 때의 표준 대안이며, 개별 수준 관계와 다를 수 있다.",
            "사고율이 금액 기준(사고금액/만기도래금액)이라 건 단위 확률과 정의가 다르다 [확인].",
            "HUG 보증 가입 매물만의 통계다. 미가입 매물은 더 위험할 수 있어 과소평가 방향이다 [확인].",
            "lien_ratio(근저당비율) 계수는 이 데이터에 없어 가정값이다 [확인: 실측 대체 필요].",
            "전세가율과 낙찰가율이 상관돼 있어 효과가 낙찰가율로 흡수됐을 수 있다(다중공선성) [확인].",
            "시점 변동이 커서 계수가 흔들린다 — periods의 시점별 계수로 P 밴드를 낸다.",
        ],
    }
    path = RULES / f"risk_model_{version}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {path.relative_to(ROOT)}  (시점 {len(periods)}개)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
