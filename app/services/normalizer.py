import hashlib
import re
from typing import List, Optional, Tuple


# Regex patterns for volatile noise
TIMESTAMP_PATTERNS = [
    # Relative times
    re.compile(r"\b\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago\b", re.IGNORECASE),
    re.compile(r"\b(?:just now|a moment ago|yesterday|today)\b", re.IGNORECASE),
    # Standard ISO / Date stamps
    re.compile(r"\b\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM|am|pm)?\b"),
]

COUNTER_PATTERNS = [
    re.compile(r"\b\d{1,3}(?:,\d{3})*\s+(?:views|likes|shares|retweets|followers|subscribers|stars|forks|comments|reads)\b", re.IGNORECASE),
]

TOKEN_PATTERNS = [
    re.compile(r"\b(?:csrf|token|session|nonce)[_\-a-z0-9]*[=:][\s\"']?([a-f0-9]{24,64})[\"']?", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{32,64}\b", re.IGNORECASE),  # Standalone hex hashes/UUIDs
]


def normalize_whitespace(text: str) -> str:
    """Normalize lines, tabs, and multiple spaces into clean LF-separated lines."""
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def filter_noise(text: str, filter_timestamps: bool = True, filter_counters: bool = True, filter_tokens: bool = True) -> str:
    """Mask or remove volatile patterns from extracted text."""
    result = text

    if filter_timestamps:
        for pat in TIMESTAMP_PATTERNS:
            result = pat.sub("[TIMESTAMP]", result)

    if filter_counters:
        for pat in COUNTER_PATTERNS:
            result = pat.sub("[COUNTER]", result)

    if filter_tokens:
        for pat in TOKEN_PATTERNS:
            result = pat.sub("[TOKEN]", result)

    return result


def compute_normalized_content(
    raw_text: str,
    sensitivity: str = "medium",
    filter_timestamps: bool = True,
    filter_counters: bool = True,
    filter_tokens: bool = True,
) -> Tuple[str, str]:
    """
    Normalizes extracted text and returns (normalized_text, content_hash).
    """
    clean = normalize_whitespace(raw_text)

    # In medium and low sensitivity, normalize common noise patterns
    if sensitivity in ("low", "medium"):
        clean = filter_noise(
            clean,
            filter_timestamps=filter_timestamps,
            filter_counters=filter_counters,
            filter_tokens=filter_tokens
        )
        clean = normalize_whitespace(clean)

    content_hash = hashlib.sha256(clean.encode("utf-8")).hexdigest()
    return clean, content_hash


def is_meaningful_change(prev_text: str, curr_text: str, sensitivity: str = "medium") -> bool:
    """
    Evaluates whether difference between normalized texts passes sensitivity threshold.
    """
    if prev_text == curr_text:
        return False

    if sensitivity == "high":
        return True

    # Compute character length difference and edit distance metric
    len_diff = abs(len(curr_text) - len(prev_text))
    max_len = max(len(prev_text), len(curr_text), 1)

    if sensitivity == "low":
        # Low sensitivity requires at least 30 characters delta or > 5% total text difference
        if len_diff >= 30 or (len_diff / max_len) >= 0.05:
            return True
        # Check line differences
        prev_lines = set(prev_text.splitlines())
        curr_lines = set(curr_text.splitlines())
        sym_diff = prev_lines.symmetric_difference(curr_lines)
        return len(sym_diff) >= 3

    # Medium sensitivity: any line change or > 5 characters change
    return len_diff > 0 or prev_text != curr_text


def matches_keyword_filter(diff_items: list, keywords: list) -> bool:
    """
    Returns True if keywords list is empty, or if any addition in diff_items
    contains at least one of the configured keywords (case-insensitive).
    """
    if not keywords:
        return True

    clean_keywords = [kw.strip().lower() for kw in keywords if kw and kw.strip()]
    if not clean_keywords:
        return True

    added_texts = [
        item.get("text", "").lower()
        for item in diff_items
        if item.get("type") in ("add", "added")
    ]
    for kw in clean_keywords:
        for text in added_texts:
            if kw in text:
                return True
    return False


def parse_numeric_value(raw: str) -> Optional[Tuple[float, Optional[str], str]]:
    """
    Parses a string into (float_value, unit, raw_clean).
    Supports currency ($29.99), percentages (98.5%), counts (12,500 users).
    """
    if not raw or not isinstance(raw, str):
        return None

    cleaned = raw.strip()
    # Find currency / unit symbols
    unit = ""
    if "$" in cleaned:
        unit = "$"
    elif "€" in cleaned:
        unit = "€"
    elif "£" in cleaned:
        unit = "£"
    elif "₹" in cleaned:
        unit = "₹"
    elif "%" in cleaned:
        unit = "%"

    # Extract digits with optional commas and decimal
    match = re.search(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", cleaned)
    if not match:
        return None

    num_str = match.group(0).replace(",", "")
    try:
        val = float(num_str)
        return val, unit, cleaned
    except ValueError:
        return None
