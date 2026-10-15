"""Authenticated HTTP API for running Chromium outside serverless web functions.

Deploy this ASGI app as a separate persistent container service. It intentionally
exposes only health and capture endpoints; application database routes are not mounted.
"""
import base64
import hmac
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.browser_capture import browser_capture_service


app = FastAPI(
    title="ChangeWatch Browser Worker",
    description="Private, authenticated Chromium capture API for ChangeWatch",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


class CaptureRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4096)
    include_selectors: list[str] = Field(default_factory=list, max_length=40)
    ignore_selectors: list[str] = Field(default_factory=list, max_length=40)
    numeric_selector: str | None = Field(default=None, max_length=512)
    capture_dom: bool = False


class CaptureResponse(BaseModel):
    success: bool
    raw_text: str = ""
    screenshot_base64: str = ""
    dom_html: str = ""
    http_status: int | None = None
    duration_ms: int = 0
    failure_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "changewatch-browser-worker"}


@app.post("/internal/capture", response_model=CaptureResponse)
async def capture(
    payload: CaptureRequest,
    authorization: str | None = Header(default=None),
) -> CaptureResponse:
    expected = settings.BROWSER_WORKER_TOKEN.strip()
    if len(expected) < 32:
        raise HTTPException(
            status_code=503,
            detail="Browser worker authentication is not configured.",
        )

    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid browser worker credentials.")

    # capture_page validates the destination and every browser request. The
    # internal flag explicitly prevents this service forwarding back to itself.
    result = await browser_capture_service.capture_page(
        url=payload.url,
        include_selectors=payload.include_selectors,
        ignore_selectors=payload.ignore_selectors,
        numeric_selector=payload.numeric_selector,
        capture_dom=payload.capture_dom,
        allow_test_fixtures=False,
        local_only=True,
    )
    return CaptureResponse(
        success=result.success,
        raw_text=result.raw_text,
        screenshot_base64=base64.b64encode(result.screenshot_bytes).decode("ascii"),
        dom_html=result.dom_html,
        http_status=result.http_status,
        duration_ms=result.duration_ms,
        failure_code=result.failure_code,
        error_message=result.error_message,
        metadata=result.metadata,
    )
