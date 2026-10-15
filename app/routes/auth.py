import logging

from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from app.db import get_db
from app.models.user import User
from app.services.security import hash_password, verify_password, create_session_token
from app.dependencies import get_current_user_optional, get_or_create_csrf_token, validate_csrf

logger = logging.getLogger(__name__)

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
        secure=request.url.scheme == "https",
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
            "email": email_clean,
            "error": "Please provide a valid email address.",
        }, status_code=400)

    if len(password) < 8:
        return templates.TemplateResponse(request, "auth/signup.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "email": email_clean,
            "error": "Password must be at least 8 characters long.",
        }, status_code=400)

    # bcrypt 5.x rejects passwords longer than 72 UTF-8 bytes. Reject explicitly
    # here so signup returns a useful form error instead of an unhandled 500.
    if len(password.encode("utf-8")) > 72:
        return templates.TemplateResponse(request, "auth/signup.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "email": email_clean,
            "error": "Password must be no more than 72 UTF-8 bytes long.",
        }, status_code=400)

    try:
        existing = db.query(User).filter(User.email == email_clean).first()
        if existing:
            return templates.TemplateResponse(request, "auth/signup.html", {
                "current_user": None,
                "csrf_token": get_or_create_csrf_token(request),
                "email": email_clean,
                "error": "An account with that email already exists.",
            }, status_code=400)

        new_user = User(
            email=email_clean,
            password_hash=hash_password(password),
            timezone=timezone or "UTC",
        )
        db.add(new_user)
        # Force INSERT now so uniqueness/constraint errors are handled below.
        db.flush()
        user_id = new_user.id
        db.commit()
    except IntegrityError:
        db.rollback()
        # A concurrent signup may have inserted this email after the initial query.
        return templates.TemplateResponse(request, "auth/signup.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "email": email_clean,
            "error": "An account with that email already exists. Please sign in instead.",
        }, status_code=400)
    except SQLAlchemyError as exc:
        db.rollback()
        # Avoid including an email, SQL parameters, or credentials in application logs.
        logger.error("Signup database operation failed (%s)", type(exc).__name__)
        return templates.TemplateResponse(request, "auth/signup.html", {
            "current_user": None,
            "csrf_token": get_or_create_csrf_token(request),
            "email": email_clean,
            "error": "Account creation is temporarily unavailable. Please try again shortly.",
        }, status_code=503)

    session_token = create_session_token(user_id)
    response = RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="cw_session",
        value=session_token,
        httponly=True,
        max_age=86400 * 14,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/logout")
async def logout_action():
    response = RedirectResponse(url="/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("cw_session")
    return response
