from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.user import User
from app.services.security import hash_password, verify_password, create_session_token
from app.dependencies import get_current_user_optional, get_or_create_csrf_token, validate_csrf

router = APIRouter(prefix="/auth")
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "auth/login.html", {
        "current_user": None,
        "csrf_token": csrf_token,
    })


@router.post("/login")
async def login_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        return templates.TemplateResponse(request, "auth/login.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "error": "Invalid or expired session security token. Please try again.",
        }, status_code=400)

    email_clean = email.strip().lower()
    user = db.query(User).filter(User.email == email_clean).first()

    if not user or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "auth/login.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "error": "Invalid email address or password.",
        }, status_code=401)

    session_token = create_session_token(user.id)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="cw_session",
        value=session_token,
        httponly=True,
        max_age=86400 * 14,
        samesite="lax",
    )
    return response


@router.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user_optional(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)

    csrf_token = get_or_create_csrf_token(request)
    return templates.TemplateResponse(request, "auth/signup.html", {
        "current_user": None,
        "csrf_token": csrf_token,
    })


@router.post("/signup")
async def signup_action(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    timezone: str = Form("UTC"),
    csrf_token: str = Form(...),
    db: Session = Depends(get_db),
):
    if not validate_csrf(request, csrf_token):
        return templates.TemplateResponse(request, "auth/signup.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "error": "Invalid security token. Please try again.",
        }, status_code=400)

    email_clean = email.strip().lower()
    if "@" not in email_clean or len(email_clean) < 5:
        return templates.TemplateResponse(request, "auth/signup.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "error": "Please provide a valid email address.",
        }, status_code=400)

    if len(password) < 8:
        return templates.TemplateResponse(request, "auth/signup.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "error": "Password must be at least 8 characters long.",
        }, status_code=400)

    existing = db.query(User).filter(User.email == email_clean).first()
    if existing:
        return templates.TemplateResponse(request, "auth/signup.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "error": "An account with that email already exists.",
        }, status_code=400)

    new_user = User(
        email=email_clean,
        password_hash=hash_password(password),
        timezone=timezone or "UTC",
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    session_token = create_session_token(new_user.id)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="cw_session",
        value=session_token,
        httponly=True,
        max_age=86400 * 14,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout_action():
    response = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("cw_session")
    return response
