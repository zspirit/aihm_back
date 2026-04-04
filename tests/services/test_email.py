"""Tests for email template rendering service."""
from app.services.email import render, _TEMPLATE_DIR


def test_template_dir_exists():
    assert _TEMPLATE_DIR.exists()


def test_render_consent_invite():
    html = render(
        "email/consent_invite.html",
        candidate_name="Alice Dupont",
        position_title="Dev Backend",
        company_name="Acme",
        consent_url="https://example.com/consent/abc",
    )
    assert "Alice Dupont" in html
    assert "https://example.com/consent/abc" in html


def test_render_password_reset():
    html = render(
        "email/password_reset.html",
        user_name="Bob",
        reset_url="https://example.com/reset/xyz",
    )
    assert "Bob" in html
    assert "https://example.com/reset/xyz" in html


def test_render_autoescape():
    """Jinja2 autoescape should escape HTML in context vars."""
    html = render(
        "email/consent_invite.html",
        candidate_name="<script>alert(1)</script>",
        position_title="Test",
        company_name="Co",
        consent_url="https://example.com",
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
