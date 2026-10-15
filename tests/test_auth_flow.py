import re
from urllib.parse import urlparse


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
