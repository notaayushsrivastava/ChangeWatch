from typing import Optional
from fastapi import Request, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.user import User
from app.services.security import verify_session_token, generate_csrf_token, verify_csrf_token


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    session_token = request.cookies.get("cw_session")
    if not session_token:
        return None
    user_id = verify_session_token(session_token)
    if not user_id:
        return None
    return db.query(User).filter(User.id == user_id, User.is_active == True).first()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = get_current_user_optional(request, db)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/login"},
            detail="Authentication required"
        )
    return user


def get_or_create_csrf_token(request: Request) -> str:
    session_id = request.cookies.get("cw_session") or "anon-session"
    return generate_csrf_token(session_id)


def validate_csrf(request: Request, csrf_token: str) -> bool:
    session_id = request.cookies.get("cw_session") or "anon-session"
    return verify_csrf_token(csrf_token, session_id)


def get_current_mcp_user(request: Request, db: Session = Depends(get_db)) -> User:
    """
    Authenticate an MCP tool request via OAuth Bearer token or session.
    Raises 401 with WWW-Authenticate header to trigger client OAuth flow if unauthenticated.
    """
    from app.services.oauth import verify_access_token

    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    user_id = None

    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        user_id = verify_access_token(token)
        # Fallback: check if the bearer token is a session token
        if not user_id:
            user_id = verify_session_token(token)

    # Secondary fallback to session cookie if called in-browser
    if not user_id:
        session_token = request.cookies.get("cw_session")
        if session_token:
            user_id = verify_session_token(session_token)

    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a valid OAuth Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account is inactive.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
