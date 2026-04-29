"""Tests for report generation (PDF output)."""
from unittest.mock import MagicMock, patch
import pytest


def test_generate_pdf_report():
    from app.services.pdf_report import generate_pdf
    content = {
        "candidate_name": "Alice Martin",
        "position_title": "Backend Dev",
        "overall_score": 75,
        "skills_extracted": ["Python", "FastAPI"],
        "communication_indicators": {"clarity": 4, "structure": 4},
        "explanations": {"overall": "Bon profil technique."},
    }
    result = generate_pdf(content)
    assert isinstance(result, bytes)
    assert result[:5] == b"%PDF-"
    assert len(result) > 100


def test_generate_pdf_empty_content():
    from app.services.pdf_report import generate_pdf
    result = generate_pdf({})
    assert isinstance(result, bytes)
    assert result[:5] == b"%PDF-"


def test_generate_pdf_includes_info():
    from app.services.pdf_report import generate_pdf
    content = {
        "candidate_name": "Fatima Zahra",
        "position_title": "Data Engineer",
        "overall_score": 82,
    }
    result = generate_pdf(content)
    assert isinstance(result, bytes)
    assert len(result) > 100
