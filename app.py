"""온전(穩全) — Streamlit 데모 UI.

실행: .venv/bin/python -m streamlit run app.py
API 키 없이(MockLLM 경로) 전 구간 데모 가능. ANTHROPIC_API_KEY가 있으면
what-if·룰 추출이 실제 LLM으로 동작한다. 숫자는 전부 L2/L3에서 온다.

디자인: KB국민은행 컬러 팔레트 + Apple Liquid Glass(글래스모피즘) UI/UX.
모션은 유체처럼 부드럽고 탄성있는 트랜지션(Emil Kowalski 스타일) 적용.
"""

from __future__ import annotations

import copy
import hashlib
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
from onjeon.data_pipeline.molit import live_market_price
from onjeon.data_pipeline.regions import SEOUL_LAWD_CD
from onjeon.display import citation_label, krw_man
from onjeon.l0.rule_pipeline import pipeline as rule_pipeline
from onjeon.l1.parser import parse_register
from onjeon.l1.pdf import pdf_to_images
from onjeon.l1.schema import ExtractionInvalid
from onjeon.l2.model import train
from onjeon.l2.synth import generate
from onjeon.l3.eligibility import evaluate
from onjeon.l4.agent import WhatIfAgent
from onjeon.llm import MockLLM, default_llm, make_llm
from onjeon.rag.documents import collect_documents
from onjeon.rag.index import ClauseIndex
from onjeon.rules_io import load_products, load_rules

# ── 디자인 토큰 (KB국민은행 + Apple Glassmorphism) ─────────────────────
INK = "#2B2A26"      # KB 텍스트 (Deep Brown/Gray)
SLATE = "#7A766C"    # 보조 텍스트
MUTED = "#A39F93"    # 축·미세 텍스트
PAPER = "#F7F7F7"    # 베이스 배경 
CARD = "rgba(255, 255, 255, 0.65)" # 글래스모피즘 베이스
TRUST = "#FFCC00"    # KB Yellow — 명목비용·주요 강조
RISK = "#FF5252"     # 기대손실·위험 (부드러운 Red)
SAFE = "#00C853"     # 긍정
ACCENT = "#FFD733"   # 최적 하이라이트 (KB Yellow Light)
YELLOW_TINT = "rgba(255, 204, 0, 0.15)" # 노란색 글래스 틴트

import matplotlib.font_manager as _fm

for _font_path in _fm.findSystemFonts(fontpaths=["/usr/share/fonts/truetype/nanum"]):
    _fm.fontManager.addfont(_font_path)  # Streamlit Cloud(Linux)
