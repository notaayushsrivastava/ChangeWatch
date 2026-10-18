from datetime import datetime, timedelta, timezone

from app.routes.dashboard import _as_utc, _is_recent_change


def test_naive_database_datetime_is_treated_as_utc():
    changed_at = datetime(2026, 10, 18, 12, 0, 0)
    cutoff = datetime(2026, 10, 18, 11, 0, 0, tzinfo=timezone.utc)

    assert _is_recent_change(changed_at, cutoff)


def test_naive_database_datetime_outside_window_is_not_recent():
    changed_at = datetime(2026, 10, 17, 9, 0, 0)
    cutoff = datetime(2026, 10, 18, 9, 0, 1, tzinfo=timezone.utc)

    assert not _is_recent_change(changed_at, cutoff)


def test_aware_datetime_is_converted_to_utc():
    changed_at = datetime(2026, 10, 18, 18, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    expected = datetime(2026, 10, 18, 12, 30, 0, tzinfo=timezone.utc)

    assert _as_utc(changed_at) == expected


def test_missing_change_timestamp_is_not_recent():
    cutoff = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone.utc)

    assert not _is_recent_change(None, cutoff)
