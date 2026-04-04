"""Tests for candidate summary service (resume 30 secondes)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.candidate_summary import generate_candidate_summary, _build_candidate_data


VALID_SUMMARY_RESPONSE = json.dumps({
    "pitch": "Developpeur backend Python senior avec 5 ans d'experience, specialise FastAPI et PostgreSQL.",
    "strengths": [
        "5 ans d'experience backend Python avec progression constante",
        "Maitrise demontree de FastAPI en production",
        "Amelioration de performance x3 sur projet critique",
    ],
    "concerns": [
        "Pas de certification cloud (AWS/GCP)",
        "Experience limitee en management d'equipe",
    ],
    "overall_score": 74,
    "recommendation": "go",
})

SAMPLE_CANDIDATE = {
    "name": "Jean Dupont",
    "cv_parsed_data": {
        "summary": "Developpeur backend Python 5 ans",
        "skills": ["Python", "FastAPI", "PostgreSQL"],
        "experience_years": 5,
        "experiences": [{"title": "Backend Dev", "company": "Acme", "duration": "3 ans"}],
        "education": [{"degree": "MSc CS", "institution": "ENSIMAG"}],
        "languages": ["Francais", "Anglais"],
    },
    "cv_score": 72.0,
    "profile_score": 75.0,
}

SAMPLE_POSITION = {
    "title": "Developpeur Backend Senior",
    "required_skills": ["Python", "FastAPI", "PostgreSQL"],
    "seniority_level": "senior",
}

SAMPLE_INTERVIEW = {
    "status": "completed",
    "duration_seconds": 420,
    "questions_asked": [
        {"question": "Parlez-moi de votre experience Python", "type": "technical"}
    ],
}

SAMPLE_ANALYSIS = {
    "scores": {"global": 78, "technical": 82, "communication": 70},
    "skills_extracted": ["Python", "FastAPI"],
    "communication_indicators": {"clarity": "good", "fluency": "good"},
    "score_explanations": {"global": "Bon profil technique"},
}


def _mock_claude_response(text: str):
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


def _make_settings():
    settings = MagicMock()
    settings.ANTHROPIC_API_KEY = "test-key"
    settings.ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
    return settings


class TestBuildCandidateData:
    def test_cv_only(self):
        data = _build_candidate_data(SAMPLE_CANDIDATE, None, None, None)
        assert data["cv"]["name"] == "Jean Dupont"
        assert data["scores"]["cv_score"] == 72.0
        assert "position" not in data
        assert "interview" not in data
        assert "analysis" not in data

    def test_with_all_data(self):
        data = _build_candidate_data(
            SAMPLE_CANDIDATE, SAMPLE_POSITION, SAMPLE_INTERVIEW, SAMPLE_ANALYSIS
        )
        assert data["position"]["title"] == "Developpeur Backend Senior"
        assert data["interview"]["duration_seconds"] == 420
        assert data["analysis"]["scores"]["global"] == 78

    def test_empty_cv_parsed_data(self):
        candidate = {"name": "Test", "cv_parsed_data": None, "cv_score": None, "profile_score": None}
        data = _build_candidate_data(candidate, None, None, None)
        assert data["cv"]["name"] == "Test"
        assert data["cv"]["skills"] == []


class TestGenerateCandidateSummary:
    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_happy_path_cv_only(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(VALID_SUMMARY_RESPONSE)

        result = generate_candidate_summary(SAMPLE_CANDIDATE)

        assert result["pitch"].startswith("Developpeur backend")
        assert len(result["strengths"]) == 3
        assert len(result["concerns"]) == 2
        assert result["overall_score"] == 74.0
        assert result["recommendation"] == "go"
        assert "generated_at" in result
        mock_client.messages.create.assert_called_once()

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_happy_path_with_interview(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(VALID_SUMMARY_RESPONSE)

        result = generate_candidate_summary(
            SAMPLE_CANDIDATE, SAMPLE_POSITION, SAMPLE_INTERVIEW, SAMPLE_ANALYSIS
        )

        assert result["recommendation"] == "go"
        assert result["overall_score"] == 74.0
        # Verify the prompt includes interview data
        call_args = mock_client.messages.create.call_args
        prompt_content = call_args[1]["messages"][0]["content"]
        assert "interview" in prompt_content
        assert "analysis" in prompt_content

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_candidate_without_interview(self, mock_anthropic_cls, mock_get_settings):
        """Un candidat sans entretien doit quand meme obtenir un resume base sur le CV."""
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(VALID_SUMMARY_RESPONSE)

        result = generate_candidate_summary(SAMPLE_CANDIDATE)

        assert "pitch" in result
        assert "strengths" in result
        assert "recommendation" in result

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_response_with_markdown_wrapper(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        wrapped = f"```json\n{VALID_SUMMARY_RESPONSE}\n```"
        mock_client.messages.create.return_value = _mock_claude_response(wrapped)

        result = generate_candidate_summary(SAMPLE_CANDIDATE)
        assert result["overall_score"] == 74.0

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_invalid_json_raises_value_error(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response("not valid json")

        with pytest.raises(ValueError, match="non parseable"):
            generate_candidate_summary(SAMPLE_CANDIDATE)

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_api_error_propagates(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API timeout")

        with pytest.raises(Exception, match="API timeout"):
            generate_candidate_summary(SAMPLE_CANDIDATE)

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_strengths_capped_at_3(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        response_data = json.loads(VALID_SUMMARY_RESPONSE)
        response_data["strengths"] = ["a", "b", "c", "d", "e"]
        mock_client.messages.create.return_value = _mock_claude_response(json.dumps(response_data))

        result = generate_candidate_summary(SAMPLE_CANDIDATE)
        assert len(result["strengths"]) == 3

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_concerns_capped_at_2(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        response_data = json.loads(VALID_SUMMARY_RESPONSE)
        response_data["concerns"] = ["a", "b", "c", "d"]
        mock_client.messages.create.return_value = _mock_claude_response(json.dumps(response_data))

        result = generate_candidate_summary(SAMPLE_CANDIDATE)
        assert len(result["concerns"]) == 2

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_invalid_recommendation_defaults_to_deepen(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        response_data = json.loads(VALID_SUMMARY_RESPONSE)
        response_data["recommendation"] = "maybe"
        mock_client.messages.create.return_value = _mock_claude_response(json.dumps(response_data))

        result = generate_candidate_summary(SAMPLE_CANDIDATE)
        assert result["recommendation"] == "to_deepen"

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_score_cast_to_float(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        response_data = json.loads(VALID_SUMMARY_RESPONSE)
        response_data["overall_score"] = "82"
        mock_client.messages.create.return_value = _mock_claude_response(json.dumps(response_data))

        result = generate_candidate_summary(SAMPLE_CANDIDATE)
        assert result["overall_score"] == 82.0
        assert isinstance(result["overall_score"], float)

    @patch("app.services.candidate_summary.get_settings")
    @patch("app.services.candidate_summary.Anthropic")
    def test_missing_fields_get_defaults(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        minimal = json.dumps({"pitch": "Un dev."})
        mock_client.messages.create.return_value = _mock_claude_response(minimal)

        result = generate_candidate_summary(SAMPLE_CANDIDATE)
        assert result["pitch"] == "Un dev."
        assert result["strengths"] == []
        assert result["concerns"] == []
        assert result["overall_score"] == 0.0
        assert result["recommendation"] == "to_deepen"