# NanumGothic은 로컬(설치됨)·Cloud(packages.txt fonts-nanum) 양쪽에서 동작 —
# 차트 한글 깨짐(두부) 방지의 핵심. AppleGothic은 Mac 로컬 폴백.
# NanumGothic만 지정 — 로컬(설치됨)·Cloud(fonts-nanum) 공통 동작.
# AppleGothic 등 Mac 전용 폰트를 목록에 두면 Linux(Cloud)에서 렌더마다
# 'findfont not found' 경고가 수천 줄 로그를 도배하므로 제외.
matplotlib.rcParams["font.family"] = ["NanumGothic", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

FIXTURES = ROOT / "data" / "fixtures"

FEATURE_LABELS = {
    "jeonse_ratio": "전세가율",
    "lien_ratio": "근저당/시세 비율",
    "is_villa": "건물유형(빌라)",
    "auction_rate": "낙찰가율",
}

# ── Liquid Glass CSS 주입 ──────────────────────────────────────────
# @import는 스타일시트 최상단이어야 유효(:root보다 앞). Pretendard를 CDN에서
# 로드해 UI에 실제 적용한다. CDN 실패 시 NanumGothic/시스템 폰트로 폴백.
CSS = f"""
<style>
@import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
:root {{
  --ink: {INK}; --slate: {SLATE}; --muted: {MUTED}; --paper: {PAPER}; 
  --card: {CARD}; --primary: {TRUST}; --risk: {RISK}; --safe: {SAFE};
  --accent: {ACCENT}; --tint: {YELLOW_TINT};
  /* 글래스 위 텍스트 전용 — 채움용 --risk(#FF5252)는 대비 부족(3:1)이라
     텍스트는 더 깊은 red를 써 WCAG AA(4.5:1) 확보 (apple-design 배니시티) */
  --risk-text: #D92D20;
  --ink-strong: #1A1917; /* 글래스 위 헤딩 대비 강화 */
  
  /* Liquid / Glass 변수 */
  --glass-blur: blur(24px);
  --glass-border: rgba(255, 255, 255, 0.5);
  --liquid-easing: cubic-bezier(0.175, 0.885, 0.32, 1.15); /* 탄성있는 텐션(Toss press) */
  --ease-out-expo: cubic-bezier(0.16, 1, 0.3, 1); /* Apple 감속(스크롤 리빌) */
}}

/* 스크롤 리빌 — 순수 CSS animation-timeline. JS 불필요, Streamlit 재실행 안전
   (마운트 시점이 아닌 스크롤 위치 기반이라 입력 변경 시 깜빡이지 않음) */
@keyframes onj-reveal {{
  from {{ opacity: 0; transform: translateY(16px); }}
  to   {{ opacity: 1; transform: translateY(0); }}
}}

/* 전체 배경에 은은한 메쉬 그라데이션 부여 (글래스모피즘 극대화) */
.stApp {{
  background: radial-gradient(circle at 15% 10%, #FFFDF5 0%, #F5F7FA 50%, #FFF8E7 100%);
  background-attachment: fixed;
}}

html, body, [class*="css"] {{
  font-family: "Pretendard", "NanumGothic", "Apple SD Gothic Neo", -apple-system, system-ui, sans-serif;
  font-variant-numeric: tabular-nums;
}}

/* 히어로 카드 — Liquid Glass */
.onj-hero {{
  background: var(--card);
  backdrop-filter: var(--glass-blur);
  -webkit-backdrop-filter: var(--glass-blur);
  border: 1px solid var(--glass-border);
  border-radius: 32px;
  padding: 2.2rem 2.2rem 2rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 16px 40px rgba(43, 42, 38, 0.04), inset 0 1px 0 rgba(255,255,255,0.8);
  position: relative;
  overflow: hidden;
}}

/* 히어로 배경에 은은한 빛 효과 추가 */
.onj-hero::before {{
  content: ''; position: absolute; top: -50%; left: -50%; width: 200%; height: 200%;
  background: radial-gradient(circle at 50% 50%, rgba(255,204,0,0.08) 0%, transparent 60%);
  z-index: -1;
}}

/* 아이브로우 — Toss식 배지(핏). 골드 텍스트의 낮은 대비를 배경 틴트로 보완 */
.onj-eyebrow {{
  display: inline-block;
  font-size: 0.75rem; font-weight: 800; color: #8A6A00;
  background: rgba(255, 204, 0, 0.18);
  padding: 0.32rem 0.72rem; border-radius: 999px;
  letter-spacing: 0.01em; margin-bottom: 0.9rem;
}}
/* 디스플레이 헤딩 — 큰 글자는 네거티브 트래킹·타이트 행간 (apple-design §15) */
.onj-hero h2 {{
  font-size: clamp(1.5rem, 2.6vw, 2rem); line-height: 1.28;
  letter-spacing: -0.028em; font-weight: 800;
  color: var(--ink-strong); margin: 0 0 0.7rem;
}}
.onj-hero p {{ color: #6B665C; font-size: 1rem; line-height: 1.6; margin: 0 0 1rem; }}
.onj-hero .amount {{ color: var(--risk-text); font-weight: 800; }}

/* 3안 옵션 카드 — 부드러운 호버 트랜지션 */
.onj-option {{
  background: rgba(255, 255, 255, 0.55);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.7);
  border-radius: 28px;
  padding: 1.4rem 1.4rem; height: 100%;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.03);
  transition: transform 0.3s var(--ease-out-expo), box-shadow 0.3s ease;
}}
/* hover는 정밀 포인터(마우스)에서만 — 터치기기서 hover 고착 방지 */
@media (hover: hover) and (pointer: fine) {{
  .onj-option:hover {{
    transform: translateY(-6px) scale(1.01);
    box-shadow: 0 16px 40px rgba(255, 204, 0, 0.1);
  }}
}}
.onj-option .label {{ font-size: 0.85rem; font-weight: 700; color: var(--slate); }}
.onj-option .value {{
  font-size: clamp(1.7rem, 2.4vw, 2rem); font-weight: 800; letter-spacing: -0.03em;
  color: var(--ink-strong); line-height: 1.15; margin-top: 0.25rem;
}}
.onj-option .eloss {{ font-size: 0.85rem; color: var(--risk-text); font-weight: 700; margin-top: 0.3rem; }}

/* 최적(Best) 카드 — KB 그라데이션 강조 */
.onj-option.best {{ 
  background: linear-gradient(135deg, rgba(255,223,64,0.85) 0%, rgba(255,204,0,0.85) 100%);
  border: 1px solid rgba(255,255,255,0.9);
  box-shadow: 0 12px 32px rgba(255, 204, 0, 0.25), inset 0 1px 0 rgba(255,255,255,0.5);
}}
.onj-option.best .label {{ color: #7A6000; font-weight: 800; }}
.onj-option.best .value {{ color: #2B2A26; }}

/* 인용 리스트 */
.onj-cite {{ font-size: 0.95rem; color: var(--ink); padding-left: 1.2rem; }}
.onj-cite li {{ margin-bottom: 0.45rem; }}
.onj-cite .loc {{ color: var(--slate); font-size: 0.85rem; background: rgba(0,0,0,0.04); padding: 2px 6px; border-radius: 6px; }}

/* Liquid 버튼 디자인 */
.stButton > button {{
  background: linear-gradient(135deg, #FFDF40 0%, #FFCC00 100%) !important;
  color: #2B2A26 !important;
  border: 1px solid rgba(255, 255, 255, 0.5) !important;
  border-radius: 20px !important; /* 애플스러운 큰 라운드 */
  font-weight: 800 !important;
  padding: 0.6rem 1.2rem !important;
  box-shadow: 0 4px 12px rgba(255, 204, 0, 0.3), inset 0 1px 0 rgba(255,255,255,0.6) !important;
  /* press는 140ms 즉각 피드백, 그 외(shadow 등)는 부드럽게 */
  transition: transform 140ms var(--liquid-easing), box-shadow 0.3s ease !important;
}}
@media (hover: hover) and (pointer: fine) {{
  .stButton > button:hover {{
    transform: translateY(-2px);
    box-shadow: 0 8px 20px rgba(255, 204, 0, 0.4), inset 0 1px 0 rgba(255,255,255,0.8) !important;
  }}
}}
.stButton > button:active {{
  transform: scale(0.97); /* press 피드백 — 예산 내 미세 스케일 */
}}

/* Expander, Inputs 등에 Glass 효과 적용 */
.stTextInput>div>div>input, .stNumberInput>div>div>input, .stSelectbox>div>div>div {{
  background: rgba(255, 255, 255, 0.5) !important;
  border-radius: 16px !important;
  border: 1px solid rgba(255, 255, 255, 0.6) !important;
  transition: all 0.3s ease !important;
}}
.stTextInput>div>div>input:focus, .stNumberInput>div>div>input:focus {{
  background: #FFFFFF !important;
  box-shadow: 0 0 0 3px rgba(255, 204, 0, 0.3) !important;
  border-color: #FFCC00 !important;
}}

/* st.container(border=True) — 대출 자격·조항 검색 카드를 히어로/3안과 같은
   글래스 톤으로 통일. 이 testid는 bordered container 전용이라 과적용 안 됨 */
[data-testid="stVerticalBlockBorderWrapper"] {{
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.7) !important;
  border-radius: 18px !important;
  box-shadow: 0 4px 16px rgba(43, 42, 38, 0.03);
}}
/* expander도 같은 글래스로 */
[data-testid="stExpander"] details {{
  background: rgba(255, 255, 255, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.7) !important;
  border-radius: 18px !important;
  overflow: hidden;
}}

/* 스크롤 리빌 유틸 — 하단 근거 패널 등 '가끔 스크롤 시' 보는 영역에만 부여.
   animation-timeline은 스크롤 위치 기반이라 재실행에도 깜빡이지 않는다. */
.onj-reveal {{
  animation: onj-reveal linear both;
  animation-timeline: view();
  animation-range: entry 0% cover 30%;
}}

@media (prefers-reduced-motion: reduce) {{
  .onj-option, .stButton > button, .onj-option:hover {{ transition: none !important; transform: none !important; }}
  /* 리빌은 제거가 아니라 강등 — 위치 이동 없이 즉시 표시(전정계 자극 회피) */
  .onj-reveal {{ animation: none !important; opacity: 1 !important; transform: none !important; }}
}}
</style>
"""

load_env()

def _bridge_streamlit_secrets() -> None:
    try:
        for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "ONJEON_MODEL", "MOLIT_API_KEY"):
            if not os.environ.get(key) and key in st.secrets:
                os.environ[key] = str(st.secrets[key])
    except Exception:
        pass 

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

