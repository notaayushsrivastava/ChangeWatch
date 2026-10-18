import re
from urllib.parse import urlparse

from sqlalchemy.exc import OperationalError


def csrf_from(response) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', response.text)
    assert match, "expected the auth form to include its CSRF token"
    return match.group(1)


def test_signup_then_signin(client):
    email = "auth-flow-test@example.invalid"
    password = "Safe-test-password-2026"

    signup_page = client.get("/auth/signup")
    assert signup_page.status_code == 200
    signup = client.post(
        "/auth/signup",
        data={
            "csrf_token": csrf_from(signup_page),
            "email": email,
            "password": password,
            "timezone": "Asia/Kolkata",
        },
        follow_redirects=False,
    )
    assert signup.status_code == 303
    assert urlparse(signup.headers["location"]).path == "/dashboard"
    assert "cw_session=" in signup.headers.get("set-cookie", "")

    logout = client.post("/auth/logout", follow_redirects=False)
    assert logout.status_code == 303

    login_page = client.get("/auth/login")
    assert login_page.status_code == 200
    login = client.post(
        "/auth/login",
        data={
            "csrf_token": csrf_from(login_page),
            "email": email,
            "password": password,
        },
        follow_redirects=False,
    )
    assert login.status_code == 303
    assert urlparse(login.headers["location"]).path == "/dashboard"
    assert "cw_session=" in login.headers.get("set-cookie", "")


def test_signup_shows_validation_error_for_overlong_bcrypt_password(client):
    signup_page = client.get("/auth/signup")
    response = client.post(
        "/auth/signup",
        data={
            "csrf_token": csrf_from(signup_page),
            "email": "long-password@example.invalid",
            "password": "x" * 73,
            "timezone": "UTC",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Password must be no more than 72 UTF-8 bytes long." in response.text


def test_signup_shows_duplicate_email_error(client):
    email = "duplicate-signup@example.invalid"
    first_page = client.get("/auth/signup")
    first = client.post(
        "/auth/signup",
        data={
            "csrf_token": csrf_from(first_page),
            "email": email,
            "password": "Safe-test-password-2026",
            "timezone": "UTC",
        },
        follow_redirects=False,
    )
    assert first.status_code == 303

    second_page = client.get("/auth/signup")
    second = client.post(
        "/auth/signup",
        data={
            "csrf_token": csrf_from(second_page),
            "email": email,
            "password": "Another-safe-password-2026",
            "timezone": "UTC",
        },
        follow_redirects=False,
    )
    assert second.status_code == 400
    assert "An account with that email already exists." in second.text


def test_signup_database_failure_is_safe_and_visible(client, db_session, monkeypatch):
    def fail_query(*args, **kwargs):
        raise OperationalError("SELECT users", {}, Exception("database unavailable"))

    monkeypatch.setattr(db_session, "query", fail_query)
    signup_page = client.get("/auth/signup")
    response = client.post(
        "/auth/signup",
        data={
            "csrf_token": csrf_from(signup_page),
            "email": "database-failure@example.invalid",
            "password": "Safe-test-password-2026",
            "timezone": "UTC",
        },
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert "Account creation is temporarily unavailable." in response.text
    assert "database unavailable" not in response.text


def test_login_with_next_forward_to_oauth_flow(client, db_session):
    """Verify that next parameter is preserved, MCP UI is rendered, and login redirects to oauth authorize."""
    # 1. Register a test user
    email = "mcp-forward-test@example.invalid"
    password = "Safe-password-2026!"
    signup_page = client.get("/auth/signup")
    client.post(
        "/auth/signup",
        data={
            "csrf_token": csrf_from(signup_page),
            "email": email,
            "password": password,
            "timezone": "UTC",
        },
    )
    # Log out
    client.post("/auth/logout")

    # 2. Hit login with next pointing to oauth authorize
    import urllib.parse
    oauth_next = "/oauth/authorize?response_type=code&client_id=cline-test&redirect_uri=http%3A%2F%2F127.0.0.1%3A9999%2Fcallback&state=xyz123"
    login_page = client.get(f"/auth/login?next={urllib.parse.quote(oauth_next)}")
    assert login_page.status_code == 200
    assert "MCP OAuth Authorization" in login_page.text
    assert "Connect" in login_page.text
    assert "cline-test" in login_page.text

    # 3. Post login with next
    login_resp = client.post(
        "/auth/login",
        data={
            "csrf_token": csrf_from(login_page),
            "email": email,
            "password": password,
            "next": oauth_next,
        },
        follow_redirects=False,
    )
    assert login_resp.status_code == 303
    assert login_resp.headers["location"] == oauth_next


def test_login_with_unsafe_next_falls_back_to_dashboard(client):
    """External or scheme-relative next URLs must fall back to /dashboard to prevent open redirects."""
    email = "open-redirect-test@example.invalid"
    password = "Safe-password-2026!"
    signup_page = client.get("/auth/signup")
    client.post(
        "/auth/signup",
        data={
            "csrf_token": csrf_from(signup_page),
            "email": email,
            "password": password,
            "timezone": "UTC",
        },
    )
    client.post("/auth/logout")

    login_page = client.get("/auth/login?next=https://malicious.example.com/steal")
    login_resp = client.post(
        "/auth/login",
        data={
            "csrf_token": csrf_from(login_page),
            "email": email,
            "password": password,
            "next": "https://malicious.example.com/steal",
        },
        follow_redirects=False,
    )
    assert login_resp.status_code == 303
    assert login_resp.headers["location"] == "/dashboard"


def test_authenticated_user_accessing_login_with_next_immediately_redirects(client):
    """An already authenticated user visiting /auth/login?next=... is forwarded to next immediately."""
    email = "already-auth@example.invalid"
    password = "Safe-password-2026!"
    signup_page = client.get("/auth/signup")
    client.post(
        "/auth/signup",
        data={
            "csrf_token": csrf_from(signup_page),
            "email": email,
            "password": password,
            "timezone": "UTC",
        },
    )

    oauth_target = "/oauth/authorize?client_id=cursor-app"
    resp = client.get(f"/auth/login?next={oauth_target}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == oauth_target

