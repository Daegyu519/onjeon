"""온전 REST 계층 — 시세 추이 + 등기부 파싱. onjeon 모듈을 감싸기만 한다."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

from onjeon.config import load_env
from onjeon.data_pipeline.regions import resolve_lawd_cd
from onjeon.decision import decide
from onjeon.market.building import building_type_for_use
from onjeon.market.cache import open_cache
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


@app.post("/api/register/parse")
async def post_register_parse(file: UploadFile, cache=Depends(get_cache)):
    # 크기 상한: 등기부는 보통 수백 KB. 상한이 없으면 대용량 업로드 하나가
    # 메모리+파싱으로 서버를 오래 점유한다(50MB 실측 73초).
    data = await file.read(_MAX_UPLOAD + 1)
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
    return {**fields, "region_code": region_code, "building_type": building_type}


@app.post("/api/decision")
def post_decision(body: dict = Body(...)):
    """프로필+매물 → 적정 주거비 진단 + 청년 금융지원 추천."""
    try:
        return decide(body.get("profile", {}), body.get("listing", {}))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# 빌드된 프론트(web/dist)를 같은 서버에서 서빙 — 단일 아티팩트 배포.
# /api 라우트가 먼저 등록돼 우선하며, 나머지 경로는 SPA(index.html)로 폴백.
_DIST = Path("web/dist")
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="web")
