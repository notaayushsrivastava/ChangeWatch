import io
import pytest
from unittest.mock import AsyncMock, patch
from PIL import Image

from app.models.user import User
from app.models.monitor import Monitor
from app.models.version import Version
from app.models.numeric_observation import NumericObservation
from app.models.notification import AlertEvent
from app.services.browser_capture import CaptureResult
from app.services.normalizer import parse_numeric_value, matches_keyword_filter
from app.services.queue_service import enqueue_check, process_check_job


def create_dummy_png():
    img = Image.new("RGB", (50, 50), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_parse_numeric_value_currencies_and_metrics():
    # Currencies
    val, unit, _ = parse_numeric_value("$129.99")
    assert val == 129.99
    assert unit == "$"

    val, unit, _ = parse_numeric_value("€ 49.50")
    assert val == 49.50
    assert unit == "€"

    val, unit, _ = parse_numeric_value("£1,250.00")
    assert val == 1250.00
    assert unit == "£"

    val, unit, _ = parse_numeric_value("₹ 9,999")
    assert val == 9999.0
    assert unit == "₹"

    # Percentages
    val, unit, _ = parse_numeric_value("99.9% uptime")
    assert val == 99.9
    assert unit == "%"

    # Integers and floats with surrounding text
    val, unit, _ = parse_numeric_value("Total count: 4,812 items")
    assert val == 4812.0
    assert unit == ""

    # None / Empty
    assert parse_numeric_value("") is None
    assert parse_numeric_value("Out of stock") is None


def test_matches_keyword_filter_logic():
    diff_items = [
        {"type": "added", "text": "New pricing announced: $49/month plans available."},
        {"type": "removed", "text": "Old plan: $29/month"},
        {"type": "unchanged", "text": "Welcome to the site"},
    ]

    # Keyword present in added line
    assert matches_keyword_filter(diff_items, ["pricing"]) is True
    assert matches_keyword_filter(diff_items, ["PRICING"]) is True  # Case-insensitive
    assert matches_keyword_filter(diff_items, ["plans", "security"]) is True

    # Keyword not present in added lines
    assert matches_keyword_filter(diff_items, ["security", "breach"]) is False

    # Empty keywords list should allow all changes
    assert matches_keyword_filter(diff_items, []) is True
    assert matches_keyword_filter(diff_items, ["   "]) is True


@pytest.mark.asyncio
async def test_numeric_tracking_and_keyword_suppression_e2e(db_session):
    # 1. Create User & Monitor with keywords and numeric selector
    user = User(email="numeric_test@example.com", password_hash="dummy")
    db_session.add(user)
    db_session.commit()

    monitor = Monitor(
        user_id=user.id,
        name="GPU Stock & Price Watcher",
        url="https://example.com/gpu",
        interval_minutes=15,
        sensitivity="low",
        state="active",
        keywords=["in stock", "available"],
        numeric_selector=".price-tag"
    )
    db_session.add(monitor)
    db_session.commit()

    dummy_png = create_dummy_png()

    # 2. First check run (Baseline)
    mock_capture_1 = CaptureResult(
        success=True,
        raw_text="RTX 5090 - Out of stock. Current retail: $1,999.00",
        screenshot_bytes=dummy_png,
        http_status=200,
        duration_ms=300,
        metadata={"numeric_text": "$1,999.00"}
    )

    with patch("app.services.queue_service.browser_capture_service.capture_page", new=AsyncMock(return_value=mock_capture_1)):
        job1 = enqueue_check(db_session, monitor.id, is_manual=True)
        assert job1 is not None
        success = await process_check_job(db_session, job1)
        assert success is True

    # Verify baseline numeric observation recorded
    observations = db_session.query(NumericObservation).filter_by(monitor_id=monitor.id).all()
    assert len(observations) == 1
    assert observations[0].value == 1999.0
    assert observations[0].unit == "$"
    assert observations[0].raw_text == "$1,999.00"

    # 3. Second check run: Change occurs, BUT DOES NOT contain keywords ("in stock", "available")
    mock_capture_2 = CaptureResult(
        success=True,
        raw_text="RTX 5090 - Sold out completely. Current retail: $1,949.00",
        screenshot_bytes=dummy_png,
        http_status=200,
        duration_ms=320,
        metadata={"numeric_text": "$1,949.00"}
    )

    with patch("app.services.queue_service.browser_capture_service.capture_page", new=AsyncMock(return_value=mock_capture_2)):
        job2 = enqueue_check(db_session, monitor.id, is_manual=True)
        assert job2 is not None
        success2 = await process_check_job(db_session, job2)
        assert success2 is True

    # Numeric observation recorded for the second check
    observations = db_session.query(NumericObservation).filter_by(monitor_id=monitor.id).order_by(NumericObservation.recorded_at.asc()).all()
    assert len(observations) == 2
    assert observations[1].value == 1949.0

    # Version was recorded because content changed
    versions = db_session.query(Version).filter_by(monitor_id=monitor.id).all()
    assert len(versions) == 2

    # BUT alert must have been suppressed because keywords "in stock" / "available" were NOT in added lines!
    alerts = db_session.query(AlertEvent).filter_by(monitor_id=monitor.id).all()
    assert len(alerts) == 0

    # 4. Third check run: Change occurs WITH target keyword ("Now in stock!")
    mock_capture_3 = CaptureResult(
        success=True,
        raw_text="RTX 5090 - Now in stock! Current retail: $1,899.00",
        screenshot_bytes=dummy_png,
        http_status=200,
        duration_ms=290,
        metadata={"numeric_text": "$1,899.00"}
    )

    with patch("app.services.queue_service.browser_capture_service.capture_page", new=AsyncMock(return_value=mock_capture_3)):
        job3 = enqueue_check(db_session, monitor.id, is_manual=True)
        assert job3 is not None
        success3 = await process_check_job(db_session, job3)
        assert success3 is True

    # Numeric observation 3 recorded
    observations = db_session.query(NumericObservation).filter_by(monitor_id=monitor.id).all()
    assert len(observations) == 3
    assert observations[2].value == 1899.0

    # This time, keyword matched, so AlertEvent MUST be created!
    alerts = db_session.query(AlertEvent).filter_by(monitor_id=monitor.id).all()
    assert len(alerts) == 1
    assert "in stock" in alerts[0].diff_snippet.lower()
