import asyncio
import sys
import time
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
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ]
                )
                try:
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

                    # Capture full-page screenshot bounded by max height
                    screenshot_bytes = b""
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
                    await browser.close()

        except Exception as e:
            return CaptureResult(
                success=False,
                failure_code="BROWSER_ERROR",
                error_message=str(e),
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
