import html as html_lib
import json
import re
from typing import Optional
from fastapi import APIRouter, Request, Depends, Form, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import get_db
from app.config import settings
from app.models.user import User
from app.models.monitor import Monitor
from app.models.version import Version
from app.models.check_run import CheckRun
from app.dependencies import get_current_user, get_or_create_csrf_token, validate_csrf
from app.services.url_safety import validate_public_url
from app.services.queue_service import enqueue_check, process_check_job
from app.services.browser_capture import browser_capture_service

router = APIRouter(prefix="/monitors")
templates = Jinja2Templates(directory="app/templates")


@router.get("/new", response_class=HTMLResponse)
async def new_monitor_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "monitors/form.html", {
        "current_user": current_user,
        "csrf_token": csrf_token,
        "monitor": None,
    })


@router.post("/new")
async def create_monitor_action(
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    interval_minutes: int = Form(60),
    sensitivity: str = Form("medium"),
    keywords: str = Form(""),
    numeric_selector: str = Form(""),
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    name_clean = name.strip()[:120]
    if not name_clean:
        return templates.TemplateResponse(request, "monitors/form.html", {
            "current_user": current_user,
            "csrf_token": get_or_create_csrf_token(request),
            "monitor": None,
            "error": "Monitor name cannot be empty.",
        }, status_code=400)

    # Validate URL safety
    is_safe, canonical_url, err_code = validate_public_url(url.strip())
    if not is_safe:
        return templates.TemplateResponse(request, "monitors/form.html", {
            "current_user": current_user,
            "csrf_token": get_or_create_csrf_token(request),
            "monitor": None,
            "error": f"URL Safety Check Rejected: {canonical_url}",
        }, status_code=400)

    # Enforce interval limits 15 - 1440 minutes
    valid_intervals = [15, 30, 60, 360, 720, 1440]
    if interval_minutes not in valid_intervals and (interval_minutes < 15 or interval_minutes > 1440):
        interval_minutes = 60

    if sensitivity not in ("low", "medium", "high"):
        sensitivity = "medium"

    kw_list = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
    num_sel = numeric_selector.strip() if numeric_selector else None

    monitor = Monitor(
        user_id=current_user.id,
        name=name_clean,
        url=canonical_url,
        interval_minutes=interval_minutes,
        sensitivity=sensitivity,
        keywords_json=json.dumps(kw_list),
        numeric_selector=num_sel,
        state="active",
    )
    db.add(monitor)
    db.commit()
    db.refresh(monitor)

    # Enqueue initial baseline check
    job = enqueue_check(db, monitor.id, is_manual=True)
    if job and (settings.run_inline_checks or settings.is_vercel):
        # Vercel has no resident queue worker. Execute the initial job in this
        # request so it immediately transitions to Running/OK/Error rather than
        # remaining Pending forever. The remote-browser backend is still required
        # for a successful Chromium capture.
        await process_check_job(db, job)

    return RedirectResponse(url=f"/monitors/{monitor.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{monitor_id}", response_class=HTMLResponse)
async def monitor_detail_page(
    monitor_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted"
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    versions = db.query(Version).filter(Version.monitor_id == monitor.id).order_by(Version.created_at.desc()).all()
    check_runs = db.query(CheckRun).filter(CheckRun.monitor_id == monitor.id).order_by(CheckRun.created_at.desc()).limit(10).all()
    numeric_observations = list(reversed(monitor.numeric_observations[:30]))

    csrf_token = get_or_create_csrf_token(request)

    return templates.TemplateResponse(request, "monitors/detail.html", {
        "current_user": current_user,
        "csrf_token": csrf_token,
        "monitor": monitor,
        "versions": versions,
        "check_runs": check_runs,
        "numeric_observations": numeric_observations,
    })


@router.get("/{monitor_id}/edit", response_class=HTMLResponse)
async def edit_monitor_page(
    monitor_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted"
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "monitors/form.html", {
        "current_user": current_user,
        "csrf_token": csrf_token,
        "monitor": monitor,
    })


@router.post("/{monitor_id}/edit")
async def edit_monitor_action(
    monitor_id: str,
    request: Request,
    name: str = Form(...),
    url: str = Form(...),
    interval_minutes: int = Form(60),
    sensitivity: str = Form("medium"),
    keywords: str = Form(""),
    numeric_selector: str = Form(""),
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted"
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    is_safe, canonical_url, err_code = validate_public_url(url.strip())
    if not is_safe:
        return templates.TemplateResponse(request, "monitors/form.html", {
            "current_user": current_user,
            "csrf_token": get_or_create_csrf_token(request),
            "monitor": monitor,
            "error": f"URL Safety Check Rejected: {canonical_url}",
        }, status_code=400)

    monitor.name = name.strip()[:120]
    monitor.url = canonical_url
    monitor.interval_minutes = interval_minutes if 15 <= interval_minutes <= 1440 else 60
    monitor.sensitivity = sensitivity if sensitivity in ("low", "medium", "high") else "medium"
    monitor.keywords = [k.strip() for k in keywords.split(",") if k.strip()] if keywords else []
    monitor.numeric_selector = numeric_selector.strip() if numeric_selector else None
    db.commit()

    return RedirectResponse(url=f"/monitors/{monitor.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{monitor_id}/check-now")
async def check_now_action(
    monitor_id: str,
    request: Request,
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    monitor = db.query(Monitor).filter(
        Monitor.id == monitor_id,
        Monitor.user_id == current_user.id,
        Monitor.state != "deleted"
    ).first()

    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    job = enqueue_check(db, monitor.id, is_manual=True)
    if job and (settings.run_inline_checks or settings.is_vercel):
        await process_check_job(db, job)

    return RedirectResponse(url=f"/monitors/{monitor.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{monitor_id}/pause")
async def pause_monitor_action(
    monitor_id: str,
    request: Request,
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == current_user.id).first()
    if monitor:
        monitor.state = "paused"
        db.commit()

    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{monitor_id}/resume")
async def resume_monitor_action(
    monitor_id: str,
    request: Request,
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == current_user.id).first()
    if monitor:
        monitor.state = "active"
        db.commit()

    return RedirectResponse(url=f"/monitors/{monitor_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/{monitor_id}/delete")
async def delete_monitor_action(
    monitor_id: str,
    request: Request,
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == current_user.id).first()
    if monitor:
        db.delete(monitor)
        db.commit()

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{monitor_id}/regions", response_class=HTMLResponse)
async def regions_page(
    monitor_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == current_user.id).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "monitors/regions.html", {
        "current_user": current_user,
        "csrf_token": csrf_token,
        "monitor": monitor,
    })


@router.post("/{monitor_id}/regions")
async def save_regions_action(
    monitor_id: str,
    request: Request,
    include_selectors: str = Form("[]"),
    ignore_selectors: str = Form("[]"),
    csrf_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        raise HTTPException(status_code=400, detail="Invalid security token")

    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == current_user.id).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    try:
        inc = json.loads(include_selectors)
        monitor.include_selectors = inc if isinstance(inc, list) else []
    except Exception:
        pass

    try:
        ign = json.loads(ignore_selectors)
        monitor.ignore_selectors = ign if isinstance(ign, list) else []
    except Exception:
        pass

    db.commit()
    return RedirectResponse(url=f"/monitors/{monitor.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{monitor_id}/preview-dom")
async def preview_dom_endpoint(
    monitor_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Renders a sanitized DOM snapshot with an injected client inspector script
    specifically for the sandboxed region picker iframe.
    """
    monitor = db.query(Monitor).filter(Monitor.id == monitor_id, Monitor.user_id == current_user.id).first()
    if not monitor:
        raise HTTPException(status_code=404, detail="Monitor not found")

    # Vercel functions do not ship Chromium. browser_capture_service forwards
    # this request to the configured authenticated worker; local development can
    # continue to launch Chromium directly.
    capture = await browser_capture_service.capture_page(
        url=monitor.url,
        capture_dom=True,
    )

    if not capture.success:
        if capture.failure_code == "BROWSER_WORKER_UNCONFIGURED":
            error_status = 503
            error_message = (
                "Remote Chromium is not configured for this deployment. "
                "Install Browserbase and set BROWSERBASE_API_KEY plus BROWSERBASE_PROJECT_ID, "
                "or configure BROWSER_WORKER_URL plus BROWSER_WORKER_TOKEN in Vercel."
            )
        else:
            error_status = 502
            error_message = capture.error_message or capture.failure_code or "Unknown capture error"
        safe_error = html_lib.escape(error_message)
        return HTMLResponse(
            "<html><body style='font-family:sans-serif;padding:2rem;color:#e11d48;background:#fff1f2;'>"
            "<h3>Unable to load preview</h3>"
            f"<p>{safe_error}</p>"
            "</body></html>",
            status_code=error_status,
        )

    html = capture.dom_html or "<html><body>Empty page</body></html>"

    # Sanitize HTML: Strip dangerous scripts, event handlers, and active tags
    html = re.sub(r"<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<meta http-equiv=[\"']?refresh[\"']?[^>]*>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"\bon[a-z]+\s*=\s*[\"'][^\"']*[\"']", "", html, flags=re.IGNORECASE)

    # Injected Inspector Styles & Script
    injected_inspector = """
    <style id="cw-inspector-style">
      .__cw-hovered {
        outline: 3px solid #2563eb !important;
        outline-offset: -1px !important;
        cursor: crosshair !important;
        background-color: rgba(37, 99, 235, 0.08) !important;
      }
      #__cw-tooltip {
        position: fixed;
        z-index: 2147483647;
        background: #0f172a;
        color: #f8fafc;
        font-family: monospace;
        font-size: 11px;
        padding: 4px 8px;
        border-radius: 4px;
        pointer-events: none;
        display: none;
        box-shadow: 0 4px 6px rgba(0,0,0,0.3);
      }
    </style>
    <div id="__cw-tooltip"></div>
    <script>
      (function() {
        const tooltip = document.getElementById('__cw-tooltip');
        let currentTarget = null;

        function getOptimalSelector(el) {
          if (!el || el === document.body || el === document.documentElement) return 'body';
          if (el.id && !el.id.match(/^__cw/)) return '#' + CSS.escape(el.id);

          const tag = el.tagName.toLowerCase();
          const classes = Array.from(el.classList).filter(c => !c.startsWith('__cw')).map(c => '.' + CSS.escape(c)).slice(0, 2).join('');
          if (classes) {
            const candidate = tag + classes;
            if (document.querySelectorAll(candidate).length === 1) return candidate;
          }

          if (el.parentElement) {
            const siblings = Array.from(el.parentElement.children).filter(c => c.tagName === el.tagName);
            if (siblings.length > 1) {
              const idx = siblings.indexOf(el) + 1;
              return getOptimalSelector(el.parentElement) + ' > ' + tag + ':nth-of-type(' + idx + ')';
            }
            return getOptimalSelector(el.parentElement) + ' > ' + tag;
          }
          return tag;
        }

        document.addEventListener('mouseover', function(e) {
          if (currentTarget) currentTarget.classList.remove('__cw-hovered');
          if (e.target && e.target !== document.body && e.target !== document.documentElement && !e.target.id?.startsWith('__cw')) {
            currentTarget = e.target;
            currentTarget.classList.add('__cw-hovered');
            const sel = getOptimalSelector(currentTarget);
            tooltip.innerText = sel;
            tooltip.style.display = 'block';
            tooltip.style.left = (e.clientX + 10) + 'px';
            tooltip.style.top = (e.clientY + 10) + 'px';
          }
        }, true);

        document.addEventListener('mousemove', function(e) {
          if (tooltip.style.display === 'block') {
            tooltip.style.left = (e.clientX + 10) + 'px';
            tooltip.style.top = (e.clientY + 10) + 'px';
          }
        }, true);

        document.addEventListener('mouseout', function(e) {
          if (currentTarget) {
            currentTarget.classList.remove('__cw-hovered');
            currentTarget = null;
          }
          tooltip.style.display = 'none';
        }, true);

        document.addEventListener('click', function(e) {
          e.preventDefault();
          e.stopPropagation();
          if (currentTarget) {
            const sel = getOptimalSelector(currentTarget);
            window.parent.postMessage({ type: 'REGION_SELECTED', selector: sel }, '*');
          }
        }, true);
      })();
    </script>
    """

    if "</body>" in html:
        html = html.replace("</body>", f"{injected_inspector}</body>")
    else:
        html += injected_inspector

    return HTMLResponse(
        content=html,
        headers={
            "Content-Security-Policy": "default-src 'self' 'unsafe-inline' data: blob: https:; script-src 'unsafe-inline';",
            "X-Frame-Options": "SAMEORIGIN",
        }
    )
