"""온전(穩全) — Streamlit 데모 UI.

실행: .venv/bin/python -m streamlit run app.py
API 키 없이(MockLLM 경로) 전 구간 데모 가능. ANTHROPIC_API_KEY가 있으면
what-if·룰 추출이 실제 LLM으로 동작한다. 숫자는 전부 L2/L3에서 온다.

디자인: 등기부 문서 세계관(잉크·서류·관인 인장) + 금융 신뢰 팔레트.
모션은 절제 — press 피드백만, prefers-reduced-motion 존중.
"""

from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))  # editable 설치 없이도 실행되도록

import matplotlib
import matplotlib.pyplot as plt
import streamlit as st

from onjeon.compare import run_comparison
from onjeon.config import load_env
from onjeon.display import citation_label, krw_man
from onjeon.l0.rule_pipeline import pipeline as rule_pipeline
from onjeon.l2.model import train
from onjeon.l2.synth import generate
from onjeon.l3.eligibility import evaluate
from onjeon.l4.agent import WhatIfAgent
from onjeon.llm import MockLLM, default_llm, make_llm
from onjeon.rules_io import load_products, load_rules

# ── 디자인 토큰 ────────────────────────────────────────────────────
INK = "#1B2233"      # 본문·헤딩 잉크
SLATE = "#5C6675"    # 보조 텍스트
PAPER = "#F5F7FA"    # 서류 백색 배경
CARD = "#FFFFFF"
TRUST = "#2F4B7C"    # 명목비용 (신뢰 남색)
RISK = "#C94F4E"     # 기대손실
SEAL = "#C0392B"     # 관인 인장
SAFE = "#2E7D64"     # 자격 충족
ACCENT = "#FFB300"   # KB 옐로

import matplotlib.font_manager as _fm

for _font_path in _fm.findSystemFonts(fontpaths=["/usr/share/fonts/truetype/nanum"]):
    _fm.fontManager.addfont(_font_path)  # Streamlit Cloud(Linux): packages.txt의 fonts-nanum