@st.cache_data
def load_registers() -> dict:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(FIXTURES.glob("register_*.json"))
    }

@st.cache_resource
def clause_index() -> ClauseIndex:
    index = ClauseIndex()
    index.index_documents(collect_documents())
    return index


def parse_uploaded_register(pdf_bytes: bytes, market_price_krw: int, jeonse_deposit_krw: int) -> dict:
    """업로드 PDF → L1 비전 파싱 → 게이트 통과 문서. 같은 파일은 세션 캐시로 재사용."""
    cache_key = hashlib.sha256(pdf_bytes).hexdigest()[:16] + f":{market_price_krw}"
    cache = st.session_state.setdefault("onj_upload_cache", {})
    if cache_key in cache:
        doc = copy.deepcopy(cache[cache_key])
    else:
        images = pdf_to_images(pdf_bytes, max_pages=5)
        with st.spinner("등기부 파싱 중 — L1 비전 추출·스키마 게이트…"):
            doc = parse_register(images, make_llm(), market_price_krw=market_price_krw)
        cache[cache_key] = copy.deepcopy(doc)
    address = doc["property"].get("address", "")
    region = next((tok for tok in address.split() if tok.endswith("구")), None)
    if region:
        doc["property"]["region"] = region  # 낙찰가율 테이블 매칭 (없으면 default 폴백)
    doc["offer"] = {
        "jeonse_deposit_krw": jeonse_deposit_krw,
        "sale_price_krw": doc["property"]["market_price_krw"],
        "insured": False,
        "note": "사용자 업로드 등기부 (시세·보증금 수동 입력)",
    }
    return doc

