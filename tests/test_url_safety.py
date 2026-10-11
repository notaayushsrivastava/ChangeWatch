import pytest
from app.services.url_safety import validate_public_url


def test_reject_unsupported_schemes():
    is_safe, err, code = validate_public_url("ftp://example.com")
    assert not is_safe
    assert code == "INVALID_SCHEME"

    is_safe, err, code = validate_public_url("file:///etc/passwd")
    assert not is_safe
    assert code == "INVALID_SCHEME"

    is_safe, err, code = validate_public_url("javascript:alert(1)")
    assert not is_safe
    assert code == "INVALID_SCHEME"


def test_reject_embedded_credentials():
    is_safe, err, code = validate_public_url("https://user:pass@example.com")
    assert not is_safe
    assert code == "CREDENTIALS_DISALLOWED"


def test_reject_localhost_and_internal_hostnames():
    is_safe, err, code = validate_public_url("http://localhost/admin")
    assert not is_safe
    assert code == "BLOCKED_DESTINATION"

    is_safe, err, code = validate_public_url("http://sub.localhost:8080")
    assert not is_safe
    assert code == "BLOCKED_DESTINATION"

    is_safe, err, code = validate_public_url("http://127.0.0.1:8000")
    assert not is_safe
    assert code == "BLOCKED_DESTINATION"


def test_reject_cloud_metadata_endpoint():
    is_safe, err, code = validate_public_url("http://169.254.169.254/latest/meta-data/")
    assert not is_safe
    assert code in ("BLOCKED_DESTINATION", "PRIVATE_IP_BLOCKED")

    is_safe, err, code = validate_public_url("http://metadata.google.internal")
    assert not is_safe
    assert code == "BLOCKED_DESTINATION"


def test_accept_valid_public_url():
    is_safe, canonical, code = validate_public_url("https://example.com/docs")
    assert is_safe
    assert canonical == "https://example.com/docs"
    assert code is None


def test_allow_test_fixtures_flag():
    is_safe, canonical, code = validate_public_url("http://127.0.0.1:8000/fixture", allow_test_fixtures=True)
    assert is_safe
