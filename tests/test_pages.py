import pytest
from starlette.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_docs_page_loads():
    response = client.get("/docs")
    assert response.status_code == 200
    assert "Architecture &amp; Features Guide" in response.text
    assert "Vercel Serverless" in response.text
    assert "Noise Normalization Pipeline" in response.text
    assert "Two-Tier SSRF Defense Fortress" in response.text


def test_privacy_page_loads():
    response = client.get("/privacy")
    assert response.status_code == 200
    assert "Privacy Policy" in response.text
    assert "Aayush Srivastava" in response.text
    assert "aayush@aayushsrivastava.com" in response.text


def test_terms_page_loads():
    response = client.get("/terms")
    assert response.status_code == 200
    assert "Terms of Service" in response.text
    assert "Aayush Srivastava" in response.text
    assert "aayush@aayushsrivastava.com" in response.text


def test_contact_page_loads_and_submits():
    # GET
    response = client.get("/contact")
    assert response.status_code == 200
    assert "Contact Us" in response.text
    assert "aayush@aayushsrivastava.com" in response.text
    assert "Aayush Srivastava" in response.text

    # Extract CSRF token from HTML form
    import re
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', response.text)
    assert match is not None
    csrf_token = match.group(1)

    # POST contact message
    post_res = client.post(
        "/contact",
        data={
            "name": "Jane Doe",
            "email": "jane@example.com",
            "subject": "Enterprise Deployment",
            "message": "Interested in running ChangeWatch on custom container clusters.",
            "csrf_token": csrf_token,
        },
    )
    assert post_res.status_code == 200
    assert "Thank you, Jane Doe!" in post_res.text
    assert "Enterprise Deployment" in post_res.text


def test_robots_txt():
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "User-agent: *" in response.text
    assert "Allow: /docs" in response.text
    assert "Allow: /privacy" in response.text
    assert "Allow: /terms" in response.text
    assert "Allow: /contact" in response.text
    assert "Allow: /llms.txt" in response.text
    assert "Disallow: /dashboard" in response.text
    assert "Sitemap:" in response.text


def test_sitemap_xml():
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "application/xml" in response.headers["content-type"]
    assert "<urlset xmlns=" in response.text
    assert "/docs" in response.text
    assert "/privacy" in response.text
    assert "/terms" in response.text
    assert "/contact" in response.text
    assert "/llms.txt" in response.text


def test_llms_txt():
    response = client.get("/llms.txt")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "# ChangeWatch" in response.text
    assert "Aayush Srivastava" in response.text
    assert "aayush@aayushsrivastava.com" in response.text
    assert "Vercel" in response.text


def test_favicons_available():
    # Direct /favicon.ico route
    res_ico = client.get("/favicon.ico")
    assert res_ico.status_code == 200

    # Static SVG favicon
    res_svg = client.get("/static/favicon.svg")
    assert res_svg.status_code == 200
    assert "<svg" in res_svg.text


def test_landing_page_does_not_contain_konami_code_reference():
    response = client.get("/")
    assert response.status_code == 200
    # Must NOT contain the Konami code reference or hint
    assert "(&uarr;&uarr;&darr;&darr;&larr;&rarr;&larr;&rarr;BA)" not in response.text
    assert "Konami Code Active" not in response.text
    # Must contain cookie consent banner
    assert "cw-cookie-banner" in response.text
    # Must contain favicon links
    assert 'href="/static/favicon.svg"' in response.text
    # Top bar must contain MCP tag linking to /docs/mcp
    assert 'href="/docs/mcp"' in response.text
    assert '>MCP<' in response.text
    # Footer must contain MCP Integration link instead of llms.txt link
    assert 'MCP Integration' in response.text


def test_mcp_docs_page_loads():
    response = client.get("/docs/mcp")
    assert response.status_code == 200
    assert "Model Context Protocol" in response.text
    assert "claude_desktop_config.json" in response.text
    assert "Cursor IDE Setup" in response.text
    assert "list_monitors" in response.text
    assert "create_monitor" in response.text