def styled_fig(figsize):
    """KB 스타일이 가미된 차트"""
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

# ── 사이드바 ───────────────────────────────────────────────────────
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
        # 정책상품 자격 판정에 쓰이는 개인 요건 (룰 DB criteria와 1:1 매핑)
        "is_homeless": st.checkbox("무주택 세대", value=persona_default.get("is_homeless", True)),
        "is_household_head": st.checkbox("세대주", value=persona_default.get("is_household_head", True)),
        "works_at_sme": st.checkbox("중소·중견기업 재직", value=persona_default.get("works_at_sme", False)),
    }
    st.divider()
    st.header("🏘️ 매물 입력")
    registers = load_registers()
    jeonse_names = [n for n, d in registers.items() if "jeonse_deposit_krw" in d.get("offer", {})]
    wolse_names = [n for n, d in registers.items() if "monthly_rent_krw" in d.get("offer", {})]
    input_mode = st.radio(
        "전세 검토 매물 입력 방식", ["샘플 매물 선택", "등기부 PDF 업로드"]
    )
    uploaded_pdf = None
    villa_name = None
    if input_mode == "샘플 매물 선택":
        villa_name = st.selectbox(
            "전세 검토 매물",
            jeonse_names,
            index=jeonse_names.index("register_risky_villa.json") if "register_risky_villa.json" in jeonse_names else 0,
            format_func=lambda n: registers[n]["property"]["address"],
        )
    else:
        uploaded_pdf = st.file_uploader("등기부등본 PDF", type=["pdf"])
        # 실거래가 자동 조회 — 지역구 선택 후 MOLIT 실데이터 중위가로 시세 채움.
        # 버튼을 위젯보다 먼저 처리해 session_state로 값 주입(Streamlit 정석 패턴).
        seoul_regions = list(SEOUL_LAWD_CD)
        st.session_state.setdefault("upload_market_man_widget", 18_500)
        upload_region = st.selectbox(
            "지역구 (실거래가 조회용)", seoul_regions,
            index=seoul_regions.index("관악구"),
        )
        if st.button("📡 실거래가로 시세 자동 조회"):
            if not os.environ.get("MOLIT_API_KEY"):
                st.warning("MOLIT_API_KEY가 필요합니다 (.env 또는 Secrets). 수동 입력하세요.")
            else:
                try:
                    live = live_market_price(upload_region, service_key=os.environ["MOLIT_API_KEY"])
                    st.session_state["upload_market_man_widget"] = live["market_price_krw"] // 10_000
                    st.session_state["onj_live_note"] = (
                        f"✅ {upload_region} 최근 실거래 {live['n']}건 중위가 "
                        f"{krw_man(live['market_price_krw'])} (기준 {live['source']['deal_ym']})"
                    )
                except Exception as exc:
                    st.session_state["onj_live_note"] = f"⚠️ 자동 조회 실패: {exc}"
        if st.session_state.get("onj_live_note"):
            st.caption(st.session_state["onj_live_note"])
        upload_market_man = st.number_input(
            "시세 (만원)", min_value=1_000, max_value=500_000, step=500,
            key="upload_market_man_widget",
            help="등기부에는 시세가 없습니다 — 위 버튼으로 실거래가를 조회하거나 직접 입력하세요",
        )
        upload_deposit_man = st.number_input("전세 보증금 (만원)", 500, 300_000, 15_500, step=500)
    officetel_name = st.selectbox(
        "월세 대안 매물",
        wolse_names,
        format_func=lambda n: registers[n]["property"]["address"],
    )
    st.divider()
    api_llm = default_llm()
    _provider = {"GeminiLLM": "Gemini API 연결됨", "AnthropicLLM": "Anthropic API 연결됨"}
    st.caption("🔌 LLM: " + _provider.get(type(api_llm).__name__, "오프라인 데모 (MockLLM)"))