matplotlib.rcParams["font.family"] = ["AppleGothic", "NanumGothic", "Malgun Gothic", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

FIXTURES = ROOT / "data" / "fixtures"

FEATURE_LABELS = {
    "jeonse_ratio": "전세가율",
    "lien_ratio": "근저당/시세 비율",
    "is_villa": "건물유형(빌라)",
    "auction_rate": "낙찰가율",
}

CSS = f"""
<style>
:root {{
  --ink: {INK}; --slate: {SLATE}; --paper: {PAPER}; --card: {CARD};
  --trust: {TRUST}; --risk: {RISK}; --seal: {SEAL}; --safe: {SAFE}; --accent: {ACCENT};
}}
html, body, [class*="css"] {{
  font-family: "Pretendard", "Apple SD Gothic Neo", -apple-system, system-ui, sans-serif;
  font-variant-numeric: tabular-nums;
}}
/* 헤드라인: 큰 글자는 네거티브 트래킹, 타이트한 행간 */
.onj-hero {{
  background: var(--card);
  border: 1px solid #E4E8EF;
  border-left: 4px solid var(--accent);
  border-radius: 14px;
  padding: 1.4rem 1.6rem 1.2rem;
  margin-bottom: 1.1rem;
  position: relative;
  overflow: hidden;
}}
.onj-hero h2 {{
  font-size: 1.55rem; line-height: 1.2; letter-spacing: -0.02em;
  font-weight: 800; color: var(--ink); margin: 0 0 0.35rem;
}}
.onj-hero p {{ color: var(--slate); font-size: 0.92rem; margin: 0; }}
.onj-hero .amount {{ color: var(--risk); font-weight: 700; }}

/* 시그니처: 등기부 관인 인장 */
.onj-seal {{
  position: absolute; right: 1.4rem; top: 50%;
  transform: translateY(-50%) rotate(-8deg);
  width: 76px; height: 76px; border-radius: 50%;
  border: 3px double var(--seal); color: var(--seal);
  display: flex; align-items: center; justify-content: center;
  font-weight: 800; font-size: 1.05rem; letter-spacing: 0.1em;
  opacity: 0.9;
  mix-blend-mode: multiply;
}}

/* 3안 카드 */
.onj-option {{
  background: var(--card); border: 1px solid #E4E8EF; border-radius: 12px;
  padding: 0.95rem 1.1rem; height: 100%;
  transition: transform 140ms ease-out, box-shadow 140ms ease-out;
}}
.onj-option:hover {{ transform: translateY(-2px); box-shadow: 0 6px 18px rgba(27,34,51,0.08); }}
.onj-option .label {{ font-size: 0.82rem; color: var(--slate); letter-spacing: 0.02em; }}
.onj-option .value {{
  font-size: 1.7rem; font-weight: 800; letter-spacing: -0.02em; color: var(--ink);
  line-height: 1.15;
}}
.onj-option .eloss {{ font-size: 0.82rem; color: var(--risk); font-weight: 600; }}
.onj-option.best {{ border: 1.5px solid var(--accent); background: #FFFDF4; }}

/* 인용 리스트 */
.onj-cite {{ font-size: 0.88rem; color: var(--ink); }}
.onj-cite li {{ margin-bottom: 0.3rem; }}
.onj-cite .loc {{
  background: #EEF1F6; border-radius: 5px; padding: 0.05rem 0.4rem;
  font-size: 0.8rem; color: var(--trust); font-weight: 600;
}}

/* 버튼: press 즉각 피드백 (Apple — pointer-down 반응) */
.stButton > button {{ transition: transform 100ms ease-out; }}
.stButton > button:active {{ transform: scale(0.97); }}

@media (prefers-reduced-motion: reduce) {{
  .onj-option, .stButton > button {{ transition: none !important; }}
  .onj-option:hover {{ transform: none; }}
}}
</style>
"""


load_env()  # .env → 환경변수 (이미 설정된 값은 유지)


def _bridge_streamlit_secrets() -> None:
    """Streamlit Cloud의 st.secrets를 환경변수로 브리지 (로컬엔 영향 없음)."""
    try:
        for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "ONJEON_MODEL", "MOLIT_API_KEY"):
            if not os.environ.get(key) and key in st.secrets:
                os.environ[key] = str(st.secrets[key])
    except Exception:
        pass  # secrets.toml 부재 등 — 키 없이도 데모는 동작해야 한다


_bridge_streamlit_secrets()


@st.cache_resource
def risk_model():
    return train(generate(1500, seed=42))


@st.cache_data
def load_fixture(name: str):
    path = FIXTURES / name
    if name.endswith(".json"):
        return json.loads(path.read_text(encoding="utf-8"))
    return path.read_text(encoding="utf-8")


def styled_fig(figsize):
    fig, ax = plt.subplots(figsize=figsize)
    fig.patch.set_facecolor("none")
    ax.set_facecolor("none")
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color("#D5DAE3")
    ax.tick_params(colors=SLATE, labelsize=9)
    return fig, ax


st.set_page_config(page_title="온전(穩全)", page_icon="🏠", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)

st.title("온전(穩全)")
st.caption(
    '"이 집, 위험을 감안하면 전세가 월세보다 정말 싼가?" — '
    "숫자는 결정론 엔진(L3)과 ML(L2)이, 해석·인용만 LLM이 담당합니다."
)

# ── 사이드바: 페르소나 ─────────────────────────────────────────────
persona_default = load_fixture("persona_kim.json")
with st.sidebar:
    st.header("👤 페르소나")
    persona = {
        "name": persona_default["name"],
        "age": st.number_input("나이", 19, 45, persona_default["age"]),
        "annual_income_krw": st.number_input(
            "연소득(원)", 0, 200_000_000, persona_default["annual_income_krw"], step=1_000_000
        ),
        "assets_krw": st.number_input(
            "가용자산(원)", 0, 500_000_000, persona_default["assets_krw"], step=1_000_000
        ),
        "expected_stay_years": st.number_input(
            "거주 예정(년)", 1, 10, persona_default["expected_stay_years"]
        ),
    }
    st.divider()
    api_llm = default_llm()
    _provider = {"GeminiLLM": "Gemini API 연결됨", "AnthropicLLM": "Anthropic API 연결됨"}
    st.caption("🔌 LLM: " + _provider.get(type(api_llm).__name__, "오프라인 데모 (MockLLM)"))

