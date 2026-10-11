import base64
import os
import secrets
from typing import Optional
import bcrypt
from cryptography.fernet import Fernet
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.config import settings

# Session serializer
_session_serializer = URLSafeTimedSerializer(settings.APP_SECRET_KEY, salt="cw-session")
_csrf_serializer = URLSafeTimedSerializer(settings.APP_SECRET_KEY, salt="cw-csrf")

# Encryption key for secrets (webhook URLs)
try:
    _fernet = Fernet(settings.ENCRYPTION_KEY.encode())
except Exception:
    # Generate reproducible safe key from APP_SECRET_KEY if invalid
    derived = base64.urlsafe_b64encode(settings.APP_SECRET_KEY.encode().ljust(32)[:32])
    _fernet = Fernet(derived)


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def create_session_token(user_id: str) -> str:
    return _session_serializer.dumps({"user_id": user_id})


def verify_session_token(token: str, max_age: int = 86400 * 14) -> Optional[str]:
    try:
        data = _session_serializer.loads(token, max_age=max_age)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


def generate_csrf_token(session_id: str) -> str:
    return _csrf_serializer.dumps({"session_id": session_id})


def verify_csrf_token(token: str, session_id: str, max_age: int = 86400) -> bool:
    try:
        data = _csrf_serializer.loads(token, max_age=max_age)
        return data.get("session_id") == session_id
    except (BadSignature, SignatureExpired):
        return False


def encrypt_secret(secret_text: str) -> str:
    if not secret_text:
        return ""
    return _fernet.encrypt(secret_text.encode("utf-8")).decode("utf-8")


def decrypt_secret(encrypted_text: str) -> str:
    if not encrypted_text:
        return ""
    try:
        return _fernet.decrypt(encrypted_text.encode("utf-8")).decode("utf-8")
    except Exception:
        return "[Decryption Failed]"


def mask_secret(secret_text: str) -> str:
    """Mask secret URL/key for safe UI rendering, e.g. https://discord.com/api/...******"""
    if not secret_text or len(secret_text) < 15:
        return "********"
    return secret_text[:20] + "..." + secret_text[-6:]
