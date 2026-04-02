"""Tests for competence dossier PDF/DOCX generation."""
import pytest
from app.services.competence_dossier import generate_dossier_pdf, generate_dossier_docx

FULL_DATA = {
    "name": "Alice Martin",
    "email": "alice@test.com",
    "phone": "+33612345678",
    "summary": "Dev backend Python 5 ans.",
    "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
    "experiences": [
        {"title": "Backend Dev", "company": "TechCorp", "duration": "3 ans", "description": "APIs REST, microservices"},
        {"title": "Junior Dev", "company": "StartupXYZ", "duration": "2 ans", "description": "Full-stack Python/React"},
    ],
    "education": [{"degree": "Master Informatique", "school": "Universite Paris", "year": "2018"}],
    "languages": ["Francais", "Anglais"],
}

MINIMAL_DATA = {"name": "Test Candidat"}


def test_generate_dossier_pdf():
    result = generate_dossier_pdf(FULL_DATA)
    assert isinstance(result, bytes)
    assert result[:5] == b"%PDF-"
    assert len(result) > 100


def test_generate_dossier_pdf_minimal():
    result = generate_dossier_pdf(MINIMAL_DATA)
    assert isinstance(result, bytes)
    assert result[:5] == b"%PDF-"


def test_generate_dossier_docx():
    result = generate_dossier_docx(FULL_DATA)
    assert isinstance(result, bytes)
    assert result[:2] == b"PK"  # ZIP/DOCX magic bytes
    assert len(result) > 100


def test_generate_dossier_docx_minimal():
    result = generate_dossier_docx(MINIMAL_DATA)
    assert isinstance(result, bytes)
    assert result[:2] == b"PK"


def test_generate_dossier_pdf_all_fields():
    result = generate_dossier_pdf(FULL_DATA)
    assert isinstance(result, bytes)
    assert len(result) > 500  # Full data should produce a substantial PDF