villa = load_fixture("register_risky_villa.json")
officetel = load_fixture("register_safe_officetel.json")
model = risk_model()
report = run_comparison(persona=persona, villa_doc=villa, officetel_doc=officetel, model=model)

# ── 히어로: 결론 먼저, 관인 인장 ───────────────────────────────────
best = report["best"]
jeonse = report["jeonse"]
gap_vs_wolse = report["jeonse"]["total"] - report["wolse"]["total"]
st.markdown(
    f"""
<div class="onj-hero">
  <h2>{persona['name']}님, 이 빌라 전세는 <span class="amount">기대손실 연 {krw_man(jeonse['e_loss'])}</span>을 반영하면<br/>월세보다 연 {krw_man(abs(gap_vs_wolse))} {'비쌉니다' if gap_vs_wolse > 0 else '쌉니다'}.</h2>
  <p>보증금 미회수 위험을 원(₩)으로 환산해 세후 총비용에 더한 결과입니다. 근거는 아래에 전부 인용됩니다.</p>
  <div class="onj-seal">{best}<br/>유리</div>
</div>
""",
    unsafe_allow_html=True,
)

tab_compare, tab_eligibility, tab_whatif, tab_l0 = st.tabs(
    ["📊 3안 비교", "✅ 대출 자격", "🔮 What-if", "⚙️ 룰 추출 라이브 (L0)"]
)

# ── 탭 1: 3안 비교 ────────────────────────────────────────────────
with tab_compare:
    cols = st.columns(3)
    for col, key in zip(cols, ("jeonse", "wolse", "buy")):
        option = report[key]
        is_best = best in option["label"]
        eloss_html = (
            f'<div class="eloss">+ 기대손실 {krw_man(option["e_loss"])}</div>'
            if option["e_loss"]
            else '<div class="eloss" style="color:var(--slate);font-weight:400;">기대손실 없음</div>'
        )
        with col:
            st.markdown(
                f"""
<div class="onj-option{' best' if is_best else ''}">
  <div class="label">{option['label']}{' · 최적' if is_best else ''}</div>
  <div class="value">{krw_man(option['total'])}<span style="font-size:0.85rem;color:var(--slate);font-weight:500;"> /년</span></div>
  {eloss_html}
</div>
""",
                unsafe_allow_html=True,
            )

    st.write("")
    fig, ax = styled_fig((8.5, 2.4))
    keys = ["jeonse", "wolse", "buy"]
    labels = [report[k]["label"] for k in keys]
    nominal = [report[k]["nominal"] / 10_000 for k in keys]
    e_loss = [report[k]["e_loss"] / 10_000 for k in keys]
    ax.barh(labels, nominal, color=TRUST, label="명목비용", height=0.55)
    ax.barh(labels, e_loss, left=nominal, color=RISK, label="기대손실 E[Loss]", height=0.55)
    ax.set_xlabel("연간 비용 (만원)", color=SLATE, fontsize=9)
    ax.invert_yaxis()
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    st.pyplot(fig, clear_figure=True)

    left, right = st.columns(2)
    with left:
        st.markdown("##### 이 매물(빌라)의 위험이 높은 이유")
        explain = report["jeonse"]["explain"]
        names = [FEATURE_LABELS[n] for n, _ in explain["contributions"]]
        values = [v for _, v in explain["contributions"]]
        fig2, ax2 = styled_fig((6, 2.2))
        ax2.barh(names, values, color=[RISK if v > 0 else TRUST for v in values], height=0.5)
        ax2.axvline(0, color="#B9C0CC", linewidth=0.8)
        ax2.set_xlabel("logit 기여도 (+위험↑)", color=SLATE, fontsize=9)
        ax2.invert_yaxis()
        st.pyplot(fig2, clear_figure=True)
        st.caption(
            f"P(사고) = {explain['p']:.1%} · LGD = {report['jeonse']['lgd']:.1%} · "
            f"E[Loss] = P × LGD × 보증금 = {krw_man(report['jeonse']['e_loss'])}/년"
        )
        st.warning(f"⚠️ {explain['data_note']}")

    with right:
        st.markdown("##### 근거 — 원문 인용")
        citations_html = "".join(
            f"<li>{citation_label(c)}</li>" for c in report["jeonse"]["citations"]
        )
        sources = report["sources"]
        st.markdown(
            f"""
<ul class="onj-cite">
  {citations_html}
  <li>시세 — 국토부 실거래가 <span class="loc">기준일 {sources['market_price_queried_at']}</span></li>
  <li>낙찰가율 — {sources['auction_rates_source']} <span class="loc">기준일 {sources['auction_rates_queried_at']}</span></li>
  <li>세제 룰 <span class="loc">{sources['tax_rules_version']}</span> · 시장 파라미터 <span class="loc">{sources['market_params_version']}</span></li>
</ul>
""",
            unsafe_allow_html=True,
        )

