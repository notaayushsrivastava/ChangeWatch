import base64
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services.browser_capture import BrowserCaptureService, CaptureResult
from app.worker_api import app as browser_worker_app, browser_capture_service


def test_browser_worker_health_is_available():
    with TestClient(browser_worker_app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["service"] == "changewatch-browser-worker"


def test_browser_worker_fails_closed_without_shared_token(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_WORKER_TOKEN", "")
    with TestClient(browser_worker_app) as client:
        response = client.post(
            "/internal/capture",
            json={"url": "https://example.com", "capture_dom": True},
        )

    assert response.status_code == 503


def test_browser_worker_rejects_invalid_token(monkeypatch):
    monkeypatch.setattr(settings, "BROWSER_WORKER_TOKEN", "x" * 40)
    with TestClient(browser_worker_app) as client:
        response = client.post(
            "/internal/capture",
            headers={"Authorization": "Bearer wrong-token"},
            json={"url": "https://example.com", "capture_dom": True},
        )

    assert response.status_code == 401


def test_browser_worker_returns_capture_result_and_forces_local_execution(monkeypatch):
    token = "unit-test-browser-worker-token-0123456789"
    monkeypatch.setattr(settings, "BROWSER_WORKER_TOKEN", token)

    async def fake_capture(**kwargs):
        assert kwargs["local_only"] is True
        assert kwargs["allow_test_fixtures"] is False
        return CaptureResult(
            success=True,
            dom_html="<html><body>test</body></html>",
            screenshot_bytes=b"png-bytes",
            http_status=200,
            duration_ms=123,
            metadata={"browser": "test"},
        )

    monkeypatch.setattr(browser_capture_service, "capture_page", fake_capture)
    with TestClient(browser_worker_app) as client:
        response = client.post(
            "/internal/capture",
            headers={"Authorization": f"Bearer {token}"},
            json={"url": "https://example.com", "capture_dom": True},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["dom_html"].startswith("<html>")
    assert payload["screenshot_base64"] == base64.b64encode(b"png-bytes").decode("ascii")


@pytest.mark.asyncio
async def test_capture_service_forwards_to_configured_worker(monkeypatch):
    from app.services import browser_capture as capture_module

    monkeypatch.setattr(settings, "BROWSER_WORKER_URL", "https://worker.example")
    monkeypatch.setattr(settings, "BROWSER_WORKER_TOKEN", "x" * 40)
    monkeypatch.setattr(
        capture_module,
        "validate_public_url",
        lambda url, allow_test_fixtures=False: (True, url, None),
    )
    service = BrowserCaptureService()
    expected = CaptureResult(success=True, dom_html="<html></html>")
    forward = AsyncMock(return_value=expected)
    monkeypatch.setattr(service, "_capture_via_worker", forward)

    result = await service.capture_page("https://example.com", capture_dom=True)

    assert result is expected
    forward.assert_awaited_once()
    assert forward.await_args.kwargs["capture_dom"] is True


@pytest.mark.asyncio
async def test_vercel_fails_clearly_without_worker_instead_of_launching_local_chromium(monkeypatch):
    from app.services import browser_capture as capture_module

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(settings, "BROWSER_WORKER_URL", "")
    monkeypatch.setattr(settings, "BROWSER_WORKER_TOKEN", "")
    monkeypatch.setattr(
        capture_module,
        "validate_public_url",
        lambda url, allow_test_fixtures=False: (True, url, None),
    )

    result = await BrowserCaptureService().capture_page(
        "https://example.com",
        capture_dom=True,
    )

    assert result.success is False
    assert result.failure_code == "BROWSER_WORKER_UNCONFIGURED"
    assert "BROWSER_WORKER_URL" in (result.error_message or "")
