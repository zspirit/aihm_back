"""Tests for CV anonymizer service."""
import pytest

from app.services.cv_anonymizer import (
    anonymize_candidate_data,
    _make_anonymous_id,
    _remove_personal_info_from_text,
    _scrub_names,
)


SAMPLE_CV_DATA = {
    "name": "Jean Dupont",
    "email": "jean.dupont@email.com",
    "phone": "+33 6 12 34 56 78",
    "summary": "Developpeur backend chez TechCorp, diplome de Polytechnique. Contact : jean.dupont@email.com",
    "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
    "experience_years": 5,
    "experiences": [
        {
            "title": "Developpeur Senior",
            "company": "TechCorp",
            "duration": "3 ans",
            "duration_months": 36,
            "responsibilities": ["Developpement API chez TechCorp", "Architecture microservices"],
            "key_achievements": ["Migration cloud reussie pour TechCorp"],
        },
        {
            "title": "Developpeur Junior",
            "company": "StartupXYZ",
            "duration": "2 ans",
            "duration_months": 24,
            "responsibilities": ["Developpement frontend chez StartupXYZ"],
            "key_achievements": [],
        },
    ],
    "education": [
        {
            "degree": "Master",
            "field": "Informatique",
            "institution": "Polytechnique",
            "year": 2019,
        },
        {
            "degree": "Licence",
            "field": "Mathematiques",
            "institution": "Universite Paris-Saclay",
            "year": 2017,
        },
    ],
    "languages": ["Francais", "Anglais", "Espagnol"],
}

CANDIDATE_ID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"


class TestMakeAnonymousId:
    def test_basic(self):
        result = _make_anonymous_id(CANDIDATE_ID)
        assert result == "Candidat #7890"

    def test_no_dashes(self):
        result = _make_anonymous_id("abcdef1234567890")
        assert result == "Candidat #7890"


class TestRemovePersonalInfo:
    def test_removes_email(self):
        text = "Contact : jean@example.com pour plus d'infos"
        result = _remove_personal_info_from_text(text)
        assert "jean@example.com" not in result
        assert "[email]" in result

    def test_removes_urls(self):
        text = "Mon profil : https://linkedin.com/in/jean et www.monsite.fr"
        result = _remove_personal_info_from_text(text)
        assert "linkedin.com" not in result
        assert "monsite.fr" not in result

    def test_cleans_multiple_spaces(self):
        text = "Texte  avec   des   espaces"
        result = _remove_personal_info_from_text(text)
        assert "  " not in result


class TestScrubNames:
    def test_replaces_company_names(self):
        text = "J'ai travaille chez TechCorp pendant 3 ans"
        company_map = {"TechCorp": "Entreprise A"}
        result = _scrub_names(text, company_map, {})
        assert "TechCorp" not in result
        assert "Entreprise A" in result

    def test_replaces_school_names(self):
        text = "Diplome de Polytechnique en 2019"
        school_map = {"Polytechnique": "Ecole X"}
        result = _scrub_names(text, {}, school_map)
        assert "Polytechnique" not in result
        assert "Ecole X" in result


class TestAnonymizeCandidateData:
    def test_full_anonymization(self):
        result = anonymize_candidate_data(CANDIDATE_ID, SAMPLE_CV_DATA)

        # Check anonymous ID
        assert result["anonymous_id"] == "Candidat #7890"

        # Personal info should NOT be present
        assert "Jean Dupont" not in str(result)
        assert "jean.dupont@email.com" not in str(result)
        assert "+33 6 12 34 56 78" not in str(result)

        # Skills should be preserved
        assert result["skills"] == ["Python", "FastAPI", "PostgreSQL", "Docker"]

        # Languages should be preserved
        assert result["languages"] == ["Francais", "Anglais", "Espagnol"]

        # Experience years preserved
        assert result["experience_years"] == 5

    def test_companies_anonymized(self):
        result = anonymize_candidate_data(CANDIDATE_ID, SAMPLE_CV_DATA)

        companies = [exp["company"] for exp in result["experiences"]]
        assert "TechCorp" not in companies
        assert "StartupXYZ" not in companies
        assert "Entreprise A" in companies
        assert "Entreprise B" in companies

    def test_schools_anonymized(self):
        result = anonymize_candidate_data(CANDIDATE_ID, SAMPLE_CV_DATA)

        institutions = [edu["institution"] for edu in result["education"]]
        assert "Polytechnique" not in institutions
        assert "Universite Paris-Saclay" not in institutions
        assert "Ecole X" in institutions
        assert "Ecole Y" in institutions

    def test_company_names_scrubbed_from_responsibilities(self):
        result = anonymize_candidate_data(CANDIDATE_ID, SAMPLE_CV_DATA)

        first_exp = result["experiences"][0]
        for resp in first_exp["responsibilities"]:
            assert "TechCorp" not in resp
        for ach in first_exp["key_achievements"]:
            assert "TechCorp" not in ach

    def test_education_fields_preserved(self):
        result = anonymize_candidate_data(CANDIDATE_ID, SAMPLE_CV_DATA)

        first_edu = result["education"][0]
        assert first_edu["degree"] == "Master"
        assert first_edu["field"] == "Informatique"
        assert first_edu["year"] == 2019

    def test_experience_titles_preserved(self):
        result = anonymize_candidate_data(CANDIDATE_ID, SAMPLE_CV_DATA)

        assert result["experiences"][0]["title"] == "Developpeur Senior"
        assert result["experiences"][1]["title"] == "Developpeur Junior"

    def test_empty_cv_data(self):
        result = anonymize_candidate_data(CANDIDATE_ID, {})

        assert result["anonymous_id"] == "Candidat #7890"
        assert result["skills"] == []
        assert result["experiences"] == []
        assert result["education"] == []
        assert result["languages"] == []

    def test_none_cv_data(self):
        result = anonymize_candidate_data(CANDIDATE_ID, None)

        assert result["anonymous_id"] == "Candidat #7890"
        assert result["skills"] == []

    def test_summary_scrubbed(self):
        result = anonymize_candidate_data(CANDIDATE_ID, SAMPLE_CV_DATA)

        if result["summary"]:
            assert "TechCorp" not in result["summary"]
            assert "Polytechnique" not in result["summary"]
            assert "jean.dupont@email.com" not in result["summary"]