# ── 탭 2: 대출 자격 ───────────────────────────────────────────────
with tab_eligibility:
    st.subheader("정책상품 자격 판정 — 미자격이면 '왜, 얼마나'까지")
    user = {
        "age": persona["age"],
        "annual_income_krw": persona["annual_income_krw"],
        "assets_krw": persona["assets_krw"],
        "deposit_krw": villa["offer"]["jeonse_deposit_krw"],
    }
    for product in load_products():
        result = evaluate(user, product)
        with st.container(border=True):
            if result["eligible"]:
                st.markdown(f"✅ **{result['product_name']}** — 자격 충족 ({result['version']})")
            else:
                st.markdown(f"❌ **{result['product_name']}** — 미자격 ({result['version']})")
                for failure in result["failed"]:
                    gap_text = (
                        f" (기준 대비 **{krw_man(failure['gap'])} 초과**)"
                        if isinstance(failure["gap"], (int, float)) and failure["gap"] > 0
                        else ""
                    )
                    st.markdown(
                        f"- 위반 조항: {failure['clause']} — "
                        f"{failure['field']} {failure['op']} {failure['limit']:,} 요건, "
                        f"현재 {failure['actual']:,}{gap_text}"
                    )
                if result["alternatives"]:
                    st.markdown(f"- 💡 차선 상품: `{'`, `'.join(result['alternatives'])}`")

# ── 탭 3: What-if ─────────────────────────────────────────────────
with tab_whatif:
    st.subheader('"연봉이 오르면?" — LLM은 파라미터만 바꾸고, 계산은 엔진이')

    def comparison_tool(params: dict) -> dict:
        patched = {**persona, **{k: v for k, v in params.items() if k in persona or k.endswith("_krw")}}
        new_report = run_comparison(
            persona=patched, villa_doc=villa, officetel_doc=officetel, model=model
        )
        return {
            "jeonse_total": new_report["jeonse"]["total"],
            "wolse_total": new_report["wolse"]["total"],
            "buy_total": new_report["buy"]["total"],
            "best": new_report["best"],
        }

    question = st.text_input("질문", placeholder="예: 연봉 500만원 오르면 결론이 바뀌나요?")
    if st.button("실행", disabled=not question):
        if api_llm:
            agent = WhatIfAgent(api_llm, dict(persona), {"run_comparison": comparison_tool})
            result = agent.ask(question)
            st.markdown(result["answer"])
            with st.expander("엔진 호출 기록 (숫자의 출처)"):
                st.json({"calls": result["tool_calls"], "results": result["tool_results"]})
        else:
            # 오프라인 데모: LLM 없이 결정론 재실행 — 시나리오 고정 (연봉 +500만)
            patched = copy.deepcopy(persona)
            patched["annual_income_krw"] += 5_000_000
            before = comparison_tool(persona)
            after = comparison_tool(patched)
            st.info(
                "오프라인 데모 모드: '연봉 +500만원' 시나리오로 엔진을 재실행했습니다. "
                "(API 키 연결 시 자연어 질문을 LLM이 파라미터로 번역합니다)"
            )
            st.markdown(
                f"- 변경 전: 월세 {krw_man(before['wolse_total'])} / 전세 {krw_man(before['jeonse_total'])} → 최적 **{before['best']}**\n"
                f"- 변경 후: 월세 {krw_man(after['wolse_total'])} / 전세 {krw_man(after['jeonse_total'])} → 최적 **{after['best']}**"
            )

