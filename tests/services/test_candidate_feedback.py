"""Tests for candidate feedback service."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.candidate_feedback import generate_candidate_feedback, _build_feedback_data


VALID_FEEDBACK_RESPONSE = json.dumps({
    "greeting": "Bonjour Jean, merci pour votre candidature au poste de Developpeur Backend Senior.",
    "strengths": [
        {
            "title": "Expertise Python solide",
            "detail": "5 ans d'experience backend Python avec une progression constante vers des roles seniors.",
        },
        {
            "title": "Maitrise FastAPI",
            "detail": "Experience demontree en production sur des projets FastAPI a fort trafic.",
        },
    ],
    "improvements": [
        {
            "title": "Competences cloud",
            "detail": "Pas de certification cloud identifiee dans votre profil.",
            "advice": "Explorez les certifications AWS ou GCP pour renforcer votre profil DevOps.",
        },
    ],
    "general_advice": "Continuez a developper vos competences en architecture distribuee. Contribuer a des projets open source est un excellent moyen de gagner en visibilite.",
    "closing": "Nous vous souhaitons beaucoup de succes dans la suite de votre parcours professionnel.",
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


class TestBuildFeedbackData:
    def test_cv_only(self):
        data = _build_feedback_data(SAMPLE_CANDIDATE, None, None)
        assert data["candidate"]["name"] == "Jean Dupont"
        assert data["scores"]["cv_score"] == 72.0
        assert "position" not in data
        assert "interview_analysis" not in data

    def test_with_all_data(self):
        data = _build_feedback_data(SAMPLE_CANDIDATE, SAMPLE_POSITION, SAMPLE_ANALYSIS)
        assert data["position"]["title"] == "Developpeur Backend Senior"
        assert data["interview_analysis"]["scores"]["global"] == 78

    def test_empty_cv_parsed_data(self):
        candidate = {"name": "Test", "cv_parsed_data": None, "cv_score": None, "profile_score": None}
        data = _build_feedback_data(candidate, None, None)
        assert data["candidate"]["name"] == "Test"
        assert data["candidate"]["skills"] == []


class TestGenerateCandidateFeedback:
    @patch("app.services.candidate_feedback.get_settings")
    @patch("app.services.candidate_feedback.Anthropic")
    def test_happy_path(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(VALID_FEEDBACK_RESPONSE)

        result = generate_candidate_feedback(SAMPLE_CANDIDATE, SAMPLE_POSITION)

        assert "Jean" in result["greeting"]
        assert len(result["strengths"]) == 2
        assert len(result["improvements"]) == 1
        assert result["improvements"][0]["advice"] is not None
        assert "generated_at" in result
        mock_client.messages.create.assert_called_once()

    @patch("app.services.candidate_feedback.get_settings")
    @patch("app.services.candidate_feedback.Anthropic")
    def test_happy_path_with_analysis(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(VALID_FEEDBACK_RESPONSE)

        result = generate_candidate_feedback(SAMPLE_CANDIDATE, SAMPLE_POSITION, SAMPLE_ANALYSIS)

        assert "greeting" in result
        assert "strengths" in result
        # Verify the prompt includes analysis data
        call_args = mock_client.messages.create.call_args
        prompt_content = call_args[1]["messages"][0]["content"]
        assert "interview_analysis" in prompt_content

    @patch("app.services.candidate_feedback.get_settings")
    @patch("app.services.candidate_feedback.Anthropic")
    def test_markdown_wrapper_cleaned(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        wrapped = f"```json\n{VALID_FEEDBACK_RESPONSE}\n```"
        mock_client.messages.create.return_value = _mock_claude_response(wrapped)

        result = generate_candidate_feedback(SAMPLE_CANDIDATE)
        assert len(result["strengths"]) == 2

    @patch("app.services.candidate_feedback.get_settings")
    @patch("app.services.candidate_feedback.Anthropic")
    def test_invalid_json_raises_value_error(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response("not valid json")

        with pytest.raises(ValueError, match="non parseable"):
            generate_candidate_feedback(SAMPLE_CANDIDATE)

    @patch("app.services.candidate_feedback.get_settings")
    @patch("app.services.candidate_feedback.Anthropic")
    def test_api_error_propagates(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API timeout")

        with pytest.raises(Exception, match="API timeout"):
            generate_candidate_feedback(SAMPLE_CANDIDATE)

    @patch("app.services.candidate_feedback.get_settings")
    @patch("app.services.candidate_feedback.Anthropic")
    def test_strengths_capped_at_4(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        response_data = json.loads(VALID_FEEDBACK_RESPONSE)
        response_data["strengths"] = [{"title": f"S{i}", "detail": f"D{i}"} for i in range(6)]
        mock_client.messages.create.return_value = _mock_claude_response(json.dumps(response_data))

        result = generate_candidate_feedback(SAMPLE_CANDIDATE)
        assert len(result["strengths"]) == 4

    @patch("app.services.candidate_feedback.get_settings")
    @patch("app.services.candidate_feedback.Anthropic")
    def test_improvements_capped_at_3(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        response_data = json.loads(VALID_FEEDBACK_RESPONSE)
        response_data["improvements"] = [
            {"title": f"I{i}", "detail": f"D{i}", "advice": f"A{i}"} for i in range(5)
        ]
        mock_client.messages.create.return_value = _mock_claude_response(json.dumps(response_data))

        result = generate_candidate_feedback(SAMPLE_CANDIDATE)
        assert len(result["improvements"]) == 3

    @patch("app.services.candidate_feedback.get_settings")
    @patch("app.services.candidate_feedback.Anthropic")
    def test_missing_fields_get_defaults(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        minimal = json.dumps({"greeting": "Bonjour."})
        mock_client.messages.create.return_value = _mock_claude_response(minimal)

        result = generate_candidate_feedback(SAMPLE_CANDIDATE)
        assert result["greeting"] == "Bonjour."
        assert result["strengths"] == []
        assert result["improvements"] == []
        assert result["general_advice"] == ""
        assert "generated_at" in result