# ── 전세 검토 매물 결정 (샘플 vs 업로드) ────────────────────────────
villa = None
if input_mode == "등기부 PDF 업로드":
    if uploaded_pdf is None:
        st.info("👈 사이드바에서 등기부등본 PDF를 올리면 실제 매물 분석이 시작됩니다. 그 전까지는 샘플(위험 빌라)을 표시합니다.")
    elif api_llm is None:
        st.warning("PDF 파싱에는 LLM 키가 필요합니다 — `.env` 또는 Streamlit Secrets에 `GEMINI_API_KEY`를 설정하세요. 샘플 매물로 대체 표시합니다.")
    else:
        try:
            villa = parse_uploaded_register(
                uploaded_pdf.getvalue(),
                int(upload_market_man) * 10_000,
                int(upload_deposit_man) * 10_000,
            )
            st.success(f"등기부 파싱 완료: {villa['property']['address']} — 아래 결과는 업로드 매물 기준입니다.")
        except ExtractionInvalid as exc:
            st.error(f"추출 결과가 스키마 게이트에서 차단됐습니다 (하위 레이어 전달 금지 원칙): {exc.errors[:3]}")
        except ValueError as exc:
            st.error(f"PDF 처리 실패: {exc}")
        except Exception as exc:  # LLM API 오류 등 — 데모가 죽지 않게 폴백
            st.error(f"파싱 중 오류: {type(exc).__name__}: {exc}")
if villa is None:
    villa = registers[villa_name or "register_risky_villa.json"]

officetel = registers[officetel_name]
model = risk_model()
report = run_comparison(persona=persona, villa_doc=villa, officetel_doc=officetel, model=model)

# ── 히어로 ─────────────────────────────────────────────────────────
best = report["best"]
jeonse = report["jeonse"]
gap_vs_wolse = report["jeonse"]["total"] - report["wolse"]["total"]
st.markdown(
    f"""
<div class="onj-hero">
  <div class="onj-eyebrow">맞춤형 분석 결과</div>
  <h2>{persona['name']}님, 이 빌라 전세는 <span class="amount">기대손실 연 {krw_man(jeonse['e_loss'])}</span>을 반영하면<br/>월세보다 연 {krw_man(abs(gap_vs_wolse))} {'비쌉니다' if gap_vs_wolse > 0 else '쌉니다'}.</h2>
  <p>보증금 미회수 위험을 원(₩)으로 환산해 세후 총비용에 더한 결과입니다. 하단에서 근거를 확인하세요.</p>
</div>
""",
    unsafe_allow_html=True,
)