# ── 탭 4: L0 룰 추출 라이브 ────────────────────────────────────────
with tab_l0:
    st.subheader("정책 공고 → 자격요건 JSON → 즉시 자격 판정")
    st.caption("추출 LLM과 검증 LLM은 분리되어 있고, 경계값 테스트 통과분만 반영됩니다.")
    announcement = st.text_area("공고 원문", load_fixture("announcement_sample.txt"), height=220)
    if st.button("룰 추출 실행"):
        if api_llm:
            extract_llm, verify_llm = make_llm(), make_llm()
        else:
            demo_rule = {
                "rule_id": "youth-wolse-loan-2026-07",
                "product_name": "청년 주거안정 월세대출",
                "version": "2026-07 기준",
                "source": {"url": "(공고 붙여넣기)", "clause_refs": ["제1호", "제2호", "제3호", "제4호"]},
                "criteria": [
                    {"field": "age", "op": "<=", "value": 34, "clause": "제1호",
                     "boundary_tests": [{"input": 34, "expect": True}, {"input": 35, "expect": False}]},
                    {"field": "annual_income_krw", "op": "<=", "value": 50_000_000, "clause": "제2호",
                     "boundary_tests": [{"input": 50_000_000, "expect": True}, {"input": 50_000_001, "expect": False}]},
                    {"field": "assets_krw", "op": "<=", "value": 337_000_000, "clause": "제3호",
                     "boundary_tests": [{"input": 337_000_000, "expect": True}]},
                    {"field": "deposit_krw", "op": "<=", "value": 300_000_000, "clause": "제4호",
                     "boundary_tests": [{"input": 300_000_000, "expect": True}]},
                ],
                "alternatives": [],
            }
            extract_llm = MockLLM(["```json\n" + json.dumps(demo_rule, ensure_ascii=False) + "\n```"])
            verify_llm = MockLLM([json.dumps({"consistent": True, "confidence": "high", "issues": []})])
            st.info("오프라인 데모 모드: 준비된 추출 결과로 파이프라인 전 단계를 시연합니다.")

        result = rule_pipeline(announcement, extract_llm=extract_llm, verify_llm=verify_llm)

        status = "✅ 승인 — 룰 DB 반영 가능" if result.approved else (
            "🕐 사람 승인 대기" if result.needs_human else "❌ 반영 거부"
        )
        st.markdown(f"**파이프라인 결과: {status}**")
        for reason in result.reasons:
            st.markdown(f"- {reason}")
        with st.expander("추출된 룰 JSON", expanded=True):
            st.json(result.rule)

        if result.approved:
            st.markdown("##### ⚡ 페르소나 자격 즉시 갱신")
            user = {
                "age": persona["age"],
                "annual_income_krw": persona["annual_income_krw"],
                "assets_krw": persona["assets_krw"],
                "deposit_krw": villa["offer"]["jeonse_deposit_krw"],
            }
            verdict = evaluate(user, result.rule)
            if verdict["eligible"]:
                st.success(f"{persona['name']}님은 **{verdict['product_name']}** 자격을 충족합니다.")
            else:
                st.error(f"{persona['name']}님은 미자격 — 사유: {verdict['failed']}")

st.divider()
st.caption(
    "한계 고지: 본 데모는 정보 제공이며 법률 자문이 아닙니다. 등기부 외 리스크(임대인 체납 등)는 "
    "커버하지 않으며 보증보험 가입을 권장합니다. L2 모델은 합성 데이터 기반 구조 시연입니다. "
    "[확인] 표기 수치는 제출 전 최신 기준 재검증 대상입니다."
)
