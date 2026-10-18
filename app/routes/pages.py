from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, Response, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import get_db
from app.config import settings
from app.dependencies import get_current_user_optional, get_or_create_csrf_token, validate_csrf

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
static_dir = Path(__file__).resolve().parent.parent / "static"


@router.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "docs.html", {
        "current_user": user,
        "csrf_token": csrf_token,
    })


@router.get("/docs/mcp", response_class=HTMLResponse)
async def mcp_docs_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    csrf_token = get_or_create_csrf_token(request)
    base_url = (
        "https://changewatch.aayushsrivastava.com"
        if (settings.is_production or (settings.APP_BASE_URL and "changewatch.aayushsrivastava.com" in settings.APP_BASE_URL))
        else str(request.base_url).rstrip("/")
    )
    return templates.TemplateResponse(request, "docs_mcp.html", {
        "current_user": user,
        "csrf_token": csrf_token,
        "base_url": base_url,
        "mcp_http_url": f"{base_url}/mcp",
        "mcp_sse_url": f"{base_url}/sse",
    })


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "privacy.html", {
        "current_user": user,
        "csrf_token": csrf_token,
    })


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "terms.html", {
        "current_user": user,
        "csrf_token": csrf_token,
    })


@router.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "contact.html", {
        "current_user": user,
        "csrf_token": csrf_token,
    })


@router.post("/contact", response_class=HTMLResponse)
async def submit_contact(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    subject: str = Form(...),
    message: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    validate_csrf(request, csrf_token)
    user = get_current_user_optional(request, db)
    # Form submission acknowledgment
    success_msg = f"Thank you, {name.strip()}! Your message regarding '{subject.strip()}' has been received. Aayush Srivastava will reply to {email.strip()} shortly."
    new_csrf = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "contact.html", {
        "current_user": user,
        "csrf_token": new_csrf,
        "message": success_msg,
    })


@router.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    ico_path = static_dir / "favicon.ico"
    if ico_path.exists():
        return FileResponse(ico_path, media_type="image/x-icon")
    svg_path = static_dir / "favicon.svg"
    return FileResponse(svg_path, media_type="image/svg+xml")


@router.get("/robots.txt", response_class=Response, include_in_schema=False)
def robots_txt(request: Request):
    base_url = (settings.APP_BASE_URL or str(request.base_url)).rstrip("/")
    content = f"""User-agent: *
Allow: /
Allow: /docs
Allow: /privacy
Allow: /terms
Allow: /contact
Allow: /llms.txt
Disallow: /dashboard
Disallow: /monitors/
Disallow: /settings/
Disallow: /internal/
Disallow: /artifacts/
Disallow: /auth/

Sitemap: {base_url}/sitemap.xml
"""
    return Response(content=content, media_type="text/plain; charset=utf-8")


@router.get("/sitemap.xml", response_class=Response, include_in_schema=False)
def sitemap_xml(request: Request):
    base_url = (settings.APP_BASE_URL or str(request.base_url)).rstrip("/")
    content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{base_url}/</loc>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{base_url}/docs</loc>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>
  <url>
    <loc>{base_url}/contact</loc>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
  </url>
  <url>
    <loc>{base_url}/privacy</loc>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>
  <url>
    <loc>{base_url}/terms</loc>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
  </url>
  <url>
    <loc>{base_url}/llms.txt</loc>
    <changefreq>weekly</changefreq>
    <priority>0.6</priority>
  </url>
  <url>
    <loc>{base_url}/auth/login</loc>
    <changefreq>monthly</changefreq>
    <priority>0.6</priority>
  </url>
  <url>
    <loc>{base_url}/auth/signup</loc>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
  </url>
</urlset>
"""
    return Response(content=content.strip(), media_type="application/xml; charset=utf-8")


@router.get("/llms.txt", response_class=Response, include_in_schema=False)
def llms_txt(request: Request):
    base_url = (settings.APP_BASE_URL or str(request.base_url)).rstrip("/")
    content = f"""# ChangeWatch

> Autonomous public web page monitoring with noise normalization, two-tier SSRF containment, multi-mode visual and text diffs, and serverless Vercel deployment.

ChangeWatch monitors public web pages and alerts users to genuine, meaningful content changes while suppressing ordinary page churn such as timestamps, view counters, dynamic tokens, and ads.

## Core Capabilities
- **Deterministic Noise Normalization**: Systematically sanitizes volatile relative timestamps, ISO 8601 dates, vanity engagement counters, whitespace variations, and dynamic session tokens before SHA-256 fingerprinting.
- **Two-Tier SSRF Defense Fortress**: Pre-navigation DNS resolution blocks RFC 1918 private subnets, IPv6 loopbacks, localhost, link-local, and cloud metadata (169.254.169.254). Playwright Chromium route interception blocks all outgoing subresource requests targeting internal destinations.
- **Visual Region Studio**: Point-and-click selector configuration inside a sandboxed iframe. Supports Watch Scopes (narrow monitoring to specific DOM elements) and Ignore Selectors (strip noise elements before normalization).
- **Multi-Mode Diff Studio**: Line-by-line normalized text diffs (+/-), synchronized side-by-side screenshot comparisons, draggable before/after swipe slider, and Pillow computer vision pixel difference masks.
- **Numeric Tracking & Sparklines**: Extracts numbers, currencies ($, €, £, ₹), percentages, and stock counts from CSS selectors, rendering historical SVG trend sparklines.
- **Keyword-Only Alert Filtering**: Optional trigger keywords (e.g. "in stock", "price drop") that suppress notifications unless matching keywords appear in added lines.
- **Multi-Channel Notification Dispatch**: Rich Discord webhook embeds with pre-rendered diffs, and email dispatches (Console, SMTP, Resend). Webhook secrets encrypted with Fernet at rest.
- **Store-on-Change Policy**: Unchanged checks only record lightweight audit run records; persistent screenshot and DOM artifacts are strictly retained for baselines and genuine changes.

## Architecture & Serverless Deployment
- **Web Runtime**: FastAPI + Jinja2 running on Vercel Python serverless functions.
- **Remote Chromium**: Vercel functions cannot launch local Chromium; they connect to Browserbase CDP sessions (`BROWSERBASE_API_KEY`) or a self-hosted container browser worker (`app/worker_api.py`) exposing authenticated `/internal/capture`.
- **Database**: Managed PostgreSQL (e.g., Neon connection pooling for request runtime + unpooled connection for Alembic migrations via `NEON_DATABASE_URL`). SQLite is supported for local development.
- **Object Storage**: S3-compatible bucket (AWS S3, Cloudflare R2, MinIO) for screenshot and diff image history. If not configured, text comparison operates normally while screenshot storage is gracefully omitted.
- **Background Scheduler**: GitHub Actions workflow (`.github/workflows/monitor-scheduler.yml`) calls `/internal/worker/tick` every 5 minutes with `CRON_SECRET`. Persistent daemons (`workers/scheduler_process.py` and `workers/check_worker.py`) can be run on container hosts for high-volume requirements.

## Contact & Maintainer
- Creator: Aayush Srivastava
- Email: aayush@aayushsrivastava.com
- Documentation: {base_url}/docs
- Privacy Policy: {base_url}/privacy
- Terms of Service: {base_url}/terms
- Contact: {base_url}/contact
"""
    return Response(content=content.strip(), media_type="text/plain; charset=utf-8")
