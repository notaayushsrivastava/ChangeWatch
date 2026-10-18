import base64
import hashlib
import time
from typing import Optional, Dict, Any
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.config import settings

# Stateless OAuth serializers using existing APP_SECRET_KEY
_oauth_code_serializer = URLSafeTimedSerializer(settings.APP_SECRET_KEY, salt="cw-oauth-code")
_oauth_token_serializer = URLSafeTimedSerializer(settings.APP_SECRET_KEY, salt="cw-oauth-token")

# Default token lifetimes
OAUTH_CODE_MAX_AGE_SECONDS = 300       # 5 minutes
OAUTH_TOKEN_MAX_AGE_SECONDS = 86400 * 30 # 30 days


def verify_pkce(code_verifier: str, code_challenge: str, method: str = "S256") -> bool:
    """Validate RFC 7636 PKCE code_verifier against code_challenge."""
    if not code_challenge:
        return True
    if not code_verifier:
        return False

    if method.upper() == "PLAIN":
        return code_verifier == code_challenge

    if method.upper() == "S256":
        # SHA256 of ASCII code_verifier, URL-safe base64 encoded without padding
        digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
        computed_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return computed_challenge == code_challenge.rstrip("=")

    return False


def create_oauth_code(
    user_id: str,
    client_id: str,
    redirect_uri: str,
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
    scopes: Optional[str] = None,
) -> str:
    """Generate cryptographically signed, stateless 5-minute authorization code."""
    payload = {
        "user_id": user_id,
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code_challenge": code_challenge or "",
        "code_challenge_method": code_challenge_method or "S256",
        "scopes": scopes or "openid profile monitors",
        "created_at": time.time(),
    }
    return _oauth_code_serializer.dumps(payload)


def verify_oauth_code(code: str, max_age: int = OAUTH_CODE_MAX_AGE_SECONDS) -> Optional[Dict[str, Any]]:
    """Verify authorization code and return payload if valid and not expired."""
    try:
        data = _oauth_code_serializer.loads(code, max_age=max_age)
        return data
    except (BadSignature, SignatureExpired):
        return None


def create_access_token(user_id: str, client_id: str = "changewatch-mcp-client", scopes: str = "monitors") -> str:
    """Generate cryptographically signed 30-day Bearer access token."""
    payload = {
        "user_id": user_id,
        "client_id": client_id,
        "scopes": scopes,
        "created_at": time.time(),
    }
    return _oauth_token_serializer.dumps(payload)


def verify_access_token(token: str, max_age: int = OAUTH_TOKEN_MAX_AGE_SECONDS) -> Optional[str]:
    """Verify access token and return user_id if valid."""
    try:
        data = _oauth_token_serializer.loads(token, max_age=max_age)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


# RFC 7591 In-Memory Dynamic Client Registration Cache
_registered_clients: Dict[str, Dict[str, Any]] = {}


def register_oauth_client(
    client_name: Optional[str] = None,
    redirect_uris: Optional[list] = None,
    grant_types: Optional[list] = None,
    token_endpoint_auth_method: str = "none",
) -> Dict[str, Any]:
    """Register an OAuth client dynamically per RFC 7591."""
    import secrets
    clean_name = (client_name or "").strip() or "MCP Client"
    client_id = f"cw-{secrets.token_hex(8)}"
    client_secret = secrets.token_urlsafe(32)

    record = {
        "client_id": client_id,
        "client_name": clean_name,
        "client_secret": client_secret,
        "client_secret_expires_at": 0,
        "redirect_uris": redirect_uris or [],
        "grant_types": grant_types or ["authorization_code"],
        "token_endpoint_auth_method": token_endpoint_auth_method,
        "client_id_issued_at": int(time.time()),
    }
    _registered_clients[client_id] = record
    return record


def get_oauth_client(client_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve registered client metadata by client_id."""
    return _registered_clients.get(client_id)

