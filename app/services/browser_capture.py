import asyncio
import base64
import sys
import time
import httpx
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Route, Request
from app.config import settings
from app.services.url_safety import validate_public_url, URLSafetyError


@dataclass
class CaptureResult:
    success: bool
    raw_text: str = ""
    screenshot_bytes: bytes = b""
    dom_html: str = ""
    http_status: Optional[int] = None
    duration_ms: int = 0
    failure_code: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BrowserCaptureService:
    def __init__(self):
        pass

    async def _capture_via_worker(
        self,
        canonical_url: str,
        include_selectors: List[str],
        ignore_selectors: List[str],
        numeric_selector: Optional[str],
        capture_dom: bool,
        start_time: float,
    ) -> CaptureResult:
        """Forward a validated capture to the authenticated remote Chromium service."""
        worker_url = settings.BROWSER_WORKER_URL.strip().rstrip("/")
        token = settings.BROWSER_WORKER_TOKEN.strip()
        if not worker_url or len(token) < 32:
            return CaptureResult(
                success=False,
                failure_code="BROWSER_WORKER_UNCONFIGURED",
                error_message=(
                    "Remote Chromium is not configured. Set either BROWSER_WORKER_URL and "
                    "BROWSER_WORKER_TOKEN, or BROWSERBASE_API_KEY and BROWSERBASE_PROJECT_ID."
                ),
                duration_ms=int((time.time() - start_time) * 1000),
            )

        payload = {
            "url": canonical_url,
            "include_selectors": include_selectors,
            "ignore_selectors": ignore_selectors,
            "numeric_selector": numeric_selector,
            "capture_dom": capture_dom,
        }
        timeout_seconds = max(5, min(settings.BROWSER_WORKER_TIMEOUT_SECONDS, 55))
        timeout = httpx.Timeout(timeout_seconds, connect=min(8, timeout_seconds))
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.post(
                    f"{worker_url}/internal/capture",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
            if response.status_code in (401, 403):
                return CaptureResult(
                    success=False,
                    failure_code="BROWSER_WORKER_AUTH_FAILED",
                    error_message="The remote browser worker rejected its shared authentication token.",
                    duration_ms=int((time.time() - start_time) * 1000),
                )
            response.raise_for_status()
            data = response.json()
            screenshot = data.get("screenshot_base64") or ""
            try:
                screenshot_bytes = base64.b64decode(screenshot, validate=True) if screenshot else b""
            except (ValueError, TypeError):
                return CaptureResult(
                    success=False,
                    failure_code="BROWSER_WORKER_INVALID_RESPONSE",
                    error_message="The remote browser worker returned an invalid screenshot payload.",
                    duration_ms=int((time.time() - start_time) * 1000),
                )
            return CaptureResult(
                success=bool(data.get("success", False)),
                raw_text=str(data.get("raw_text") or ""),
                screenshot_bytes=screenshot_bytes,
                dom_html=str(data.get("dom_html") or ""),
                http_status=data.get("http_status"),
                duration_ms=int(data.get("duration_ms") or (time.time() - start_time) * 1000),
                failure_code=data.get("failure_code"),
                error_message=data.get("error_message"),
                metadata={
                    **(data.get("metadata") if isinstance(data.get("metadata"), dict) else {}),
                    "execution": "remote-browser-worker",
                },
            )
        except httpx.TimeoutException:
            return CaptureResult(
                success=False,
                failure_code="BROWSER_WORKER_TIMEOUT",
                error_message="The remote browser worker timed out. Retry the preview.",
                duration_ms=int((time.time() - start_time) * 1000),
            )
        except httpx.HTTPStatusError as exc:
            return CaptureResult(
                success=False,
                failure_code="BROWSER_WORKER_HTTP_ERROR",
                error_message=f"The remote browser worker returned HTTP {exc.response.status_code}.",
                duration_ms=int((time.time() - start_time) * 1000),
            )
        except (httpx.HTTPError, ValueError):
            return CaptureResult(
                success=False,
                failure_code="BROWSER_WORKER_UNAVAILABLE",
                error_message="The remote browser worker could not be reached or returned an invalid response.",
                duration_ms=int((time.time() - start_time) * 1000),
            )

    async def _create_browserbase_session(self) -> tuple[str, str]:
        """Create a short-lived managed Chromium session and return (id, CDP URL)."""
        timeout_seconds = max(60, min(settings.BROWSERBASE_SESSION_TIMEOUT_SECONDS, 21600))
        timeout = httpx.Timeout(15, connect=5)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://api.browserbase.com/v1/sessions",
                headers={
                    "X-BB-API-Key": settings.BROWSERBASE_API_KEY.strip(),
                    "Content-Type": "application/json",
                },
                json={
                    "projectId": settings.BROWSERBASE_PROJECT_ID.strip(),
                    "timeout": timeout_seconds,
                },
            )
        response.raise_for_status()
        session = response.json()
        session_id = session.get("id")
        connect_url = session.get("connectUrl")
        if not isinstance(session_id, str) or not isinstance(connect_url, str):
            raise ValueError("Browserbase did not return a session id and CDP URL.")
        return session_id, connect_url

    async def _release_browserbase_session(self, session_id: str) -> None:
        """Release a managed session even if navigation or capture failed."""
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=4)) as client:
                await client.post(
                    f"https://api.browserbase.com/v1/sessions/{session_id}",
                    headers={
                        "X-BB-API-Key": settings.BROWSERBASE_API_KEY.strip(),
                        "Content-Type": "application/json",
                    },
                    json={"status": "REQUEST_RELEASE"},
                )
        except Exception:
            # The platform also enforces the session timeout; cleanup errors must
            # not hide the capture result or leak provider details to the UI.
            pass

    async def _capture_page_async(
        self,
        canonical_url: str,
        include_selectors: List[str],
        ignore_selectors: List[str],
        numeric_selector: Optional[str],
        capture_dom: bool,
        allow_test_fixtures: bool,
        start_time: float,
    ) -> CaptureResult:
        try:
            async with async_playwright() as p:
                browser: Browser | None = None
                browserbase_session_id: str | None = None
                try:
                    if settings.BROWSERBASE_API_KEY.strip() and settings.BROWSERBASE_PROJECT_ID.strip():
                        browserbase_session_id, connect_url = await self._create_browserbase_session()
                        browser = await p.chromium.connect_over_cdp(connect_url)
                    else:
                        browser = await p.chromium.launch(
                            headless=True,
                            args=[
                                "--no-sandbox",
                                "--disable-setuid-sandbox",
                                "--disable-dev-shm-usage",
                                "--disable-gpu",
                            ],
                        )

                    context = await browser.new_context(
                        viewport={"width": 1280, "height": 800},
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 ChangeWatch/1.0",
                        java_script_enabled=True,
                        ignore_https_errors=False,
                    )

                    # Subresource SSRF defense interception
                    async def handle_route(route: Route, request: Request):
                        req_url = request.url
                        # Skip data: or blob: urls
                        if req_url.startswith("data:") or req_url.startswith("blob:"):
                            await route.continue_()
                            return

                        sub_safe, _, _ = validate_public_url(req_url, allow_test_fixtures=allow_test_fixtures)
                        if not sub_safe:
                            await route.abort()
                        else:
                            await route.continue_()

                    await context.route("**/*", handle_route)
                    page = await context.new_page()

                    # Navigation with explicit timeout
                    response = None
                    try:
                        response = await page.goto(
                            canonical_url,
                            timeout=settings.BROWSER_NAV_TIMEOUT_SECONDS * 1000,
                            wait_until="domcontentloaded",
                        )
                    except Exception as nav_err:
                        err_str = str(nav_err).lower()
                        code = "TIMEOUT" if "timeout" in err_str else "NAVIGATION_FAILED"
                        await context.close()
                        return CaptureResult(
                            success=False,
                            failure_code=code,
                            error_message=f"Navigation failed: {str(nav_err)}",
                            duration_ms=int((time.time() - start_time) * 1000),
                        )

                    http_status = response.status if response else 200

                    # Check if target returned anti-bot / blocked status
                    if http_status in (401, 403, 429):
                        await context.close()
                        return CaptureResult(
                            success=False,
                            http_status=http_status,
                            failure_code="TARGET_BLOCKED",
                            error_message=f"Target web server returned HTTP {http_status} access blocked.",
                            duration_ms=int((time.time() - start_time) * 1000),
                        )

                    # Stabilization wait
                    await asyncio.sleep(settings.BROWSER_STABILIZATION_MS / 1000.0)

                    # Capture DOM for region picker if requested
                    dom_html = ""
                    if capture_dom:
                        dom_html = await page.content()

                    # Remove/hide ignored selectors in page
                    if ignore_selectors:
                        for sel in ignore_selectors:
                            try:
                                await page.evaluate(f"""
                                    document.querySelectorAll('{sel}').forEach(el => el.remove());
                                """)
                            except Exception:
                                pass

                    # Extract text
                    extracted_text = ""
                    if include_selectors:
                        chunks = []
                        for sel in include_selectors:
                            try:
                                texts = await page.evaluate(f"""
                                    Array.from(document.querySelectorAll('{sel}')).map(el => el.innerText || el.textContent || '')
                                """)
                                if texts:
                                    chunks.extend([t.strip() for t in texts if t.strip()])
                            except Exception:
                                pass
                        extracted_text = "\n\n".join(chunks)
                    else:
                        try:
                            extracted_text = await page.evaluate("""
                                document.body ? (document.body.innerText || document.body.textContent || '') : ''
                            """)
                        except Exception:
                            extracted_text = ""

                    # Extract numeric selector value if configured
                    numeric_text = ""
                    if numeric_selector:
                        try:
                            numeric_text = await page.evaluate(f"""
                                (function() {{
                                    const el = document.querySelector('{numeric_selector}');
                                    return el ? (el.innerText || el.textContent || '').trim() : '';
                                }})()
                            """)
                        except Exception:
                            pass

                    # The visual region picker only needs HTML. Avoid capturing and
                    # transferring a large PNG when DOM-only mode is requested.
                    screenshot_bytes = b""
                    if not capture_dom:
                        try:
                            screenshot_bytes = await page.screenshot(
                                full_page=True,
                                type="png",
                                timeout=15000,
                            )
                        except Exception:
                            # Fallback to viewport screenshot
                            screenshot_bytes = await page.screenshot(type="png")

                    await context.close()

                    duration_ms = int((time.time() - start_time) * 1000)
                    return CaptureResult(
                        success=True,
                        raw_text=extracted_text,
                        screenshot_bytes=screenshot_bytes,
                        dom_html=dom_html,
                        http_status=http_status,
                        duration_ms=duration_ms,
                        metadata={
                            "browser": "Chromium Headless",
                            "viewport": "1280x800",
                            "screenshot_bytes": len(screenshot_bytes),
                            "numeric_text": numeric_text,
                        }
                    )
                finally:
                    if browser is not None:
                        try:
                            await browser.close()
                        except Exception:
                            pass
                    if browserbase_session_id:
                        await self._release_browserbase_session(browserbase_session_id)

        except Exception:
            if settings.BROWSERBASE_API_KEY.strip() and settings.BROWSERBASE_PROJECT_ID.strip():
                return CaptureResult(
                    success=False,
                    failure_code="BROWSERBASE_UNAVAILABLE",
                    error_message=(
                        "Could not start or connect to the managed Chromium session. "
                        "Verify the Browserbase API key, project ID, and available session capacity."
                    ),
                    duration_ms=int((time.time() - start_time) * 1000),
                )
            return CaptureResult(
                success=False,
                failure_code="BROWSER_ERROR",
                error_message="The local browser could not start or complete the capture.",
                duration_ms=int((time.time() - start_time) * 1000),
            )

    def _run_capture_in_proactor_thread(
        self,
        canonical_url: str,
        include_selectors: List[str],
        ignore_selectors: List[str],
        numeric_selector: Optional[str],
        capture_dom: bool,
        allow_test_fixtures: bool,
        start_time: float,
    ) -> CaptureResult:
        """
        Executes Playwright on Windows inside a dedicated thread with a ProactorEventLoop.
        This resolves NotImplementedError in environments where Uvicorn or another framework
        forces a SelectorEventLoop on Windows (e.g. uvicorn --reload).
        """
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                self._capture_page_async(
                    canonical_url=canonical_url,
                    include_selectors=include_selectors,
                    ignore_selectors=ignore_selectors,
                    numeric_selector=numeric_selector,
                    capture_dom=capture_dom,
                    allow_test_fixtures=allow_test_fixtures,
                    start_time=start_time,
                )
            )
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    async def capture_page(
        self,
        url: str,
        include_selectors: Optional[List[str]] = None,
        ignore_selectors: Optional[List[str]] = None,
        numeric_selector: Optional[str] = None,
        capture_dom: bool = False,
        allow_test_fixtures: bool = False,
        local_only: bool = False,
    ) -> CaptureResult:
        start_time = time.time()

        # Step 1: Pre-navigation SSRF verification
        is_safe, canonical_url, fail_code = validate_public_url(url, allow_test_fixtures=allow_test_fixtures)
        if not is_safe:
            return CaptureResult(
                success=False,
                failure_code=fail_code or "BLOCKED_DESTINATION",
                error_message=canonical_url,
                duration_ms=int((time.time() - start_time) * 1000),
            )

        include_selectors = include_selectors or []
        ignore_selectors = ignore_selectors or []

        # Vercel request functions do not launch Chromium locally. Forward all
        # browser work to the persistent worker when configured; fail quickly and
        # clearly if the deployment has not been connected to one yet.
        if not local_only and settings.BROWSER_WORKER_URL.strip():
            return await self._capture_via_worker(
                canonical_url=canonical_url,
                include_selectors=include_selectors,
                ignore_selectors=ignore_selectors,
                numeric_selector=numeric_selector,
                capture_dom=capture_dom,
                start_time=start_time,
            )
        browserbase_configured = bool(
            settings.BROWSERBASE_API_KEY.strip() and settings.BROWSERBASE_PROJECT_ID.strip()
        )
        if not local_only and settings.is_vercel and not browserbase_configured:
            return CaptureResult(
                success=False,
                failure_code="BROWSER_WORKER_UNCONFIGURED",
                error_message=(
                    "Remote Chromium is not configured. Set BROWSER_WORKER_URL and "
                    "the same random BROWSER_WORKER_TOKEN on Vercel and the browser-worker service."
                ),
                duration_ms=int((time.time() - start_time) * 1000),
            )

        # Step 2: Event Loop Compatibility check on Windows
        # If current loop does not support subprocesses (e.g. SelectorEventLoop under uvicorn --reload),
        # dispatch capture to a dedicated ProactorEventLoop thread.
        current_loop = asyncio.get_running_loop()
        is_windows = sys.platform == "win32"
        if is_windows and not isinstance(current_loop, getattr(asyncio, "ProactorEventLoop", object)):
            return await asyncio.to_thread(
                self._run_capture_in_proactor_thread,
                canonical_url=canonical_url,
                include_selectors=include_selectors,
                ignore_selectors=ignore_selectors,
                numeric_selector=numeric_selector,
                capture_dom=capture_dom,
                allow_test_fixtures=allow_test_fixtures,
                start_time=start_time,
            )

        return await self._capture_page_async(
            canonical_url=canonical_url,
            include_selectors=include_selectors,
            ignore_selectors=ignore_selectors,
            numeric_selector=numeric_selector,
            capture_dom=capture_dom,
            allow_test_fixtures=allow_test_fixtures,
            start_time=start_time,
        )


browser_capture_service = BrowserCaptureService()
