"""Helpers for making captured target HTML render faithfully in the region-picker iframe."""
import html
import re


def ensure_preview_base_href(document_html: str, base_url: str) -> str:
    """Make relative stylesheets, images, and other safe resources resolve at the target URL.

    Captured HTML is served by ChangeWatch rather than the monitored origin. Without
    a base element, URLs such as /assets/site.css or images/logo.svg incorrectly resolve
    against the ChangeWatch preview endpoint.
    """
    if not isinstance(document_html, str):
        document_html = ""

    # Never preserve a target-provided base element: replace it with the validated,
    # canonical URL from the monitor record so relative URLs have one predictable base.
    document_html = re.sub(r"<base\\b[^>]*>", "", document_html, flags=re.IGNORECASE)
    base_tag = f'<base href="{html.escape(base_url, quote=True)}">'

    head_match = re.search(r"<head\\b[^>]*>", document_html, flags=re.IGNORECASE)
    if head_match:
        return document_html[:head_match.end()] + base_tag + document_html[head_match.end():]

    html_match = re.search(r"<html\\b[^>]*>", document_html, flags=re.IGNORECASE)
    if html_match:
        insertion = f"<head>{base_tag}</head>"
        return document_html[:html_match.end()] + insertion + document_html[html_match.end():]

    body_match = re.search(r"<body\\b", document_html, flags=re.IGNORECASE)
    if body_match:
        return document_html[:body_match.start()] + f"<head>{base_tag}</head>" + document_html[body_match.start():]

    return f"<head>{base_tag}</head>{document_html}"
