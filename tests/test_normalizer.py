import pytest
from app.services.normalizer import (
    normalize_whitespace,
    filter_noise,
    compute_normalized_content,
    is_meaningful_change,
)


def test_normalize_whitespace():
    raw = "   Line 1  with   spaces \r\n\r\n  Line 2   \n\n\n Line 3 "
    expected = "Line 1 with spaces\nLine 2\nLine 3"
    assert normalize_whitespace(raw) == expected


def test_filter_volatile_timestamps():
    text1 = "Release v1.2 updated 5 minutes ago by developer."
    text2 = "Release v1.2 updated 4 hours ago by developer."

    _, hash1 = compute_normalized_content(text1, sensitivity="medium")
    _, hash2 = compute_normalized_content(text2, sensitivity="medium")

    # Both volatile timestamps should be masked to [TIMESTAMP] and result in identical hashes
    assert hash1 == hash2


def test_filter_volatile_counters():
    text1 = "Article title\n1,250 views and 45 likes\nMain article content."
    text2 = "Article title\n2,890 views and 88 likes\nMain article content."

    _, hash1 = compute_normalized_content(text1, sensitivity="medium")
    _, hash2 = compute_normalized_content(text2, sensitivity="medium")

    assert hash1 == hash2


def test_detect_meaningful_content_change():
    text1 = "Product pricing: $29 per month."
    text2 = "Product pricing: $49 per month."

    _, hash1 = compute_normalized_content(text1, sensitivity="medium")
    _, hash2 = compute_normalized_content(text2, sensitivity="medium")

    assert hash1 != hash2
    assert is_meaningful_change(text1, text2, sensitivity="medium")


def test_sensitivity_thresholds():
    prev = "This is a long documentation section containing detailed paragraphs about web monitoring features."
    minor_edit = "This is a long documentation section containing detailed paragraphs about web monitoring features!"

    # High sensitivity detects even single character changes
    assert is_meaningful_change(prev, minor_edit, sensitivity="high")

    # Low sensitivity suppresses minor character edits
    assert not is_meaningful_change(prev, minor_edit, sensitivity="low")
