# 시세 동향 차트 — 백엔드 구현 계획 (Plan 1/2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 업로드 등기부의 시군구·용도에 맞는 국토부 실거래가를 집계해 평당가(만원) 매매/전세 시계열을 내려주는 REST API를 만든다(프론트는 Plan 2).

**Architecture:** 기존 `src/onjeon/`(molit.py 등)을 재사용·확장하고, 순수 함수(평당가·버킷·기간)로 집계 코어를 TDD한 뒤, SQLite 월단위 캐시를 통해 FastAPI 2개 엔드포인트로 노출한다. LLM·유료 요소 없음.

**Tech Stack:** Python 3.12 · requests · tenacity · sqlite3(표준) · FastAPI · pdfplumber · pytest. 관리: uv, `.venv`.

**설계 스펙:** [docs/superpowers/specs/2026-07-23-market-trends-chart-design.md](../specs/2026-07-23-market-trends-chart-design.md)

## Global Constraints

- 금액 단위는 원(₩) 정수로 통일. 만원 변환은 표시 계층에서만(이 백엔드는 원/평 정수까지만 산출).
- 모든 조회 결과에 조회 기준일(`queried_at`) 동반 저장.
- L1/L0 외 계산은 순수 함수 + 단위테스트 필수. 네트워크는 `http_get` 주입으로 테스트에서 배제.
- LLM 호출 0. 유료 호스팅·OCR·비전 미사용. 스캔(텍스트레이어 없는) PDF는 오류 반환.
- 기존 `src/onjeon/`·테스트를 깨지 않는다. molit.py는 내부 리팩터(동작 보존) + 함수 추가만.
- 테스트 실행: `.venv/bin/python -m pytest`. 파이썬 직접 실행도 `.venv/bin/python`.
- `[확인]` 마커가 붙은 실거래가 오퍼레이션 ID/응답 태그는 실키 검증 전까지 확정 아님(Task 5에서 검증 스텝 포함).

---

## File Structure

- Create `src/onjeon/device.py` — MPS/CPU 디바이스 해석 헬퍼
- Create `src/onjeon/market/__init__.py`
- Create `src/onjeon/market/pyeong.py` — 평당가 순수 함수
- Create `src/onjeon/market/buckets.py` — 주/월 버킷 집계 순수 함수
- Create `src/onjeon/market/period.py` — 기간 문자열 → (범위, 단위)
- Create `src/onjeon/market/building.py` — 건물용도 문자열 → 유형(apt/rh/offi)
- Create `src/onjeon/market/cache.py` — SQLite 월단위 캐시
- Create `src/onjeon/market/trends.py` — 오케스트레이터(fetch→pyeong→cache→series)
- Modify `src/onjeon/data_pipeline/molit.py` — rent 파싱 + 용도별 엔드포인트 + `fetch_deals`
- Create `src/onjeon/register/__init__.py`, `src/onjeon/register/parse.py` — 등기부 텍스트 파서
- Create `api/__init__.py`, `api/main.py` — FastAPI 앱(2개 엔드포인트)
- Modify `app.py` — 비교 탭 비활성화(플래그)
- Tests: `tests/test_device.py`, `tests/test_pyeong.py`, `tests/test_buckets.py`, `tests/test_period.py`, `tests/test_building.py`, `tests/test_market_cache.py`, `tests/test_trends.py`, `tests/test_molit_deals.py`, `tests/test_register_parse.py`, `tests/test_api.py`

---

## Task 1: MPS 디바이스 헬퍼

**Files:**
- Create: `src/onjeon/device.py`
- Test: `tests/test_device.py`

**Interfaces:**
- Produces: `resolve_device() -> str` — torch 사용 경로가 소비. torch 미설치 시 `"cpu"`.

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_device.py`

```python
from onjeon.device import resolve_device


def test_returns_cpu_when_torch_absent(monkeypatch):
    # torch import를 막아 미설치 환경을 모사
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "torch":
            raise ImportError("no torch")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert resolve_device() == "cpu"


def test_returns_mps_when_available(monkeypatch):
    import types
    torch = types.SimpleNamespace(
        backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: True))
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", torch)
    assert resolve_device() == "mps"
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_device.py -v` · Expected: FAIL (`ModuleNotFoundError: onjeon.device`)

- [ ] **Step 3: 구현** — `src/onjeon/device.py`

```python
"""연산 디바이스 해석 — Apple Silicon은 CUDA 대신 MPS 우선.

torch가 없거나 MPS 미가용이면 cpu. fastembed(ONNX)는 이 대상이 아니다.
"""

from __future__ import annotations


def resolve_device() -> str:
    """'mps'(가용 시) 또는 'cpu'. torch 미설치 환경에서도 안전."""
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_device.py -v` · Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/onjeon/device.py tests/test_device.py
git commit -m "feat: MPS/CPU 디바이스 해석 헬퍼"
```

---

## Task 2: 평당가 순수 함수

**Files:**
- Create: `src/onjeon/market/__init__.py` (빈 파일), `src/onjeon/market/pyeong.py`
- Test: `tests/test_pyeong.py`

**Interfaces:**
- Produces: `PYEONG_PER_M2 = 3.3058`; `price_per_pyeong(amount_krw: int, area_m2: float) -> int` — 원/평 정수(반올림). `area_m2 <= 0`이면 `ValueError`.

- [ ] **Step 1: 실패 테스트** — `tests/test_pyeong.py`

```python
import pytest

from onjeon.market.pyeong import price_per_pyeong


def test_known_value():
    # 3.3058 m² = 1평. 1억이 정확히 1평이면 평당 1억.
    assert price_per_pyeong(100_000_000, 3.3058) == 100_000_000


def test_rounds_to_int():
    # 29.75m² ≈ 9.0009평, 1.5억 → 원/평 정수
    v = price_per_pyeong(150_000_000, 29.75)
    assert isinstance(v, int)
    assert v == round(150_000_000 / (29.75 / 3.3058))


def test_zero_area_raises():
    with pytest.raises(ValueError):
        price_per_pyeong(150_000_000, 0)
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_pyeong.py -v` · Expected: FAIL (import 에러)

- [ ] **Step 3: 구현** — `src/onjeon/market/pyeong.py`