tab_compare, tab_eligibility, tab_whatif, tab_l0, tab_rag = st.tabs(
    ["📊 3안 비교", "✅ 대출 자격", "🔮 What-if", "⚙️ 룰 추출 라이브 (L0)", "📚 조항 검색"]
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
  <div class="label">{option['label']}{' ✨ 최적 대안' if is_best else ''}</div>
  <div class="value">{krw_man(option['total'])}<span style="font-size:1rem;color:{'#7A6000' if is_best else 'var(--slate)'};font-weight:600;"> /년</span></div>
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
    # 차트 컬러 KB Yellow 적용
    ax.barh(labels, nominal, color=TRUST, edgecolor="none", label="명목비용", height=0.55)
    ax.barh(labels, e_loss, left=nominal, color=RISK, edgecolor="none", label="기대손실 E[Loss]", height=0.55)
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
        ax2.axvline(0, color="#E2E5EB", linewidth=1)
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
<ul class="onj-cite onj-reveal">
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
    st.subheader("정책상품 자격 판정")
    user = {
        "age": persona["age"],
        "annual_income_krw": persona["annual_income_krw"],
        "assets_krw": persona["assets_krw"],
        "deposit_krw": villa["offer"]["jeonse_deposit_krw"],
        "is_homeless": persona["is_homeless"],
        "is_household_head": persona["is_household_head"],
        "works_at_sme": persona["works_at_sme"],
    }
    for product in load_products():
        result = evaluate(user, product)
        # st.container 자체는 스타일링 한계가 있으나 CSS로 투명도를 조정받습니다.
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
                "is_homeless": persona["is_homeless"],
                "is_household_head": persona["is_household_head"],
                "works_at_sme": persona["works_at_sme"],
            }
            verdict = evaluate(user, result.rule)
            if verdict["eligible"]:
                st.success(f"{persona['name']}님은 **{verdict['product_name']}** 자격을 충족합니다.")
            else:
                st.error(f"{persona['name']}님은 미자격 — 사유: {verdict['failed']}")

            added = clause_index().index_rule(result.rule)
            st.caption(f"⚡ 조항 색인 갱신: {added}건 — '조항 검색' 탭에서 즉시 인용 가능합니다.")

# ── 탭 5: 조항 검색 ───────────────────────────────────────────────
with tab_rag:
    st.subheader("조항 단위 검색 — 룰 DB·세제·공고를 근거 그대로 인용")
    index = clause_index()
    st.caption(
        f"Qdrant 임베디드(비용 0) · 임베더 {type(index.embedder).__name__} · "
        f"색인 {index.count()}건"
    )
    rag_query = st.text_input(
        "질문/키워드", placeholder="예: 연소득 기준이 얼마인가요? / 월세 세액공제"
    )
    if rag_query:
        results = index.search(rag_query, top_k=5)
        if not results:
            st.info("검색 결과가 없습니다 — 다른 키워드로 시도해 보세요.")
        for r in results:
            with st.container(border=True):
                st.markdown(r["text"])
                p = r["payload"]
                meta = " · ".join(
                    x for x in (
                        p.get("source_type", ""),
                        p.get("clause", ""),
                        p.get("version", ""),
                        f"검증일 {p['verified_at']}" if p.get("verified_at") else "",
                        f"유사도 {r['score']:.2f}",
                    ) if x
                )
                st.caption(meta)
                if p.get("url"):
                    st.caption(f"출처: {p['url']}")

st.divider()
st.caption(
    "한계 고지: 본 데모는 정보 제공이며 법률 자문이 아닙니다. 등기부 외 리스크(임대인 체납 등)는 "
    "커버하지 않으며 보증보험 가입을 권장합니다. L2 모델은 합성 데이터 기반 구조 시연입니다. "
    "[확인] 표기 수치는 제출 전 최신 기준 재검증 대상입니다."
)