"""온전 REST 계층 — 시세 추이 + 등기부 파싱. onjeon 모듈을 감싸기만 한다."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from onjeon.config import load_env
from onjeon.data_pipeline.regions import resolve_lawd_cd
from onjeon.decision import decide
from onjeon.l3.register_risk import grade_register
from onjeon.l4.register_explain import explain
from onjeon.market.building import auction_type, building_type_for_use
from onjeon.market.cache import open_cache
from onjeon.market.map import market_map
from onjeon.market.pyeong import estimate_market_price_krw
from onjeon.market.trends import market_trends
from onjeon.register.parse import NoTextLayer, parse_register_pdf

load_env()  # .env의 MOLIT_API_KEY 등을 프로세스 환경으로 — 라이브 시세 조회용
app = FastAPI(title="온전 API")
_CACHE_PATH = Path("data/cache.db")
_MAX_UPLOAD = 20 * 1024 * 1024  # 등기부 PDF 업로드 상한 20MB

# 공개 배포 자세: 1이면 시세 조회가 캐시만 읽고 외부 국토부 API를 호출하지 않는다.
# 인증 없는 공개 엔드포인트가 외부 호출 경로를 타면(1요청 최대 183회) 누구나 운영자의
# 실명 인증 서비스키 쿼터를 소진시킬 수 있다. 공개 URL로 띄울 땐 반드시 1로 두고,
# 캐시는 scripts/warm_cache.py로 미리 채운다. 로컬 개발은 기본값(0)이 편하다.
_READONLY = os.environ.get("ONJEON_PUBLIC_READONLY", "").strip() in {"1", "true", "yes"}

# 키가 없으면 조회를 시도조차 하지 않는다. 캐시에 없는 달(캐시는 수집 시점까지만 차 있고
# 날짜가 지나면 최근 달이 계속 빈다)을 채우러 들어갔다가 "MOLIT_API_KEY가 없다"로 400이
# 나면, 키 없이 캐시로 돌아야 하는 심사·시연 환경에서 시세 화면이 통째로 죽는다.
# _READONLY와 따로 두는 이유: _READONLY는 공개 배포 자세라 L4 해설(Gemini)까지 끄는데,
# MOLIT 키가 없는 것과 해설을 끄는 것은 아무 상관이 없다.
_CAN_FETCH_MOLIT = bool(os.environ.get("MOLIT_API_KEY", "").strip())


def get_cache():
    """요청 스코프 캐시 연결(테스트는 dependency_overrides로 교체)."""
    conn = open_cache(_CACHE_PATH)
    try:
        yield conn
    finally:
        conn.close()


@app.get("/api/market-trends")
def get_market_trends(region: str, buildingType: str, period: str, cache=Depends(get_cache),
                      dong: str | None = None, jibun: str | None = None):
    try:
        return market_trends(region, buildingType, period, cache=cache,
                             queried_at=date.today().isoformat(), dong=dong, jibun=jibun,
                             allow_fetch=not _READONLY and _CAN_FETCH_MOLIT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/market-map")
def get_market_map(buildingType: str, period: str, metric: str = "mae", cache=Depends(get_cache)):
    """서울 법정동별 평당가 — 지도용. 항상 캐시만 읽는다(market.map 모듈 주석 참조)."""
    try:
        return market_map(cache, buildingType, period, metric)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/register/parse")
def post_register_parse(file: UploadFile):
    # 동기 def인 것이 핵심 — FastAPI가 이 핸들러를 스레드풀에서 돌린다. async def로 두면
    # pdfplumber·tesseract(동기·CPU)가 이벤트 루프를 점유해서, 등기부 업로드 1건이
    # 다른 방문자의 시세 조회까지 전부 멈춘다(50MB 실측 73초 동안 서버 전체 정지).
    # 그래서 await file.read()가 아니라 file.file.read()로 읽는다.
    #
    # 크기 상한: 등기부는 보통 수백 KB. 상한이 없으면 대용량 업로드 하나가
    # 메모리+파싱으로 서버를 오래 점유한다.
    data = file.file.read(_MAX_UPLOAD + 1)
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(
            status_code=413,
            detail=f"파일이 너무 큽니다 — {_MAX_UPLOAD // (1024 * 1024)}MB 이하 PDF만 올려주세요",
        )
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(data)
        tmp.flush()
        try:
            fields = parse_register_pdf(tmp.name)
        except NoTextLayer as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # 손상 PDF·비PDF 등 업로드 경계 방어 — 500 대신 친화 422
            raise HTTPException(
                status_code=422,
                detail="등기부 파일을 읽지 못했습니다 — PDF가 맞는지 확인하거나 수동 입력하세요",
            ) from exc
    region_code = resolve_lawd_cd(fields.get("sigungu") or "")
    building_type = None
    if fields.get("building_use"):
        try:
            building_type = building_type_for_use(fields["building_use"])
        except ValueError:
            building_type = None
    # 시세 수집 범위 밖(서울 25개 구 외)이면 그렇다고 말한다. 예전엔 region_code가
    # 조용히 None이 되고 화면도 지역 칸을 그냥 안 채워서, 사용자는 등기부가 잘못
    # 읽힌 줄 알았다. 코드 표만 전국으로 넓혀도 캐시에 해당 지역 거래가 0건이라
    # (공개 배포는 캐시만 읽는다) 시세는 여전히 안 나온다 — 그래서 정직하게
    # "직접 입력하면 나머지는 계산된다"로 안내한다.
    warnings = list(fields.get("warnings") or [])
    if fields.get("sigungu") and region_code is None:
        # 비서울이면 두 가지가 함께 막힌다. 하나만 말하면 나머지를 나중에 발견한다.
        warnings.append(
            f"{fields['sigungu']}는 아직 지원 범위 밖이다 — 이 서비스는 현재 서울 25개 구만 "
            "다루고, 이 지역은 의사결정 계산을 **막는다**(/api/decision이 400). "
            "(1) 실거래가 시세를 수집하지 않아 시세 자동 추정이 안 되고, "
            "(2) 소액임차인 최우선변제도 주택임대차보호법 시행령 §10·§11의 서울 구간만 "
            "반영돼 있다. 시행령은 지역을 4구간으로 나누고 금액이 2배 이상 벌어지는데"
            "(서울 5,500만 / 그 밖의 지역 2,500만), 두 축이 함께 빈 상태로 낸 기대손실은 "
            "근거가 없다. 등기부에서 읽은 채권최고액·면적은 그대로 쓸 수 있다."
        )
    # 등기부에 적힌 권리 제한(가압류·경매개시·신탁 등) → 등급. 결정론 룰 테이블이라
    # 왕복도 지연도 늘지 않는다. E[Loss]와는 다른 축이다(l3.register_risk 참조).
    register_risk = grade_register(fields)
    # 문단 설명만 LLM(Gemini)에 맡긴다 — 곁가지라 실패해도 None이 오고 필드만 빠진다.
    # 공개 배포(READONLY)에선 끈다: 인증 없는 업로드 1건이 곧 과금이라, 국토부 키를
    # 막아둔 것과 같은 이유로 막아야 한다. 말할 항목이 없으면 아예 부르지 않는다.
    # 이 핸들러는 스레드풀에서 도는 동기 함수라, 호출한 만큼 이 요청 하나가 길어진다.
    if not _READONLY and register_risk["items"]:
        explanation = explain(register_risk, warnings)
        if explanation:
            register_risk["explanation"] = explanation
    return {
        # rights(원시 탐지 결과)는 빼고 보낸다 — register_risk.items가 같은 내용을
        # 등급까지 붙여 싣는다. 둘 다 보내면 화면이 무엇을 믿을지가 두 갈래가 된다.
        **{k: v for k, v in fields.items() if k != "rights"},
        "warnings": warnings,
        "register_risk": register_risk,
        "region_code": region_code,
        "region_supported": region_code is not None,
        "building_type": building_type,
    }


# /api/decision 입력 스키마. raw dict로 두면 필드명 오타가 검증 없이 통과해서
# 위험 입력이 조용히 빠지고 화면엔 "미반영"만 뜬다 — 사용자는 이유를 알 수 없다.
# extra="forbid"라서 오타는 422로 즉시 드러난다.
class _Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 0을 막지 않는다. 무소득 청년은 이 서비스가 도와야 할 대상이지 거절할 대상이 아니고,
    # 실제로 청년전용 버팀목전세자금대출은 소득 **상한**만 있고 하한이 없다(무소득 신청 가능).
    # 소득 때문에 못 받는 상품이 있으면 그건 422가 아니라 '미자격 반증'으로 답해야 한다.
    monthly_income_krw: int = Field(ge=0, description="월소득(원). 0=무소득 — 거절이 아니라 결과로 답한다")
    assets_krw: int = Field(default=0, ge=0)
    age: int = Field(default=30, ge=0, le=120)
    region: str = "관악구"
    expected_stay_years: int = Field(default=4, ge=1, le=50)
    is_homeless: bool = True
    is_household_head: bool = True
    works_at_sme: bool = False

    # ── 가구 형태. 정책 상품의 우대·완화가 대부분 여기에 걸린다.
    # 기본값은 전부 '해당 없음'이라 안 보내면 지금까지와 같은 결과가 나온다.
    is_married: bool = False
    # 혼인 경과 연수. 신혼가구 = 7년 이내. 기혼인데 이 값이 없으면 신혼 판정을
    # 하지 않는다 — 모르는 것을 '아니다'로 단정하지 않기 위해서다.
    marriage_years: int | None = Field(default=None, ge=0, le=80)
    children_count: int = Field(default=0, ge=0, le=20, description="미성년 자녀 수")
    # 막내 나이(만). 신생아 특례(출산 2년 이내) 판정에 쓴다.
    youngest_child_age: int | None = Field(default=None, ge=0, le=30)

    # 신용: 기금 대출은 신용'점수' 커트라인이 아니라 신용도판단정보(연체·대지급·
    # 대위변제·부도) 등록 여부로 거른다. 그래서 점수가 아니라 불리언이다.
    # 점수를 임계값으로 쓰면 근거 없는 숫자를 지어내는 것이 된다(CLAUDE.md 원칙 1·6).
    has_credit_delinquency: bool = Field(
        default=False, description="연체·대위변제 등 신용도판단정보 등록 여부. 기금 대출 제한 사유"
    )
    # 참고용 입력. **자격 판정에 쓰지 않는다** — 점수→금리/승인 기준표를 검증하지
    # 못했기 때문이다. 화면 안내에만 쓰고, 검증된 표가 생기면 그때 계산에 넣는다.
    credit_score: int | None = Field(
        default=None, ge=0, le=1000, description="NICE/KCB 신용점수(참고용, 판정 미반영)"
    )


class _Listing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "wolse"
    deposit_krw: int = Field(default=0, ge=0)
    monthly_rent_krw: int = Field(default=0, ge=0)
    maintenance_krw: int = Field(default=0, ge=0)
    jeonse_deposit_krw: int = Field(default=0, ge=0)
    wolse_deposit_krw: int = Field(default=0, ge=0)
    wolse_monthly_rent_krw: int = Field(default=0, ge=0)
    # 매수 비교용(선택) + E[Loss]의 시세 입력. 없으면 캐시 평당가로 추정한다.
    market_price_krw: int | None = Field(default=None, ge=0)
    # E[Loss] 입력 — 등기부 을구의 근저당 채권최고액 합계
    senior_claims_krw: int | None = Field(default=None, ge=0)
    building_type: str | None = None
    exclusive_area_m2: float | None = Field(default=None, gt=0)
    insured: bool = False
    # 매물 소재지. profile.region(희망지역)과 다를 수 있다 — 시세·낙찰가율은
    # 매물이 있는 곳 기준이어야 하므로 이걸 우선한다.
    region: str | None = None
    # 법정동·지번이 있으면 시세 추정을 그 단위로 좁힌다 — 구 평균보다 훨씬 정확하다
    dong: str | None = None
    jibun: str | None = None
    # 서버가 채우는 내부 필드 — 시세 추정이 어느 집계 단위에서 왔는지(밴드 폭 결정용).
    # 클라이언트가 보내도 무해하지만 보낼 필요는 없다.
    price_level: str | None = None


class _DecisionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: _Profile
    listing: _Listing


def _estimate_price(listing: dict, region: str, cache) -> tuple[int | None, dict | None]:
    """시세 미입력 시 캐시 평당가 × 전용면적으로 추정 → (시세(원), 출처).

    항상 캐시만 읽는다(allow_fetch=False). 의사결정 1요청이 국토부 API를 최대 183회
    호출하는 경로를 타면 공개 URL에서 키 쿼터가 소진된다(market.trends 주석 참조).
    매매(mae) 평당가만 쓴다 — 경매 회수는 매매 시세 기준이라 전세 평당가를 넣으면
    LGD가 무의미해진다.

    **지번 → 동 → 구 순으로 좁혀서 시도한다.** 시세 오차는 P(사고)와 LGD 양쪽에
    들어가 증폭되므로(±20% 밴드가 기대손실 6배를 만든다) 좁은 지역의 집계가
    훨씬 낫다. market_trends는 해당 단위에 거래가 없으면 자동으로 상위 레벨로
    떨어지므로(`_pick_level`), 가장 좁은 것부터 요청하고 응답이 실제로 쓰인
    단위를 알려준다.

    쓰는 건 `mae_level`이지 `level`이 아니다 — 차트 레벨(level)은 전세·월세 거래도
    세므로, 그걸 밴드에 넣으면 매매 거래가 거의 없는 건물이 '건물 단위 정밀도'를
    주장하게 된다(trends.market_trends 독스트링 참조).
    """
    area = listing.get("exclusive_area_m2")
    btype = listing.get("building_type")
    if not area or not btype:
        return None, None
    try:
        trends = market_trends(
            region, btype, "1y", cache=cache, queried_at=date.today().isoformat(),
            allow_fetch=False,
            dong=listing.get("dong"), jibun=listing.get("jibun"),
        )
    except ValueError:
        return None, None
    recent = [(d, v) for d, v in zip(trends["dates"], trends["mae_price"]) if v is not None]
    if not recent:
        return None, None
    bucket, pyeong_manwon = recent[-1]
    return estimate_market_price_krw(
        pyeong_price_manwon=pyeong_manwon, area_m2=area
    ), {
        # 어느 집계 단위에서 온 값인지 — 밴드 폭이 여기에 달려 있다(decision._price_band)
        "level": trends.get("mae_level", "sigungu"),
        "pyeong_price_manwon": pyeong_manwon,
        "area_m2": area,
        "bucket": bucket,
        "level_label": trends.get("mae_level_label", ""),
        "note": "국토부 실거래 매매 평당가 집계 × 전용면적 — 특정 호실이 아닌 지역 평균 추정치",
    }


@app.post("/api/decision")
def post_decision(body: _DecisionBody, cache=Depends(get_cache)):
    """프로필+매물 → 전세 vs 월세 비교 + 적정 주거비 + 청년 금융지원."""
    profile = body.profile.model_dump()
    listing = body.listing.model_dump()
    # 서울 밖은 계산하지 않고 막는다. 예전엔 경고만 띄우고 계산했는데, 그러면
    # 시세 추정(캐시에 거래 0건)과 최우선변제(서울 값만 있음) 두 축이 동시에
    # 비어 있는 상태로 숫자가 나온다 — 안내를 읽지 않은 사용자에게는 그냥
    # '계산된 결론'으로 보인다. 근거가 반쪽인 결론을 내는 대신 입구에서 거절한다.
    # resolve_lawd_cd가 지원 범위의 단일 정의다(업로드 경고도 같은 함수를 쓴다).
    for label, region in (("매물 소재지", listing.get("region")), ("희망지역", profile["region"])):
        if region and resolve_lawd_cd(region) is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{label} '{region}'는 아직 지원하지 않습니다 — 현재 서울 25개 구만 계산합니다. "
                    "실거래가 시세를 서울만 수집하고 있고, 소액임차인 최우선변제도 "
                    "주택임대차보호법 시행령 §10·§11의 서울 구간(5,500만/1억6,500만)만 "
                    "반영돼 있습니다. 다른 지역은 이 두 값이 함께 비어서 기대손실이 "
                    "근거 없이 나오므로, 틀린 숫자를 보여드리는 대신 막았습니다."
                ),
            )
    # 순서 주의: market_trends는 유형 **코드**(apt/rh/offi/sh)를 받고 낙찰가율 룰은
    # **한글**을 받는다. 시세 추정을 먼저 하고 그다음에 한글로 정규화한다.
    price_source = None
    if not listing.get("market_price_krw"):
        # 매물 소재지 우선 — 희망지역의 평당가로 이 매물 시세를 추정하면 엉뚱한 값이 된다
        region = listing.get("region") or profile["region"]
        estimated, price_source = _estimate_price(listing, region, cache)
        if estimated:
            listing["market_price_krw"] = estimated
            # 사용자가 입력한 매매가가 아니라 추정치라는 사실을 응답에 남긴다.
            # 이게 없으면 매수 비교가 추정치를 '예상 매매가'로 제시해 오해를 준다.
            price_source["estimated"] = True
            # 집계 단위를 decision으로 넘겨 밴드 폭을 결정하게 한다. 사용자가 직접
            # 입력한 매매가에는 이 키가 없으므로 밴드도 붙지 않는다.
            listing["price_level"] = price_source["level"]
    if listing.get("building_type"):
        listing["building_type"] = auction_type(listing["building_type"])
    try:
        result = decide(profile, listing)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if price_source:
        result["sources"]["market_price_estimate"] = price_source
    return result


# 빌드된 프론트(web/dist)를 같은 서버에서 서빙 — 단일 아티팩트 배포.
# /api 라우트가 먼저 등록돼 우선하며, 나머지 경로는 SPA(index.html)로 폴백.
_DIST = Path("web/dist")
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="web")
