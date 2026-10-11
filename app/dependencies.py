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
