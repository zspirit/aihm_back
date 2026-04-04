"""Tests for candidate profile computation service."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.profile_compute import compute_candidate_profile


VALID_CLAUDE_RESPONSE = json.dumps({
    "competencies": {
        "technical": [
            {"name": "Python", "level": 4, "normalized": "python", "demonstrated": True,
             "evidence": "5 ans, projets FastAPI"},
        ],
        "experience": [
            {"title": "Backend Dev", "company": "Acme", "duration_months": 36,
             "responsibilities": ["API design"], "key_achievements": ["Perf x3"]},
        ],
        "education": [
            {"degree": "MSc", "field": "CS", "institution": "ENSIMAG", "year": 2018},
        ],
        "languages": [{"name": "Francais", "level": "natif"}],
        "soft_skills": ["Communication", "Autonomie"],
    },
    "profile_score": 72,
    "score_explanation": {
        "overall": "Profil solide en backend Python.",
        "breakdown": {
            "technical_depth": {"score": 78, "detail": "Bonne maitrise Python/FastAPI"},
            "experience_quality": {"score": 70, "detail": "3 ans, progression"},
            "education_relevance": {"score": 65, "detail": "MSc pertinent"},
            "cv_completeness": {"score": 60, "detail": "Manque certifications"},
        },
    },
    "suggestions": [
        {"category": "impact", "priority": "high", "suggestion": "Ajouter des chiffres"},
    ],
    "cv_quality_score": 68,
    "cv_quality_details": {
        "completeness": 70, "clarity": 75, "impact": 55, "consistency": 72,
    },
})

SAMPLE_CV_DATA = {
    "summary": "Developpeur backend Python 5 ans",
    "skills": ["Python", "FastAPI", "PostgreSQL"],
    "experience_years": 5,
    "experience": [{"title": "Backend Dev", "company": "Acme", "duration": "3 ans"}],
    "education": [{"degree": "MSc CS", "institution": "ENSIMAG"}],
    "languages": ["Francais", "Anglais"],
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


class TestComputeCandidateProfile:
    @patch("app.services.profile_compute.get_settings")
    @patch("app.services.profile_compute.Anthropic")
    def test_happy_path(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(VALID_CLAUDE_RESPONSE)

        result = compute_candidate_profile(SAMPLE_CV_DATA)

        assert result["profile_score"] == 72.0
        assert isinstance(result["profile_score"], float)
        assert len(result["competencies"]["technical"]) == 1
        assert len(result["suggestions"]) == 1
        assert result["cv_quality_score"] == 68.0
        mock_client.messages.create.assert_called_once()

    @patch("app.services.profile_compute.get_settings")
    @patch("app.services.profile_compute.Anthropic")
    def test_response_with_markdown_wrapper(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        wrapped = f"```json\n{VALID_CLAUDE_RESPONSE}\n```"
        mock_client.messages.create.return_value = _mock_claude_response(wrapped)

        result = compute_candidate_profile(SAMPLE_CV_DATA)
        assert result["profile_score"] == 72.0

    @patch("app.services.profile_compute.get_settings")
    @patch("app.services.profile_compute.Anthropic")
    def test_response_with_text_before_json(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        text_with_prefix = f"Voici l'analyse:\n{VALID_CLAUDE_RESPONSE}"
        mock_client.messages.create.return_value = _mock_claude_response(text_with_prefix)

        result = compute_candidate_profile(SAMPLE_CV_DATA)
        assert result["profile_score"] == 72.0

    @patch("app.services.profile_compute.get_settings")
    @patch("app.services.profile_compute.Anthropic")
    def test_invalid_json_raises_value_error(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response("not valid json at all")

        with pytest.raises(ValueError, match="non parseable"):
            compute_candidate_profile(SAMPLE_CV_DATA)

    @patch("app.services.profile_compute.get_settings")
    @patch("app.services.profile_compute.Anthropic")
    def test_missing_keys_still_returns(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        partial = json.dumps({"profile_score": 50, "competencies": {}})
        mock_client.messages.create.return_value = _mock_claude_response(partial)

        result = compute_candidate_profile(SAMPLE_CV_DATA)
        assert result["profile_score"] == 50.0
        assert "suggestions" not in result

    @patch("app.services.profile_compute.get_settings")
    @patch("app.services.profile_compute.Anthropic")
    def test_api_error_propagates(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.side_effect = Exception("API timeout")

        with pytest.raises(Exception, match="API timeout"):
            compute_candidate_profile(SAMPLE_CV_DATA)

    @patch("app.services.profile_compute.get_settings")
    @patch("app.services.profile_compute.Anthropic")
    def test_empty_cv_data(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        mock_client.messages.create.return_value = _mock_claude_response(VALID_CLAUDE_RESPONSE)

        result = compute_candidate_profile({})
        assert "profile_score" in result

    @patch("app.services.profile_compute.get_settings")
    @patch("app.services.profile_compute.Anthropic")
    def test_score_cast_to_float(self, mock_anthropic_cls, mock_get_settings):
        mock_get_settings.return_value = _make_settings()
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client
        resp = json.dumps({"profile_score": "85", "cv_quality_score": "70", "competencies": {}})
        mock_client.messages.create.return_value = _mock_claude_response(resp)

        result = compute_candidate_profile(SAMPLE_CV_DATA)
        assert result["profile_score"] == 85.0
        assert result["cv_quality_score"] == 70.0
        assert isinstance(result["profile_score"], float)
