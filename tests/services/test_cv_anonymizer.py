"""Tests for CV anonymizer service."""
import pytest

from app.services.cv_anonymizer import (
    anonymize_candidate_data,
    _make_anonymous_id,
    _remove_personal_info_from_text,
    _scrub_candidate_name,
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


class TestScrubCandidateName:
    def test_removes_full_name(self):
        text = "Jean Dupont is an engineer with 10 years experience."
        result = _scrub_candidate_name(text, "Jean Dupont")
        assert "Jean Dupont" not in result
        assert "engineer" in result

    def test_removes_individual_parts(self):
        text = "Jean est un developpeur. Dupont a travaille chez X."
        result = _scrub_candidate_name(text, "Jean Dupont")
        assert "Jean" not in result
        assert "Dupont" not in result

    def test_short_words_not_scrubbed_individually(self):
        # Full name "Ali Ben" is scrubbed as a unit (specific enough)
        # But individual short parts should NOT be scrubbed when appearing alone
        text = "Ali est un developpeur senior. Ben travaille aussi."
        result = _scrub_candidate_name(text, "Ali Ben")
        # "Ali" (3 chars) and "Ben" (3 chars) individually should NOT be scrubbed
        assert "Ali" in result
        assert "Ben" in result

    def test_full_name_with_short_parts_still_scrubbed(self):
        text = "Ali Ben est un developpeur senior."
        result = _scrub_candidate_name(text, "Ali Ben")
        # Full name as a unit IS scrubbed
        assert "Ali Ben" not in result

    def test_french_titles_scrubbed(self):
        text = "M. Dupont a rejoint l'equipe. Mme Martin est arrivee."
        result = _scrub_candidate_name(text, "Jean Dupont")
        assert "M. Dupont" not in result
        assert "Mme Martin" in result  # different name, not scrubbed

    def test_case_insensitive(self):
        text = "JEAN dupont est ingenieur."
        result = _scrub_candidate_name(text, "Jean Dupont")
        assert "JEAN" not in result
        assert "dupont" not in result

    def test_multiple_occurrences(self):
        text = "Dupont a commence chez X. Plus tard, Dupont a dirige le projet."
        result = _scrub_candidate_name(text, "Jean Dupont")
        assert "Dupont" not in result

    def test_empty_name(self):
        text = "Some text here."
        result = _scrub_candidate_name(text, "")
        assert result == text

    def test_preserves_common_words(self):
        text = "le developpeur a fait un bon travail"
        result = _scrub_candidate_name(text, "Jean Dupont")
        assert result == text


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

    def test_scrubs_candidate_name_when_provided(self):
        text = "Jean Dupont a travaille chez TechCorp."
        company_map = {"TechCorp": "Entreprise A"}
        result = _scrub_names(text, company_map, {}, candidate_name="Jean Dupont")
        assert "Jean Dupont" not in result
        assert "TechCorp" not in result
        assert "Entreprise A" in result


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

    def test_candidate_name_removed_from_summary(self):
        cv_data = {
            **SAMPLE_CV_DATA,
            "summary": "Jean Dupont is an engineer with 10 years experience at TechCorp.",
        }
        result = anonymize_candidate_data(CANDIDATE_ID, cv_data)
        assert "Jean Dupont" not in result["summary"]
        assert "Jean" not in result["summary"]
        assert "Dupont" not in result["summary"]
        assert "engineer" in result["summary"]

    def test_candidate_name_removed_from_responsibilities(self):
        cv_data = {
            **SAMPLE_CV_DATA,
            "experiences": [
                {
                    "title": "Lead Dev",
                    "company": "TechCorp",
                    "duration": "3 ans",
                    "responsibilities": [
                        "Jean Dupont a dirige l'equipe backend",
                        "Dupont a mis en place les pipelines CI/CD",
                    ],
                    "key_achievements": ["Jean a livre le projet en avance"],
                }
            ],
        }
        result = anonymize_candidate_data(CANDIDATE_ID, cv_data)
        exp = result["experiences"][0]
        for resp in exp["responsibilities"]:
            assert "Dupont" not in resp
        # "Jean" is 4 chars, should be scrubbed
        for resp in exp["responsibilities"]:
            assert "Jean" not in resp
        for ach in exp["key_achievements"]:
            assert "Jean" not in ach

    def test_candidate_name_removed_from_description(self):
        cv_data = {
            **SAMPLE_CV_DATA,
            "experiences": [
                {
                    "title": "Lead Dev",
                    "company": "TechCorp",
                    "duration": "3 ans",
                    "description": "Jean Dupont a developpe des APIs REST chez TechCorp.",
                    "responsibilities": [],
                    "key_achievements": [],
                }
            ],
        }
        result = anonymize_candidate_data(CANDIDATE_ID, cv_data)
        exp = result["experiences"][0]
        assert "Jean Dupont" not in exp["description"]
        assert "Jean" not in exp["description"]
        assert "Dupont" not in exp["description"]
        assert "TechCorp" not in exp["description"]
        assert "Entreprise A" in exp["description"]

    def test_false_positives_short_words_not_scrubbed(self):
        """Verify that common short words (le, de, et) are NOT scrubbed."""
        cv_data = {
            "name": "Ali De Le",
            "skills": ["Python"],
            "experiences": [
                {
                    "title": "Dev",
                    "company": "Acme",
                    "duration": "1 an",
                    "description": "le developpeur de talent et de rigueur",
                    "responsibilities": ["le lead de l'equipe et la gestion"],
                    "key_achievements": [],
                }
            ],
            "education": [],
            "languages": [],
        }
        result = anonymize_candidate_data(CANDIDATE_ID, cv_data)
        exp = result["experiences"][0]
        # "le", "De", "et" are <= 3 chars, should NOT be individually scrubbed
        assert "le" in exp["description"].lower()
        assert "de" in exp["description"].lower()
        assert "et" in exp["description"].lower()
        assert "le" in exp["responsibilities"][0].lower()
        assert "de" in exp["responsibilities"][0].lower()
