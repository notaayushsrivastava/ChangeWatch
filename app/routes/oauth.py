import urllib.parse
from typing import Optional
from fastapi import APIRouter, Request, Depends, HTTPException, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.dependencies import get_current_user_optional
from app.services.oauth import (
    create_oauth_code,
    verify_oauth_code,
    create_access_token,
    verify_pkce,
    register_oauth_client,
    get_oauth_client,
    OAUTH_TOKEN_MAX_AGE_SECONDS,
)

router = APIRouter(tags=["oauth"])
templates = Jinja2Templates(directory="app/templates")


def _get_base_url(request: Request) -> str:
    """Derive public base URL from settings or incoming request."""
    if settings.is_production or (settings.APP_BASE_URL and "changewatch.aayushsrivastava.com" in settings.APP_BASE_URL):
        return "https://changewatch.aayushsrivastava.com"
    if settings.APP_BASE_URL and settings.APP_BASE_URL.startswith("http"):
        return settings.APP_BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
async def oauth_metadata(request: Request):
    """RFC 8414 OAuth 2.0 Authorization Server Metadata."""
    base_url = _get_base_url(request)
    return {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/oauth/authorize",
        "token_endpoint": f"{base_url}/oauth/token",
        "registration_endpoint": f"{base_url}/oauth/register",
        "scopes_supported": ["openid", "profile", "email", "monitors"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256", "plain"],
    }


@router.post("/oauth/register", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def oauth_register_endpoint(request: Request):
    """
    RFC 7591 OAuth 2.0 Dynamic Client Registration endpoint for MCP clients
    (e.g. npx mcp-remote, Claude Desktop, Cursor).
    """
    data = {}
    try:
        data = await request.json()
    except Exception:
        pass

    client_name = data.get("client_name")
    redirect_uris = data.get("redirect_uris") or []
    grant_types = data.get("grant_types") or ["authorization_code"]
    token_endpoint_auth_method = data.get("token_endpoint_auth_method") or "none"

    client_record = register_oauth_client(
        client_name=client_name,
        redirect_uris=redirect_uris,
        grant_types=grant_types,
        token_endpoint_auth_method=token_endpoint_auth_method,
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=client_record,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


@router.get("/oauth/authorize", response_class=HTMLResponse, include_in_schema=False)
async def oauth_authorize_page(
    request: Request,
    client_id: Optional[str] = None,
    redirect_uri: Optional[str] = None,
    response_type: Optional[str] = "code",
    state: Optional[str] = None,
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = "S256",
    scope: Optional[str] = "monitors",
    db: Session = Depends(get_db),
):
    """Render OAuth authorization consent dialog or redirect to login if unauthenticated."""
    user = get_current_user_optional(request, db)
    if not user:
        # Prompt login, preserving full authorize URL to return to
        original_query = str(request.url.query)
        next_url = f"/oauth/authorize?{original_query}" if original_query else "/oauth/authorize"
        encoded_next = urllib.parse.quote(next_url)
        return RedirectResponse(url=f"/auth/login?next={encoded_next}", status_code=status.HTTP_303_SEE_OTHER)

    client_info = get_oauth_client(client_id) if client_id else None
    client_name = client_info.get("client_name") if client_info else (client_id or "mcp-client")

    return templates.TemplateResponse(request, "oauth_authorize.html", {
        "current_user": user,
        "client_id": client_id or "mcp-client",
        "client_name": client_name,
        "redirect_uri": redirect_uri or "",
        "state": state or "",
        "code_challenge": code_challenge or "",
        "code_challenge_method": code_challenge_method or "S256",
        "scope": scope or "monitors",
    })


@router.post("/oauth/authorize", include_in_schema=False)
async def oauth_authorize_submit(
    request: Request,
    action: str = Form(...),
    client_id: Optional[str] = Form("mcp-client"),
    redirect_uri: Optional[str] = Form(None),
    state: Optional[str] = Form(None),
    code_challenge: Optional[str] = Form(None),
    code_challenge_method: Optional[str] = Form("S256"),
    scope: Optional[str] = Form("monitors"),
    db: Session = Depends(get_db),
):
    """Process user consent approval or denial."""
    user = get_current_user_optional(request, db)
    if not user:
        return RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)

    # Validate target redirect_uri or fallback to client display
    clean_redirect = redirect_uri.strip() if redirect_uri else ""
    if not clean_redirect:
        clean_redirect = "/settings"

    url_parts = urllib.parse.urlparse(clean_redirect)
    query_params = urllib.parse.parse_qs(url_parts.query)

    if action == "approve":
        code = create_oauth_code(
            user_id=user.id,
            client_id=client_id or "mcp-client",
            redirect_uri=clean_redirect,
            code_challenge=code_challenge,
            code_challenge_method=code_challenge_method,
            scopes=scope,
        )
        query_params["code"] = [code]
        if state:
            query_params["state"] = [state]
    else:
        query_params["error"] = ["access_denied"]
        query_params["error_description"] = ["User denied authorization request"]
        if state:
            query_params["state"] = [state]

    new_query = urllib.parse.urlencode(query_params, doseq=True)
    target_url = urllib.parse.urlunparse((
        url_parts.scheme,
        url_parts.netloc,
        url_parts.path,
        url_parts.params,
        new_query,
        url_parts.fragment,
    ))

    return RedirectResponse(url=target_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/oauth/token", include_in_schema=False)
async def oauth_token_endpoint(request: Request):
    """
    Exchange authorization code for an OAuth 2.0 Bearer access token.
    Supports both application/x-www-form-urlencoded and application/json.
    """
    content_type = request.headers.get("content-type", "").lower()
    data = {}
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            data = {}
    else:
        form = await request.form()
        data = dict(form)

    # Support HTTP Basic authentication for client credentials
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Basic "):
        try:
            import base64
            encoded = auth_header.split(" ", 1)[1]
            decoded = base64.b64decode(encoded).decode("utf-8")
            if ":" in decoded:
                b_client_id, b_client_secret = decoded.split(":", 1)
                if not data.get("client_id"):
                    data["client_id"] = b_client_id
                if not data.get("client_secret"):
                    data["client_secret"] = b_client_secret
        except Exception:
            pass

    grant_type = data.get("grant_type", "")
    code = data.get("code", "")
    code_verifier = data.get("code_verifier", "")
    client_id = data.get("client_id", "mcp-client")

    if grant_type != "authorization_code":
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "unsupported_grant_type",
                "error_description": "Only grant_type=authorization_code is supported.",
            },
        )

    if not code:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "invalid_request",
                "error_description": "Missing authorization code.",
            },
        )

    payload = verify_oauth_code(code)
    if not payload:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "invalid_grant",
                "error_description": "Authorization code is invalid or expired.",
            },
        )

    # Validate PKCE if challenge was set
    expected_challenge = payload.get("code_challenge", "")
    challenge_method = payload.get("code_challenge_method", "S256")
    if expected_challenge:
        if not verify_pkce(code_verifier, expected_challenge, method=challenge_method):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "error": "invalid_grant",
                    "error_description": "PKCE code_verifier verification failed.",
                },
            )

    user_id = payload.get("user_id")
    access_token = create_access_token(
        user_id=user_id,
        client_id=client_id or payload.get("client_id", "mcp-client"),
        scopes=payload.get("scopes", "monitors"),
    )

    return JSONResponse(
        content={
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": OAUTH_TOKEN_MAX_AGE_SECONDS,
            "scope": payload.get("scopes", "monitors"),
        },
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )
