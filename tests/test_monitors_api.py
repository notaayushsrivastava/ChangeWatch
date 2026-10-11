import pytest
from app.models.user import User
from app.models.monitor import Monitor
from app.services.security import hash_password, create_session_token, generate_csrf_token


def test_auth_and_monitor_isolation(client, db_session):
    # 1. Create two users
    user_a = User(email="user_a@example.com", password_hash=hash_password("password123"))
    user_b = User(email="user_b@example.com", password_hash=hash_password("password123"))
    db_session.add(user_a)
    db_session.add(user_b)
    db_session.commit()

    # 2. Authenticate as User A
    session_token_a = create_session_token(user_a.id)
    client.cookies.set("cw_session", session_token_a)

    # 3. Create a monitor for User A
    monitor_a = Monitor(
        user_id=user_a.id,
        name="User A Monitor",
        url="https://example.com/test-a",
        interval_minutes=60,
        sensitivity="medium"
    )
    db_session.add(monitor_a)
    db_session.commit()

    # User A accesses their dashboard
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "User A Monitor" in resp.text

    # User A accesses their monitor detail
    resp = client.get(f"/monitors/{monitor_a.id}")
    assert resp.status_code == 200
    assert "User A Monitor" in resp.text

    # 4. Authenticate as User B
    session_token_b = create_session_token(user_b.id)
    client.cookies.set("cw_session", session_token_b)

    # User B's dashboard must NOT show User A's monitor
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "User A Monitor" not in resp.text

    # User B attempting to view User A's monitor directly must be rejected with 404
    resp = client.get(f"/monitors/{monitor_a.id}")
    assert resp.status_code == 404


def test_pause_and_resume_monitor(client, db_session):
    user = User(email="tester@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.commit()

    session_token = create_session_token(user.id)
    client.cookies.set("cw_session", session_token)
    csrf_token = generate_csrf_token(session_token)

    monitor = Monitor(
        user_id=user.id,
        name="Test Pausing",
        url="https://example.com/pause",
        interval_minutes=60,
        state="active"
    )
    db_session.add(monitor)
    db_session.commit()

    # Pause monitor
    resp = client.post(f"/monitors/{monitor.id}/pause", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(monitor)
    assert monitor.state == "paused"

    # Resume monitor
    resp = client.post(f"/monitors/{monitor.id}/resume", data={"csrf_token": csrf_token}, follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(monitor)
    assert monitor.state == "active"


def test_landing_page_renders_for_guests_and_users(client, db_session):
    # Unauthenticated visitor
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ChangeWatch" in resp.text
    assert "Catch Silent Web Changes" in resp.text
    assert "Sign In" in resp.text
    assert "Get Started" in resp.text

    # Authenticated user
    user = User(email="landing_user@example.com", password_hash=hash_password("password123"))
    db_session.add(user)
    db_session.commit()
    token = create_session_token(user.id)
    client.cookies.set("cw_session", token)

    resp_auth = client.get("/")
    assert resp_auth.status_code == 200
    assert "Dashboard" in resp_auth.text
