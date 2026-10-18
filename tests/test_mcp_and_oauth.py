import base64
import hashlib
import json
import pytest
from starlette.testclient import TestClient
from app.main import app, mcp
from app.db import SessionLocal
from app.models.user import User
from app.models.monitor import Monitor
from app.models.version import Version
from app.services.security import hash_password, create_session_token
from app.services.oauth import create_access_token


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def test_user(db_session):
    user = db_session.query(User).filter(User.email == "mcp_tester@example.com").first()
    if not user:
        user = User(
            email="mcp_tester@example.com",
            password_hash=hash_password("McpPassword123!"),
            is_active=True,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    return user


@pytest.fixture
def auth_client(test_user):
    client = TestClient(app)
    session_token = create_session_token(test_user.id)
    client.cookies.set("cw_session", session_token)
    return client


@pytest.fixture
def bearer_client(test_user):
    client = TestClient(app)
    token = create_access_token(user_id=test_user.id)
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def test_mcp_tools_registered():
    """Verify that FastApiMCP successfully discovered all 9 API endpoints as tools."""
    tool_names = [t.name for t in mcp.tools]
    assert "list_monitors" in tool_names
    assert "create_monitor" in tool_names
    assert "get_monitor" in tool_names
    assert "update_monitor" in tool_names
    assert "delete_monitor" in tool_names
    assert "pause_monitor" in tool_names
    assert "resume_monitor" in tool_names
    assert "trigger_check" in tool_names
    assert "get_diff" in tool_names


def test_oauth_metadata_discovery():
    """Verify RFC 8414 OAuth 2.0 authorization server metadata discovery endpoint."""
    client = TestClient(app)
    response = client.get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    data = response.json()
    assert "issuer" in data
    assert "authorization_endpoint" in data
    assert "token_endpoint" in data
    assert "authorization_code" in data["grant_types_supported"]
    assert "S256" in data["code_challenge_methods_supported"]


def test_oauth_authorize_unauthenticated_redirects_to_login():
    """Unauthenticated users visiting /oauth/authorize are redirected to login with next url preserved."""
    client = TestClient(app)
    response = client.get(
        "/oauth/authorize?client_id=claude-desktop&redirect_uri=http://localhost:9000/callback&state=xyz123",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/auth/login?next=" in response.headers["location"]


def test_oauth_authorize_consent_page(auth_client, test_user):
    """Authenticated user visiting /oauth/authorize sees the consent UI dialog."""
    response = auth_client.get(
        "/oauth/authorize?client_id=claude-desktop&redirect_uri=http://localhost:9000/callback&state=xyz123"
    )
    assert response.status_code == 200
    assert "Authorize AI Agent Access" in response.text
    assert test_user.email in response.text
    assert "claude-desktop" in response.text


def test_oauth_authorization_and_token_exchange(auth_client, test_user):
    """Complete authorization code grant flow with PKCE S256 verification."""
    # 1. Generate PKCE verifier and S256 challenge
    code_verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    # 2. User approves consent
    response = auth_client.post(
        "/oauth/authorize",
        data={
            "action": "approve",
            "client_id": "cursor-agent",
            "redirect_uri": "http://localhost:9000/callback",
            "state": "state_abc",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": "monitors",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "http://localhost:9000/callback" in location
    assert "code=" in location
    assert "state=state_abc" in location

    # Extract code from query string
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(location).query)
    auth_code = qs["code"][0]

    # 3. Exchange code for access token with valid PKCE verifier
    client = TestClient(app)
    token_resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "code_verifier": code_verifier,
            "client_id": "cursor-agent",
        },
    )
    assert token_resp.status_code == 200
    token_data = token_resp.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "Bearer"
    assert token_data["expires_in"] > 0

    # 4. Use the issued Bearer access token on an MCP API endpoint
    mcp_resp = client.get(
        "/api/monitors",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )
    assert mcp_resp.status_code == 200
    assert isinstance(mcp_resp.json(), list)


def test_oauth_token_exchange_invalid_pkce(auth_client):
    """Token exchange fails when wrong PKCE code_verifier is presented."""
    code_verifier = "correct-secret-code-verifier-string"
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    response = auth_client.post(
        "/oauth/authorize",
        data={
            "action": "approve",
            "client_id": "mcp-test",
            "redirect_uri": "http://localhost:9000/callback",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    from urllib.parse import urlparse, parse_qs
    auth_code = parse_qs(urlparse(response.headers["location"]).query)["code"][0]

    client = TestClient(app)
    token_resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "code_verifier": "wrong-verifier",
            "client_id": "mcp-test",
        },
    )
    assert token_resp.status_code == 400
    assert token_resp.json()["error"] == "invalid_grant"


def test_oauth_user_denial(auth_client):
    """User clicking Deny sends error=access_denied back to client redirect_uri."""
    response = auth_client.post(
        "/oauth/authorize",
        data={
            "action": "deny",
            "client_id": "untrusted-agent",
            "redirect_uri": "http://localhost:9000/callback",
            "state": "deny_state",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "error=access_denied" in location
    assert "state=deny_state" in location


def test_mcp_api_unauthorized_returns_401_with_www_authenticate():
    """Unauthenticated MCP requests get 401 with WWW-Authenticate header to trigger client OAuth flow."""
    client = TestClient(app)
    response = client.get("/api/monitors")
    assert response.status_code == 401
    assert "Bearer" in response.headers.get("WWW-Authenticate", "")


def test_mcp_api_full_management_lifecycle(bearer_client, db_session, test_user):
    """Test full CRUD, pause, resume, check trigger, and diff endpoints via Bearer token."""
    # 1. Create a monitor
    create_resp = bearer_client.post(
        "/api/monitors",
        json={
            "name": "MCP Lifecycle Test Monitor",
            "url": "https://example.com/pricing",
            "interval_minutes": 30,
            "sensitivity": "high",
            "include_selectors": [".pricing-tier"],
            "keywords": ["pro", "enterprise"],
        },
    )
    assert create_resp.status_code == 201
    mon = create_resp.json()
    monitor_id = mon["id"]
    assert mon["name"] == "MCP Lifecycle Test Monitor"
    assert mon["interval_minutes"] == 30

    # 2. List monitors
    list_resp = bearer_client.get("/api/monitors")
    assert list_resp.status_code == 200
    ids = [m["id"] for m in list_resp.json()]
    assert monitor_id in ids

    # 3. Get monitor detail
    detail_resp = bearer_client.get(f"/api/monitors/{monitor_id}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["url"] == "https://example.com/pricing"

    # 4. Update monitor
    update_resp = bearer_client.patch(
        f"/api/monitors/{monitor_id}",
        json={"name": "Updated Monitor Name", "interval_minutes": 120},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Updated Monitor Name"
    assert update_resp.json()["interval_minutes"] == 120

    # 5. Pause monitor
    pause_resp = bearer_client.post(f"/api/monitors/{monitor_id}/pause")
    assert pause_resp.status_code == 200
    assert pause_resp.json()["state"] == "paused"
    assert pause_resp.json()["is_active"] is False

    # 6. Resume monitor
    resume_resp = bearer_client.post(f"/api/monitors/{monitor_id}/resume")
    assert resume_resp.status_code == 200
    assert resume_resp.json()["state"] == "active"
    assert resume_resp.json()["is_active"] is True

    # 7. Trigger check
    check_resp = bearer_client.post(f"/api/monitors/{monitor_id}/check")
    assert check_resp.status_code == 200
    assert check_resp.json()["status"] == "enqueued"

    # 8. Seed two mock versions to test diff endpoint
    v1 = Version(
        monitor_id=monitor_id,
        version_number=1,
        content_hash="hash1",
        normalized_text="Pricing tier: $10 / month",
        reason="baseline",
    )
    v2 = Version(
        monitor_id=monitor_id,
        version_number=2,
        content_hash="hash2",
        normalized_text="Pricing tier: $15 / month",
        reason="content_changed",
    )
    db_session.add_all([v1, v2])
    db_session.commit()

    diff_resp = bearer_client.get(f"/api/monitors/{monitor_id}/diff")
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()
    assert diff_data["to_version_number"] == 2
    assert len(diff_data["diff_lines_preview"]) > 0

    # 9. Delete monitor
    del_resp = bearer_client.delete(f"/api/monitors/{monitor_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "ok"


def test_settings_page_renders_mcp_section(auth_client):
    """Verify that user settings displays the AI & MCP Server integration card."""
    response = auth_client.get("/settings/notifications")
    assert response.status_code == 200
    assert "AI Agent & MCP Integration" in response.text
    assert "/mcp" in response.text
    assert "/sse" in response.text
    assert "Personal Access Bearer Token" in response.text


def test_dynamic_client_registration_flow(auth_client, test_user):
    """Verify RFC 7591 dynamic client registration and its integration with OAuth consent."""
    client = TestClient(app)

    # 1. Discover registration endpoint from OAuth metadata
    meta_resp = client.get("/.well-known/oauth-authorization-server")
    assert meta_resp.status_code == 200
    meta = meta_resp.json()
    assert "registration_endpoint" in meta
    assert "/oauth/register" in meta["registration_endpoint"]

    # 2. Dynamically register a new MCP client (e.g. Claude Desktop or Cursor)
    reg_payload = {
        "client_name": "Claude Desktop AI Assistant",
        "redirect_uris": ["http://127.0.0.1:9099/callback"],
        "grant_types": ["authorization_code"],
        "token_endpoint_auth_method": "none",
    }
    reg_resp = client.post("/oauth/register", json=reg_payload)
    assert reg_resp.status_code == 201
    reg_data = reg_resp.json()
    assert "client_id" in reg_data
    assert reg_data["client_name"] == "Claude Desktop AI Assistant"
    assert "http://127.0.0.1:9099/callback" in reg_data["redirect_uris"]
    assert isinstance(reg_data.get("client_secret"), str) and len(reg_data["client_secret"]) > 0
    assert reg_data.get("client_secret_expires_at") == 0
    dyn_client_id = reg_data["client_id"]

    # 3. Request authorization consent using the dynamic client_id
    auth_page_resp = auth_client.get(
        f"/oauth/authorize?client_id={dyn_client_id}&redirect_uri=http://127.0.0.1:9099/callback&state=dyn_state"
    )
    assert auth_page_resp.status_code == 200
    # Must display the registered application name
    assert "Claude Desktop AI Assistant" in auth_page_resp.text
    assert dyn_client_id in auth_page_resp.text

    # 4. Approve authorization
    approve_resp = auth_client.post(
        "/oauth/authorize",
        data={
            "action": "approve",
            "client_id": dyn_client_id,
            "redirect_uri": "http://127.0.0.1:9099/callback",
            "state": "dyn_state",
        },
        follow_redirects=False,
    )
    assert approve_resp.status_code == 303
    from urllib.parse import urlparse, parse_qs
    code = parse_qs(urlparse(approve_resp.headers["location"]).query)["code"][0]

    # 5. Exchange code for access token
    token_resp = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": dyn_client_id,
        },
    )
    assert token_resp.status_code == 200
    token_data = token_resp.json()
    assert "access_token" in token_data

    # 6. Verify token works on MCP tool endpoint
    tool_resp = client.get(
        "/api/monitors",
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
    )
    assert tool_resp.status_code == 200

