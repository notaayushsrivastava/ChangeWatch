from app.services.preview_html import ensure_preview_base_href


def test_injects_target_base_before_relative_stylesheets():
    source = (
        '<!doctype html><html><head>'
        '<link rel="stylesheet" href="/assets/site.css">'
        '</head><body><img src="images/logo.svg"></body></html>'
    )

    result = ensure_preview_base_href(source, "https://example.com/news/story")

    assert result.index('<base href="https://example.com/news/story">') < result.index(
        '<link rel="stylesheet" href="/assets/site.css">'
    )
    assert '<img src="images/logo.svg">' in result


def test_replaces_existing_base_and_escapes_base_url():
    source = (
        '<html><head><base href="https://wrong.example/">'
        '<link rel="stylesheet" href="theme.css"></head></html>'
    )

    result = ensure_preview_base_href(source, 'https://example.com/page?quote="x"')

    assert result.count("<base ") == 1
    assert '<base href="https://example.com/page?quote=&quot;x&quot;">' in result
    assert '<link rel="stylesheet" href="theme.css">' in result


def test_inserts_head_when_missing():
    result = ensure_preview_base_href(
        "<html><body><div>content</div></body></html>",
        "https://example.com/",
    )

    assert "<html><head><base href=\"https://example.com/\"></head><body>" in result