```python
"""평당가 계산 — 원(₩) 정수. 만원 변환은 표시 계층 몫."""

from __future__ import annotations

PYEONG_PER_M2 = 3.3058  # 1평 = 3.3058 m²


def price_per_pyeong(amount_krw: int, area_m2: float) -> int:
    """거래금액(원)·전용면적(m²) → 평당가(원/평) 정수. 면적 0 이하면 ValueError."""
    if area_m2 <= 0:
        raise ValueError(f"전용면적이 0 이하: {area_m2!r}")
    pyeong = area_m2 / PYEONG_PER_M2
    return round(amount_krw / pyeong)
```

(`src/onjeon/market/__init__.py`는 빈 파일로 생성.)

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_pyeong.py -v` · Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/onjeon/market/__init__.py src/onjeon/market/pyeong.py tests/test_pyeong.py
git commit -m "feat: 평당가(원/평) 순수 함수"
```

---

## Task 3: 주/월 버킷 집계

**Files:**
- Create: `src/onjeon/market/buckets.py`
- Test: `tests/test_buckets.py`

**Interfaces:**
- Consumes: 레코드 형태 `{"deal_date": "YYYY-MM-DD", "pyeong_krw": int}`.
- Produces:
  - `bucket_key(deal_date: str, granularity: str) -> str` — `"month"`→`"YYYY-MM"`, `"week"`→`"YYYY-MM-Wn"`(n=(일-1)//7+1).
  - `average_by_bucket(records: list[dict], granularity: str) -> dict[str, dict]` — `{bucket: {"pyeong_krw": int(평균 반올림), "n": int}}`, 버킷 키 오름차순 삽입.

- [ ] **Step 1: 실패 테스트** — `tests/test_buckets.py`

```python
from onjeon.market.buckets import average_by_bucket, bucket_key


def test_bucket_key_month():
    assert bucket_key("2026-07-12", "month") == "2026-07"


def test_bucket_key_week_first_and_second():
    assert bucket_key("2026-07-01", "week") == "2026-07-W1"
    assert bucket_key("2026-07-08", "week") == "2026-07-W2"
    assert bucket_key("2026-07-31", "week") == "2026-07-W5"


def test_average_by_month_groups_and_rounds():
    recs = [
        {"deal_date": "2026-06-03", "pyeong_krw": 10_000_000},
        {"deal_date": "2026-06-20", "pyeong_krw": 20_000_000},
        {"deal_date": "2026-07-01", "pyeong_krw": 30_000_000},
    ]
    out = average_by_bucket(recs, "month")
    assert out["2026-06"] == {"pyeong_krw": 15_000_000, "n": 2}
    assert out["2026-07"] == {"pyeong_krw": 30_000_000, "n": 1}
    assert list(out.keys()) == ["2026-06", "2026-07"]  # 정렬


def test_empty_returns_empty():
    assert average_by_bucket([], "month") == {}
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_buckets.py -v` · Expected: FAIL

- [ ] **Step 3: 구현** — `src/onjeon/market/buckets.py`

```python
"""거래 레코드를 주/월 버킷으로 묶어 평당가 평균을 낸다(순수 함수)."""

from __future__ import annotations

import statistics


def bucket_key(deal_date: str, granularity: str) -> str:
    """'YYYY-MM-DD' → 'YYYY-MM'(month) 또는 'YYYY-MM-Wn'(week)."""
    year, month, day = deal_date.split("-")
    if granularity == "month":
        return f"{year}-{month}"
    if granularity == "week":
        week = (int(day) - 1) // 7 + 1
        return f"{year}-{month}-W{week}"
    raise ValueError(f"알 수 없는 granularity: {granularity!r}")


def average_by_bucket(records: list[dict], granularity: str) -> dict[str, dict]:
    """버킷별 평당가 평균(반올림)·건수. 버킷 키 오름차순."""
    groups: dict[str, list[int]] = {}
    for rec in records:
        key = bucket_key(rec["deal_date"], granularity)
        groups.setdefault(key, []).append(rec["pyeong_krw"])
    return {
        key: {"pyeong_krw": round(statistics.mean(vals)), "n": len(vals)}
        for key, vals in sorted(groups.items())
    }
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_buckets.py -v` · Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/onjeon/market/buckets.py tests/test_buckets.py
git commit -m "feat: 주/월 버킷 평당가 집계 순수 함수"
```

---

## Task 4: 기간 문자열 → 범위·단위

**Files:**
- Create: `src/onjeon/market/period.py`
- Test: `tests/test_period.py`

**Interfaces:**
- Consumes: `onjeon.data_pipeline.regions.recent_deal_ym`, `month_range`(기존).
- Produces:
  - `granularity_for(period: str) -> str` — `"1m"|"6m"`→`"week"`, `"1y"|"3y"|"5y"`→`"month"`.
  - `period_months(period: str, today: str | None = None) -> list[str]` — 종료월=직전 완결월, 시작월=종료월에서 N개월 전. 반환은 `month_range` 결과(YYYYMM 리스트).

- [ ] **Step 1: 실패 테스트** — `tests/test_period.py`

```python
import pytest

from onjeon.market.period import granularity_for, period_months


def test_granularity_short_is_week():
    assert granularity_for("1m") == "week"
    assert granularity_for("6m") == "week"


def test_granularity_long_is_month():
    assert granularity_for("1y") == "month"
    assert granularity_for("5y") == "month"


def test_period_months_1m_is_two_months():
    # today 2026-07-15 → 직전 완결월 202606, 1개월 전 202605
    assert period_months("1m", today="2026-07-15") == ["202605", "202606"]


def test_period_months_1y_spans_13():
    months = period_months("1y", today="2026-07-15")
    assert months[0] == "202506" and months[-1] == "202606"
    assert len(months) == 13


def test_unknown_period_raises():
    with pytest.raises(ValueError):
        period_months("2w", today="2026-07-15")
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_period.py -v` · Expected: FAIL

- [ ] **Step 3: 구현** — `src/onjeon/market/period.py`

```python
"""기간 퀵버튼(1m/6m/1y/3y/5y) → 계약월 범위·집계 단위."""

from __future__ import annotations

from onjeon.data_pipeline.regions import month_range, recent_deal_ym

_MONTHS_BACK = {"1m": 1, "6m": 6, "1y": 12, "3y": 36, "5y": 60}
_WEEK_PERIODS = {"1m", "6m"}


def granularity_for(period: str) -> str:
    """짧은 기간(≤6m)은 주 단위, 그 외는 월 단위."""
    if period not in _MONTHS_BACK:
        raise ValueError(f"지원하지 않는 기간: {period!r}")
    return "week" if period in _WEEK_PERIODS else "month"


def period_months(period: str, today: str | None = None) -> list[str]:
    """직전 완결월을 끝으로 N개월 전까지의 YYYYMM 리스트."""
    if period not in _MONTHS_BACK:
        raise ValueError(f"지원하지 않는 기간: {period!r}")
    end = recent_deal_ym(today)
    ey, em = int(end[:4]), int(end[4:])
    back = _MONTHS_BACK[period]
    total = ey * 12 + (em - 1) - back
    sy, sm = divmod(total, 12)
    start = f"{sy}{sm + 1:02d}"
    return month_range(start, end)
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_period.py -v` · Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/onjeon/market/period.py tests/test_period.py
git commit -m "feat: 기간 퀵버튼 → 계약월 범위·집계 단위"
```

---

## Task 5: 용도별 실거래가 fetch (molit.py 확장)

**Files:**
- Modify: `src/onjeon/data_pipeline/molit.py`
- Test: `tests/test_molit_deals.py`

**Interfaces:**
- Consumes: 기존 `parse_trades`, `_is_retryable`, retry 로직.
- Produces:
  - `parse_rents(xml_text: str) -> list[dict]` — `{"deposit_krw","monthly_rent_krw","area_m2","deal_date","dong"}`.
  - `BUILDING_OPS: dict[str, dict[str, str]]` (apt/rh/offi × trade/rent 오퍼레이션 ID), `deal_endpoint(building_type, kind) -> str`.
  - `fetch_deals(lawd_cd, ym, building_type, deal_kind, *, service_key=None, http_get=requests.get, retry_wait=None) -> list[dict]` — 정규화 `{"amount_krw","area_m2","deal_date"}`. `deal_kind="trade"`는 매매금액, `deal_kind="jeonse"`는 rent에서 월세금 0만 필터해 보증금액.
- 내부 리팩터: 요청/재시도 부분을 `_fetch_xml(...) -> str`로 추출(기존 `fetch_trades` 동작·테스트 보존).

- [ ] **Step 1: 실패 테스트** — `tests/test_molit_deals.py`

```python
from tenacity import wait_none

from onjeon.data_pipeline.molit import deal_endpoint, fetch_deals, parse_rents

RENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response><body><items>
  <item><deposit>30,000</deposit><monthlyRent>0</monthlyRent><excluUseAr>29.75</excluUseAr>
    <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>3</dealDay><umdNm>봉천동</umdNm></item>
  <item><deposit>5,000</deposit><monthlyRent>80</monthlyRent><excluUseAr>30</excluUseAr>
    <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>5</dealDay><umdNm>봉천동</umdNm></item>
</items></body></response>"""

TRADE_XML = """<?xml version="1.0"?><response><body><items>
  <item><dealAmount>15,000</dealAmount><excluUseAr>29.75</excluUseAr><floor>3</floor>
    <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>12</dealDay><umdNm>봉천동</umdNm></item>
</items></body></response>"""


def _fake(xml):
    class _Resp:
        text = xml

        def raise_for_status(self):
            pass

    return lambda url, params=None, timeout=None: _Resp()


def test_parse_rents_converts_deposit_and_flags_monthly():
    rents = parse_rents(RENT_XML)
    assert rents[0]["deposit_krw"] == 300_000_000
    assert rents[0]["monthly_rent_krw"] == 0
    assert rents[1]["monthly_rent_krw"] == 800_000


def test_deal_endpoint_shapes_url():
    url = deal_endpoint("apt", "trade")
    assert url.startswith("https://apis.data.go.kr/1613000/")
    assert url.endswith(deal_endpoint("apt", "trade").rsplit("/", 1)[1])


def test_fetch_deals_trade_normalizes():
    deals = fetch_deals("11620", "202606", "rh", "trade",
                        service_key="k", http_get=_fake(TRADE_XML), retry_wait=wait_none())
    assert deals == [{"amount_krw": 150_000_000, "area_m2": 29.75, "deal_date": "2026-06-12"}]


def test_fetch_deals_jeonse_filters_monthly_zero():
    deals = fetch_deals("11620", "202606", "rh", "jeonse",
                        service_key="k", http_get=_fake(RENT_XML), retry_wait=wait_none())
    # 월세금 0(전세) 1건만, 금액은 보증금
    assert deals == [{"amount_krw": 300_000_000, "area_m2": 29.75, "deal_date": "2026-06-03"}]
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_molit_deals.py -v` · Expected: FAIL

- [ ] **Step 3: 구현** — `src/onjeon/data_pipeline/molit.py`에 추가/리팩터

```python
# --- 파일 상단 _TAGS 아래에 추가 ---
_RENT_TAGS = {
    "deposit": ("deposit", "보증금액", "보증금"),
    "monthly": ("monthlyRent", "월세금액", "월세"),
    "area": ("excluUseAr", "전용면적"),
    "year": ("dealYear", "년"),
    "month": ("dealMonth", "월"),
    "day": ("dealDay", "일"),
    "dong": ("umdNm", "법정동"),
}

ENDPOINT_BASE = "https://apis.data.go.kr/1613000"
# [확인] apt/offi/rent 오퍼레이션 ID — 실키로 검증 후 확정. rh trade는 기존 검증됨.
BUILDING_OPS = {
    "apt": {"trade": "RTMSDataSvcAptTradeDev", "rent": "RTMSDataSvcAptRent"},
    "rh": {"trade": "RTMSDataSvcRHTrade", "rent": "RTMSDataSvcRHRent"},
    "offi": {"trade": "RTMSDataSvcOffiTrade", "rent": "RTMSDataSvcOffiRent"},
}


def deal_endpoint(building_type: str, kind: str) -> str:
    """(용도, trade|rent) → 실거래가 오퍼레이션 URL."""
    op = BUILDING_OPS[building_type][kind]
    return f"{ENDPOINT_BASE}/{op}/get{op}"


def _find_rent(item, key: str) -> str:
    for tag in _RENT_TAGS[key]:
        node = item.find(tag)
        if node is not None and node.text:
            return node.text.strip()
    return ""


def parse_rents(xml_text: str) -> list[dict]:
    """전월세 응답 XML → 목록. 보증금/월세 '30,000'(만원) → 원 정수."""
    root = ET.fromstring(xml_text)
    rents = []
    for item in root.iter("item"):
        year, month, day = _find_rent(item, "year"), _find_rent(item, "month"), _find_rent(item, "day")
        rents.append({
            "deposit_krw": int(_find_rent(item, "deposit").replace(",", "") or 0) * 10_000,
            "monthly_rent_krw": int(_find_rent(item, "monthly").replace(",", "") or 0) * 10_000,
            "area_m2": float(_find_rent(item, "area") or 0),
            "deal_date": f"{year}-{int(month):02d}-{int(day):02d}",
            "dong": _find_rent(item, "dong"),
        })
    return rents
```

`_fetch_xml` 추출 — 기존 `fetch_trades` 내부 `_request`/`retryer` 블록을 함수로 빼고 `fetch_trades`는 이를 호출:

```python
def _fetch_xml(lawd_cd, deal_ym, endpoint, *, service_key, http_get, retry_wait) -> str:
    """실거래가 원본 XML 문자열 반환(재시도·키 마스킹 포함)."""
    key = service_key or os.environ.get("MOLIT_API_KEY")
    if not key:
        raise ValueError("MOLIT_API_KEY가 없다 — .env에 공공데이터포털 서비스키를 설정하라")

    def _request():
        try:
            response = http_get(endpoint, params={
                "serviceKey": key, "LAWD_CD": lawd_cd,
                "DEAL_YMD": deal_ym, "numOfRows": "1000",
            }, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            sanitized = str(exc).replace(key, "***")
            raise type(exc)(sanitized, response=getattr(exc, "response", None)) from None
        return response

    retryer = Retrying(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=retry_wait if retry_wait is not None else wait_exponential(multiplier=0.5),
        before_sleep=_warn_before_retry, reraise=True,
    )
    return retryer(_request).text


def fetch_deals(lawd_cd, ym, building_type, deal_kind, *,
                service_key=None, http_get=requests.get, retry_wait=None) -> list[dict]:
    """용도별 실거래가 → 정규화 {amount_krw, area_m2, deal_date}.
    deal_kind='trade' 매매금액 / 'jeonse' 전월세 중 월세금 0(전세)만·보증금액.
    """
    kind = "trade" if deal_kind == "trade" else "rent"
    xml = _fetch_xml(lawd_cd, ym, deal_endpoint(building_type, kind),
                     service_key=service_key, http_get=http_get, retry_wait=retry_wait)
    if deal_kind == "trade":
        return [{"amount_krw": t["price_krw"], "area_m2": t["area_m2"], "deal_date": t["deal_date"]}
                for t in parse_trades(xml)]
    return [{"amount_krw": r["deposit_krw"], "area_m2": r["area_m2"], "deal_date": r["deal_date"]}
            for r in parse_rents(xml) if r["monthly_rent_krw"] == 0]
```

> `fetch_trades`는 `_fetch_xml`를 쓰도록 본문만 교체(반환 구조·시그니처 불변). 기존 `tests/test_data_pipeline.py`가 그대로 통과해야 한다.

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_molit_deals.py tests/test_data_pipeline.py -v` · Expected: PASS (신규 + 기존 회귀 없음)

- [ ] **Step 5: `[확인]` 실 API 검증(네트워크, 선택적이지만 착수 전 권장)**

Run: `.venv/bin/python -c "from onjeon.data_pipeline.molit import fetch_deals; print(len(fetch_deals('11110','202605','apt','trade')))"`
Expected: 정수 출력(>0). 401/404/빈결과면 `BUILDING_OPS`의 apt/offi 오퍼레이션 ID·태그를 data.go.kr 카탈로그로 교정하고 재실행. 검증된 값으로 `[확인]` 주석 제거.

- [ ] **Step 6: 커밋**

```bash
git add src/onjeon/data_pipeline/molit.py tests/test_molit_deals.py
git commit -m "feat: 용도별 실거래가 fetch_deals + 전월세 파싱(molit 확장)"
```

---

## Task 6: SQLite 월단위 캐시

**Files:**
- Create: `src/onjeon/market/cache.py`
- Test: `tests/test_market_cache.py`

**Interfaces:**
- Produces:
  - `open_cache(path) -> sqlite3.Connection` — 테이블 없으면 생성.
  - `is_month_fetched(conn, region, btype, kind, ym) -> bool`
  - `save_month(conn, region, btype, kind, ym, deals, queried_at) -> None` — `deals`=`[{"deal_date","pyeong_krw"}]`. 0건도 fetched 마킹.
  - `load_deals(conn, region, btype, kind, months: list[str]) -> list[dict]` — `[{"deal_date","pyeong_krw"}]`.

- [ ] **Step 1: 실패 테스트** — `tests/test_market_cache.py`

```python
from onjeon.market.cache import is_month_fetched, load_deals, open_cache, save_month


def test_unfetched_month_is_false(tmp_path):
    conn = open_cache(tmp_path / "c.db")
    assert is_month_fetched(conn, "11620", "rh", "trade", "202606") is False


def test_save_marks_fetched_and_loads_deals(tmp_path):
    conn = open_cache(tmp_path / "c.db")
    deals = [{"deal_date": "2026-06-03", "pyeong_krw": 10_000_000},
             {"deal_date": "2026-06-20", "pyeong_krw": 20_000_000}]
    save_month(conn, "11620", "rh", "trade", "202606", deals, "2026-07-23")
    assert is_month_fetched(conn, "11620", "rh", "trade", "202606") is True
    assert load_deals(conn, "11620", "rh", "trade", ["202606"]) == deals


def test_empty_month_still_marked_fetched(tmp_path):
    conn = open_cache(tmp_path / "c.db")
    save_month(conn, "11620", "rh", "trade", "202604", [], "2026-07-23")
    assert is_month_fetched(conn, "11620", "rh", "trade", "202604") is True
    assert load_deals(conn, "11620", "rh", "trade", ["202604"]) == []
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_market_cache.py -v` · Expected: FAIL

- [ ] **Step 3: 구현** — `src/onjeon/market/cache.py`

```python
"""실거래가 월단위 캐시(SQLite). 원(₩) 정수·조회기준일 저장(CLAUDE.md)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fetched_months (
  region_code TEXT, building_type TEXT, deal_kind TEXT, ym TEXT,
  n INTEGER NOT NULL, queried_at TEXT NOT NULL,
  PRIMARY KEY (region_code, building_type, deal_kind, ym)
);
CREATE TABLE IF NOT EXISTS deal_cache (
  region_code TEXT, building_type TEXT, deal_kind TEXT, ym TEXT,
  deal_date TEXT NOT NULL, pyeong_krw INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deal_lookup
  ON deal_cache (region_code, building_type, deal_kind, ym);
"""


def open_cache(path) -> sqlite3.Connection:
    """캐시 DB 연결(+스키마 보장). path 디렉터리는 미리 존재해야 함."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def is_month_fetched(conn, region, btype, kind, ym) -> bool:
    row = conn.execute(
        "SELECT 1 FROM fetched_months WHERE region_code=? AND building_type=? AND deal_kind=? AND ym=?",
        (region, btype, kind, ym),
    ).fetchone()
    return row is not None


def save_month(conn, region, btype, kind, ym, deals, queried_at) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO fetched_months VALUES (?,?,?,?,?,?)",
        (region, btype, kind, ym, len(deals), queried_at),
    )
    conn.execute(
        "DELETE FROM deal_cache WHERE region_code=? AND building_type=? AND deal_kind=? AND ym=?",
        (region, btype, kind, ym),
    )
    conn.executemany(
        "INSERT INTO deal_cache VALUES (?,?,?,?,?,?)",
        [(region, btype, kind, ym, d["deal_date"], d["pyeong_krw"]) for d in deals],
    )
    conn.commit()


def load_deals(conn, region, btype, kind, months) -> list[dict]:
    if not months:
        return []
    qs = ",".join("?" * len(months))
    rows = conn.execute(
        f"SELECT deal_date, pyeong_krw FROM deal_cache "
        f"WHERE region_code=? AND building_type=? AND deal_kind=? AND ym IN ({qs}) "
        f"ORDER BY deal_date",
        (region, btype, kind, *months),
    ).fetchall()
    return [{"deal_date": d, "pyeong_krw": p} for d, p in rows]
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_market_cache.py -v` · Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/onjeon/market/cache.py tests/test_market_cache.py
git commit -m "feat: 실거래가 월단위 SQLite 캐시"
```

---

## Task 7: trends 오케스트레이터 (cache-through)

**Files:**
- Create: `src/onjeon/market/trends.py`
- Test: `tests/test_trends.py`

**Interfaces:**
- Consumes: `fetch_deals`(Task5), `price_per_pyeong`(Task2), `average_by_bucket`(Task3), `period_months`/`granularity_for`(Task4), cache(Task6), `resolve_lawd_cd`(기존).
- Produces: `market_trends(region, building_type, period, *, cache, today=None, queried_at, service_key=None, http_get=None, retry_wait=None) -> {"dates": list[str], "mae_price": list[int|None], "jun_price": list[int|None]}`. `http_get=None`이면 `fetch_deals`의 기본(`requests.get`)을 쓴다(테스트만 주입). 미지원 지역이면 `ValueError`. 값 단위 = 평당 만원 정수(원/평 → //10_000). 결측 버킷은 `None`.

- [ ] **Step 1: 실패 테스트** — `tests/test_trends.py`

```python
from tenacity import wait_none

from onjeon.market.cache import open_cache
from onjeon.market.pyeong import price_per_pyeong
from onjeon.market.trends import market_trends


class _StubHTTP:
    """(deal_kind별) 월→XML 매핑. 호출 횟수 기록으로 캐시 검증."""

    def __init__(self, trade_xml, rent_xml):
        self.trade_xml, self.rent_xml = trade_xml, rent_xml
        self.calls = 0

    def __call__(self, url, params=None, timeout=None):
        self.calls += 1
        xml = self.rent_xml if "Rent" in url else self.trade_xml

        class _Resp:
            text = xml

            def raise_for_status(self):
                pass

        return _Resp()


TRADE = """<response><body><items>
  <item><dealAmount>15,000</dealAmount><excluUseAr>29.75</excluUseAr><floor>3</floor>
    <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>12</dealDay><umdNm>봉천동</umdNm></item>
</items></body></response>"""
RENT = """<response><body><items>
  <item><deposit>30,000</deposit><monthlyRent>0</monthlyRent><excluUseAr>29.75</excluUseAr>
    <dealYear>2026</dealYear><dealMonth>6</dealMonth><dealDay>3</dealDay><umdNm>봉천동</umdNm></item>
</items></body></response>"""


def test_returns_aligned_series(tmp_path):
    conn = open_cache(tmp_path / "c.db")
    http = _StubHTTP(TRADE, RENT)
    out = market_trends("관악구", "rh", "1m", cache=conn, today="2026-07-15",
                        queried_at="2026-07-23", service_key="k",
                        http_get=http, retry_wait=wait_none())
    assert "dates" in out and len(out["dates"]) == len(out["mae_price"]) == len(out["jun_price"])
    # 값 단위 = 평당 만원. 기대값은 단위테스트된 price_per_pyeong으로 결정론적 계산.
    expected_mae = price_per_pyeong(150_000_000, 29.75) // 10_000   # 매매 1.5억
    expected_jun = price_per_pyeong(300_000_000, 29.75) // 10_000   # 전세 보증금 3억
    non_null_mae = [v for v in out["mae_price"] if v is not None]
    non_null_jun = [v for v in out["jun_price"] if v is not None]
    assert non_null_mae and non_null_mae[0] == expected_mae
    assert non_null_jun and non_null_jun[0] == expected_jun


def test_second_call_hits_cache(tmp_path):
    conn = open_cache(tmp_path / "c.db")
    http = _StubHTTP(TRADE, RENT)
    kw = dict(cache=conn, today="2026-07-15", queried_at="2026-07-23",
              service_key="k", http_get=http, retry_wait=wait_none())
    market_trends("관악구", "rh", "1m", **kw)
    first = http.calls
    market_trends("관악구", "rh", "1m", **kw)
    assert http.calls == first  # 두 번째는 네트워크 0


def test_unknown_region_raises(tmp_path):
    import pytest
    conn = open_cache(tmp_path / "c.db")
    with pytest.raises(ValueError):
        market_trends("제주시", "apt", "1m", cache=conn, today="2026-07-15",
                      queried_at="2026-07-23", service_key="k")
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_trends.py -v` · Expected: FAIL

- [ ] **Step 3: 구현** — `src/onjeon/market/trends.py`

```python
"""시세 추이 오케스트레이터 — 캐시 우선, 없으면 fetch→평당가→저장→집계."""

from __future__ import annotations

from onjeon.data_pipeline.molit import fetch_deals
from onjeon.data_pipeline.regions import resolve_lawd_cd
from onjeon.market import cache as cache_mod
from onjeon.market.buckets import average_by_bucket
from onjeon.market.period import granularity_for, period_months
from onjeon.market.pyeong import price_per_pyeong

_KINDS = {"mae_price": "trade", "jun_price": "jeonse"}


def _ensure_cached(conn, region, btype, kind, months, queried_at, **fetch_kw):
    for ym in months:
        if cache_mod.is_month_fetched(conn, region, btype, kind, ym):
            continue
        raw = fetch_deals(region, ym, btype, kind, **fetch_kw)
        deals = [{"deal_date": d["deal_date"],
                  "pyeong_krw": price_per_pyeong(d["amount_krw"], d["area_m2"])}
                 for d in raw if d["area_m2"] > 0]
        cache_mod.save_month(conn, region, btype, kind, ym, deals, queried_at)


def market_trends(region, building_type, period, *, cache, today=None, queried_at,
                  service_key=None, http_get=None, retry_wait=None) -> dict:
    """지역·용도·기간 → {dates, mae_price, jun_price}(평당 만원, 결측 None)."""
    region_code = resolve_lawd_cd(region)
    if region_code is None:
        raise ValueError(f"실거래가 자동 조회 미지원 지역: {region!r}")

    months = period_months(period, today)
    gran = granularity_for(period)
    fetch_kw = {"service_key": service_key, "retry_wait": retry_wait}
    if http_get is not None:
        fetch_kw["http_get"] = http_get

    series = {}
    all_buckets: set[str] = set()
    for out_key, kind in _KINDS.items():
        _ensure_cached(cache, region_code, building_type, kind, months, queried_at, **fetch_kw)
        deals = cache_mod.load_deals(cache, region_code, building_type, kind, months)
        by_bucket = average_by_bucket(deals, gran)
        series[out_key] = {k: v["pyeong_krw"] // 10_000 for k, v in by_bucket.items()}
        all_buckets |= set(by_bucket)

    dates = sorted(all_buckets)
    return {
        "dates": dates,
        "mae_price": [series["mae_price"].get(d) for d in dates],
        "jun_price": [series["jun_price"].get(d) for d in dates],
    }
```

> `fetch_deals`의 첫 인자는 `lawd_cd`다. 여기서는 `region_code`를 넘긴다(지역명이 아니라 코드).

- [ ] **Step 4: 통과 확인 + 기대값 확정** — Run: `.venv/bin/python -m pytest tests/test_trends.py -v` · 첫 실행에서 `test_returns_aligned_series`의 자리표시 단언을 실제 출력 정수로 교체 후 재실행 → PASS

- [ ] **Step 5: 커밋**

```bash
git add src/onjeon/market/trends.py tests/test_trends.py
git commit -m "feat: 시세 추이 오케스트레이터(캐시 우선 집계)"
```

---

## Task 8: 건물용도 → 유형 매핑

**Files:**
- Create: `src/onjeon/market/building.py`
- Test: `tests/test_building.py`

**Interfaces:**
- Produces: `building_type_for_use(use: str) -> str` — 아파트→`"apt"`, 연립/다세대→`"rh"`, 오피스텔→`"offi"`. 미분류는 `ValueError`.

- [ ] **Step 1: 실패 테스트** — `tests/test_building.py`

```python
import pytest

from onjeon.market.building import building_type_for_use


@pytest.mark.parametrize("use,expected", [
    ("아파트", "apt"),
    ("연립주택", "rh"),
    ("다세대주택", "rh"),
    ("오피스텔", "offi"),
    ("서울시 ... 오피스텔(업무시설)", "offi"),
])
def test_maps_use(use, expected):
    assert building_type_for_use(use) == expected


def test_unknown_use_raises():
    with pytest.raises(ValueError):
        building_type_for_use("근린생활시설")
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_building.py -v` · Expected: FAIL

- [ ] **Step 3: 구현** — `src/onjeon/market/building.py`

```python
"""등기부 건물용도 문자열 → 실거래가 유형(apt/rh/offi)."""

from __future__ import annotations

# 순서 중요: '오피스텔'을 먼저 판정(아파트 오인 방지)
_RULES = [
    ("오피스텔", "offi"),
    ("아파트", "apt"),
    ("연립", "rh"),
    ("다세대", "rh"),
]


def building_type_for_use(use: str) -> str:
    """부분 문자열 매칭으로 유형 분류. 미분류는 ValueError."""
    for needle, btype in _RULES:
        if needle in use:
            return btype
    raise ValueError(f"실거래가 유형 미분류 건물용도: {use!r}")
```

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_building.py -v` · Expected: PASS

- [ ] **Step 5: 커밋**

```bash
git add src/onjeon/market/building.py tests/test_building.py
git commit -m "feat: 건물용도 → 실거래가 유형 매핑"
```

---

## Task 9: 등기부 텍스트 파서

**Files:**
- Create: `src/onjeon/register/__init__.py`(빈), `src/onjeon/register/parse.py`
- Test: `tests/test_register_parse.py`
- Modify: `pyproject.toml`(의존성 `pdfplumber` 추가), `requirements.txt`

**Interfaces:**
- Produces:
  - `class NoTextLayer(ValueError)` — 텍스트 레이어 없는(스캔) PDF.
  - `extract_fields(text: str) -> dict` — 순수 함수. `{"sido","sigungu","jibun","road_addr","exclusive_area_m2","building_use"}`. 텍스트에서 못 찾은 값은 `None`(면적은 필수, 없으면 `ValueError`).
  - `parse_register_pdf(path) -> dict` — pdfplumber로 텍스트 추출 후 `extract_fields`. 텍스트가 비면 `NoTextLayer`.
- **테스트는 `extract_fields`(순수)만 대상**(PDF 실물 불요). `parse_register_pdf`는 얇은 래퍼.

- [ ] **Step 1: 의존성 추가** — `pyproject.toml`의 해당 optional/기본 deps에 `pdfplumber>=0.11` 추가, `requirements.txt`에도 `pdfplumber>=0.11` 한 줄 추가. Run: `.venv/bin/python -m pip install "pdfplumber>=0.11"`

- [ ] **Step 2: 실패 테스트** — `tests/test_register_parse.py`

```python
import pytest

from onjeon.register.parse import NoTextLayer, extract_fields, parse_register_pdf

SAMPLE = """[집합건물] 서울특별시 관악구 봉천동 100-1 제3층 제302호
1동의 건물의 표시
서울특별시 관악구 봉천동 100-1
[도로명주소] 서울특별시 관악구 관악로 12
전유부분의 건물의 표시
건물의 번호 3-302
구조 철근콘크리트조 용도 아파트 면적 59.85㎡
"""


def test_extracts_core_fields():
    f = extract_fields(SAMPLE)
    assert f["sido"] == "서울특별시"
    assert f["sigungu"] == "관악구"
    assert f["building_use"] == "아파트"
    assert f["exclusive_area_m2"] == 59.85
    assert f["road_addr"] == "서울특별시 관악구 관악로 12"


def test_missing_area_raises():
    with pytest.raises(ValueError):
        extract_fields("서울특별시 관악구 봉천동 100-1 용도 아파트")


def test_scanned_pdf_signals_no_text_layer(tmp_path, monkeypatch):
    import onjeon.register.parse as mod

    class _Page:
        def extract_text(self):
            return None

    class _PDF:
        pages = [_Page()]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mod.pdfplumber, "open", lambda p: _PDF())
    with pytest.raises(NoTextLayer):
        parse_register_pdf("scan.pdf")
```

- [ ] **Step 3: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_register_parse.py -v` · Expected: FAIL

- [ ] **Step 4: 구현** — `src/onjeon/register/parse.py`

```python
"""등기부등본 PDF → 핵심 필드(주소·전용면적·용도) 텍스트 파싱.

비전 LLM 아님. 텍스트 레이어가 없는 스캔본은 NoTextLayer로 신호(유료 OCR 미사용).
"""

from __future__ import annotations

import re

import pdfplumber

_AREA_RE = re.compile(r"면적\s*([\d,]+\.\d+)\s*㎡")
_USE_RE = re.compile(r"용도\s*([가-힣A-Za-z]+)")
_SIDO_RE = re.compile(r"(서울특별시|부산광역시|대구광역시|인천광역시|광주광역시|대전광역시|"
                      r"울산광역시|세종특별자치시|경기도|강원(?:특별자치)?도|충청북도|충청남도|"
                      r"전라북도|전북특별자치도|전라남도|경상북도|경상남도|제주특별자치도)")
_SIGUNGU_RE = re.compile(r"[가-힣]+(?:시|군|구)")  # findall — sido와 겹치면 제외
_ROAD_RE = re.compile(r"\[도로명주소\]\s*(.+)")


class NoTextLayer(ValueError):
    """텍스트 레이어가 없는(스캔) PDF."""


def extract_fields(text: str) -> dict:
    """등기부 텍스트 → 필드. 전용면적은 필수(없으면 ValueError)."""
    area_m = _AREA_RE.search(text)
    if not area_m:
        raise ValueError("전용면적을 찾지 못했다 — 등기부 형식 확인 필요")
    sido = _SIDO_RE.search(text)
    sido_val = sido.group(1) if sido else None
    # 시군구: '시/군/구' 토큰 중 sido(예: 서울특별시)와 겹치지 않는 첫 번째
    sigungu_val = next((t for t in _SIGUNGU_RE.findall(text) if t != sido_val), None)
    use = _USE_RE.search(text)
    road = _ROAD_RE.search(text)
    return {
        "sido": sido_val,
        "sigungu": sigungu_val,
        "jibun": None,  # [확인] 지번 상세 파싱은 실물 등기부로 규칙 확정
        "road_addr": road.group(1).strip() if road else None,
        "exclusive_area_m2": float(area_m.group(1).replace(",", "")),
        "building_use": use.group(1) if use else None,
    }


def parse_register_pdf(path) -> dict:
    """PDF 텍스트 추출 후 필드 파싱. 텍스트 없으면 NoTextLayer."""
    with pdfplumber.open(path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    if not text.strip():
        raise NoTextLayer("텍스트 레이어 없음(스캔 PDF로 추정) — 수동 입력 필요")
    return extract_fields(text)
```

- [ ] **Step 5: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_register_parse.py -v` · Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add src/onjeon/register/ tests/test_register_parse.py pyproject.toml requirements.txt
git commit -m "feat: 등기부 텍스트 파서(스캔 PDF는 NoTextLayer)"
```

---

## Task 10: FastAPI 엔드포인트

**Files:**
- Create: `api/__init__.py`(빈), `api/main.py`
- Test: `tests/test_api.py`
- Modify: `pyproject.toml`(deps `fastapi`, `python-multipart`, `httpx`), `requirements.txt`

**Interfaces:**
- Consumes: `market_trends`(Task7), `parse_register_pdf`/`extract_fields`(Task9), `building_type_for_use`(Task8), `resolve_lawd_cd`.
- Produces:
  - `app` (FastAPI). `get_cache()` 의존성 — `data/cache.db` 연결(테스트에서 override).
  - `GET /api/market-trends?region=&buildingType=&period=` → `{"dates":[...],"mae_price":[...],"jun_price":[...]}`. 미지원 지역/파라미터 → 400.
  - `POST /api/register/parse` (multipart file) → `{"sigungu","region_code","building_type","exclusive_area_m2","road_addr",...}`. 텍스트레이어 없으면 422.

- [ ] **Step 1: 의존성 추가** — `pyproject.toml`/`requirements.txt`에 `fastapi>=0.115`, `python-multipart>=0.0.9`, `httpx>=0.27`(TestClient용) 추가. Run: `.venv/bin/python -m pip install "fastapi>=0.115" "python-multipart>=0.0.9" "httpx>=0.27"`

- [ ] **Step 2: 실패 테스트** — `tests/test_api.py`

```python
from fastapi.testclient import TestClient

from onjeon.market.cache import open_cache
from api.main import app, get_cache


def _client(tmp_path):
    conn = open_cache(tmp_path / "c.db")
    app.dependency_overrides[get_cache] = lambda: conn
    return TestClient(app)


def test_market_trends_bad_region_returns_400(tmp_path):
    client = _client(tmp_path)
    r = client.get("/api/market-trends", params={"region": "제주시", "buildingType": "apt", "period": "1m"})
    assert r.status_code == 400


def test_register_parse_extracts(tmp_path, monkeypatch):
    client = _client(tmp_path)
    import api.main as mod
    monkeypatch.setattr(mod, "parse_register_pdf", lambda path: {
        "sido": "서울특별시", "sigungu": "관악구", "jibun": None,
        "road_addr": "서울특별시 관악구 관악로 12",
        "exclusive_area_m2": 59.85, "building_use": "아파트",
    })
    r = client.post("/api/register/parse", files={"file": ("r.pdf", b"%PDF-1.4", "application/pdf")})
    assert r.status_code == 200
    body = r.json()
    assert body["region_code"] == "11620"
    assert body["building_type"] == "apt"
```

- [ ] **Step 3: 실패 확인** — Run: `.venv/bin/python -m pytest tests/test_api.py -v` · Expected: FAIL

- [ ] **Step 4: 구현** — `api/main.py`

```python
"""온전 REST 계층 — 시세 추이 + 등기부 파싱. onjeon 모듈을 감싸기만 한다."""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile

from onjeon.data_pipeline.regions import resolve_lawd_cd
from onjeon.market.building import building_type_for_use
from onjeon.market.cache import open_cache
from onjeon.market.trends import market_trends
from onjeon.register.parse import NoTextLayer, parse_register_pdf

app = FastAPI(title="온전 API")
_CACHE_PATH = Path("data/cache.db")


def get_cache():
    """요청 스코프 캐시 연결(테스트는 dependency_overrides로 교체)."""
    conn = open_cache(_CACHE_PATH)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/api/market-trends")
def get_market_trends(region: str, buildingType: str, period: str, cache=Depends(get_cache)):
    try:
        return market_trends(region, buildingType, period, cache=cache,
                             queried_at=date.today().isoformat())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/register/parse")
async def post_register_parse(file: UploadFile, cache=Depends(get_cache)):
    data = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            fields = parse_register_pdf(tmp.name)
        except NoTextLayer as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    region_code = resolve_lawd_cd(fields.get("sigungu") or "")
    building_type = None
    if fields.get("building_use"):
        try:
            building_type = building_type_for_use(fields["building_use"])
        except ValueError:
            building_type = None
    return {**fields, "region_code": region_code, "building_type": building_type}
```

- [ ] **Step 5: 통과 확인** — Run: `.venv/bin/python -m pytest tests/test_api.py -v` · Expected: PASS

- [ ] **Step 6: 커밋**

```bash
git add api/ tests/test_api.py pyproject.toml requirements.txt
git commit -m "feat: FastAPI 시세추이·등기부파싱 엔드포인트"
```

---

## Task 11: Streamlit 비교 탭 비활성화(코드 보존)

**Files:**
- Modify: `app.py`
- Test: 수동(앱 기동 확인)

**Interfaces:** 없음(UI 플래그).

- [ ] **Step 1: 비교 렌더 진입부 탐색** — Run: `grep -n "run_comparison\|비교\|3안" app.py` · 비교 UI를 그리는 블록의 시작 라인 확인.

- [ ] **Step 2: 플래그로 감싸기** — `app.py` 상단에 `SHOW_COMPARISON = False` 추가하고, 비교 UI 렌더 블록을 `if SHOW_COMPARISON:`로 감싼다(내부 코드·`run_comparison` import는 삭제하지 않고 보존). 비활성 시 대체 안내(예: `st.info("비교 기능은 현재 비활성화되어 있습니다.")`)를 표시.

- [ ] **Step 3: 회귀 없음 확인** — Run: `.venv/bin/python -m pytest -q` · Expected: 전체 PASS(기존 + 신규). 비교 로직 테스트는 그대로 통과해야 함(코드 보존).

- [ ] **Step 4: 기동 확인** — Run: `.venv/bin/streamlit run app.py --server.headless true` 로 부팅 에러 없음 확인 후 종료(또는 `verify` 스킬 레시피 사용).

- [ ] **Step 5: 커밋**

```bash
git add app.py
git commit -m "chore: Streamlit 비교 탭 비활성화(코드·테스트 보존)"
```

---

## 전체 검증

- [ ] Run: `.venv/bin/python -m pytest -q` — 전체 그린(기존 239 + 신규).
- [ ] Run: `.venv/bin/uvicorn api.main:app --reload` 로 API 기동, `GET /api/market-trends?region=관악구&buildingType=rh&period=1y` 실호출로 시리즈 확인(실키 필요).

## Plan 2 (프론트, 별도 계획으로)
Vite + React + `echarts-for-react` 앱: 상단 필터·기간 퀵버튼, dataZoom(inside+slider), tooltip, 매매 `#00a84d`/전세 `#0066ff`. 지역 기본값 = `/api/register/parse` 응답의 `sigungu`. 개발 Vite proxy로 `/api` → FastAPI. `/frontend-design` 스킬 적용. 이 백엔드가 랜딩된 뒤 착수.
