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
                             allow_fetch=not _READONLY)
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
        warnings.append(
            f"{fields['sigungu']}는 아직 실거래가 시세를 수집하지 않은 지역이다"
            "(현재 서울 25개 구만 수집). 시세를 직접 입력하면 미회수 기대손실까지"
            " 그대로 계산된다."
        )
    return {
        **fields,
        "warnings": warnings,
        "region_code": region_code,
        "region_supported": region_code is not None,
        "building_type": building_type,
    }


# /api/decision 입력 스키마. raw dict로 두면 필드명 오타가 검증 없이 통과해서
# 위험 입력이 조용히 빠지고 화면엔 "미반영"만 뜬다 — 사용자는 이유를 알 수 없다.
# extra="forbid"라서 오타는 422로 즉시 드러난다.
class _Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    monthly_income_krw: int = Field(gt=0, description="월소득(원)")
    assets_krw: int = Field(default=0, ge=0)
    age: int = Field(default=30, ge=0, le=120)
    region: str = "관악구"
    expected_stay_years: int = Field(default=4, ge=1, le=50)
    is_homeless: bool = True
    is_household_head: bool = True
    works_at_sme: bool = False


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
    떨어지므로(`_pick_level`), 가장 좁은 것부터 요청하고 응답의 level_label이
    실제로 쓰인 단위를 알려준다.
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
        "level": trends.get("level", "sigungu"),
        "pyeong_price_manwon": pyeong_manwon,
        "area_m2": area,
        "bucket": bucket,
        "level_label": trends.get("level_label", ""),
        "note": "국토부 실거래 매매 평당가 집계 × 전용면적 — 특정 호실이 아닌 지역 평균 추정치",
    }


@app.post("/api/decision")
def post_decision(body: _DecisionBody, cache=Depends(get_cache)):
    """프로필+매물 → 전세 vs 월세 비교 + 적정 주거비 + 청년 금융지원."""
    profile = body.profile.model_dump()
    listing = body.listing.model_dump()
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
