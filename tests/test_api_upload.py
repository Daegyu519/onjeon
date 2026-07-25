"""등기부 업로드 엔드포인트 경계 — 스레드풀 실행 + 크기 상한 + 손상 파일.

이 파일이 지키는 것(회귀 시 즉시 실패):
  1. post_register_parse가 async가 아니어야 한다. async면 pdfplumber·tesseract가
     이벤트 루프를 점유해 업로드 1건이 서버 전체를 멈춘다(실측 최대 73초).
     FastAPI는 동기 def 핸들러만 스레드풀로 넘긴다.
  2. 20MB 초과 업로드는 파싱 전에 413으로 잘려야 한다.
  3. PDF가 아닌 바이트는 500이 아니라 친화적 422로 나가야 한다.

TestClient(httpx)를 쓰지 않고 핸들러를 직접 호출한다 — 이 파일이 검증하는 건
라우팅이 아니라 핸들러 내부의 읽기·경계 처리다.
"""

from __future__ import annotations

import inspect
import io

import pytest
from fastapi import HTTPException, UploadFile

from api.main import _MAX_UPLOAD, post_register_parse


def _upload(data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename="register.pdf")


def test_handler_is_sync_so_fastapi_uses_threadpool():
    """REGRESSION: async def로 되돌리면 업로드가 이벤트 루프를 점유한다."""
    assert not inspect.iscoroutinefunction(post_register_parse), (
        "post_register_parse는 동기 def여야 한다 — async면 동기 파싱이 "
        "이벤트 루프를 막아 다른 요청이 전부 대기한다"
    )


def test_oversize_upload_rejected_before_parsing():
    """상한 초과는 파싱에 들어가기 전에 413으로 끊긴다."""
    with pytest.raises(HTTPException) as exc:
        post_register_parse(_upload(b"%PDF-1.4" + b"\0" * _MAX_UPLOAD))
    assert exc.value.status_code == 413
    assert "MB" in exc.value.detail, "사용자가 상한 크기를 알 수 있어야 한다"


def test_non_pdf_gives_friendly_422_not_500():
    """비-PDF 바이트는 스택트레이스(500)가 아니라 안내(422)로 나간다."""
    with pytest.raises(HTTPException) as exc:
        post_register_parse(_upload(b"this is not a pdf"))
    assert exc.value.status_code == 422
