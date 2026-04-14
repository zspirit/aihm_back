"""Tests for enriched 30-second candidate summary (4.6)."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.candidate_summary import generate_candidate_summary


MOCK_FULL_SUMMARY = {
    "pitch": "Developpeur backend senior 5 ans, specialise Python/FastAPI.",
    "strengths": ["5 ans Python", "Expert FastAPI", "CI/CD Docker"],
    "concerns": ["Pas d'experience Kubernetes"],
    "areas_to_dig": [
        "Pourquoi avoir quitte TechCorp apres 3 ans ?",
        "Experience en equipe distribuee ?",
        "Gestion de charge en production ?",
    ],
    "red_flags": ["Changement de poste tous les 18 mois sur 2020-2023"],
    "key_questions": [
        "Implementez un endpoint pagine avec filtres",
        "Decrivez votre strategie de cache Redis",
        "Comment debuggez-vous un memory leak en prod ?",
    ],
    "overall_score": 74,
    "recommendation": "go",
}


def _make_claude_response(content: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=json.dumps(content, ensure_ascii=False))]
    return mock_resp


@pytest.fixture
def candidate_data():
    return {
        "name": "Ali Benali",
        "cv_parsed_data": {
            "summary": "Dev backend 5 ans",
            "skills": ["Python", "FastAPI"],
            "experience_years": 5,
        },
        "cv_score": 75,
        "profile_score": 72,
    }


class TestEnrichedSummary:
    """Tests for the enriched candidate summary with new fields."""

    @patch("app.services.candidate_summary.Anthropic")
    def test_summary_returns_all_new_fields(self, mock_anthropic_cls, candidate_data):
        """Summary should include areas_to_dig, red_flags, key_questions."""
        instance = MagicMock()
        instance.messages.create.return_value = _make_claude_response(MOCK_FULL_SUMMARY)
        mock_anthropic_cls.return_value = instance

        result = generate_candidate_summary(candidate_data)

        assert "areas_to_dig" in result
        assert "red_flags" in result
        assert "key_questions" in result
        assert len(result["areas_to_dig"]) == 3
        assert len(result["red_flags"]) == 1
        assert len(result["key_questions"]) == 3

    @patch("app.services.candidate_summary.Anthropic")
    def test_summary_truncates_areas_to_dig_to_3(self, mock_anthropic_cls, candidate_data):
        """areas_to_dig should be truncated to max 3 items."""
        response = {**MOCK_FULL_SUMMARY, "areas_to_dig": ["Q1", "Q2", "Q3", "Q4", "Q5"]}
        instance = MagicMock()
        instance.messages.create.return_value = _make_claude_response(response)
        mock_anthropic_cls.return_value = instance

        result = generate_candidate_summary(candidate_data)

        assert len(result["areas_to_dig"]) == 3

    @patch("app.services.candidate_summary.Anthropic")
    def test_summary_missing_new_fields_defaults_empty(self, mock_anthropic_cls, candidate_data):
        """Old summary without new fields should default to empty lists (backward compat)."""
        old_response = {
            "pitch": "Dev backend senior.",
            "strengths": ["Python"],
            "concerns": [],
            "overall_score": 70,
            "recommendation": "go",
        }
        instance = MagicMock()
        instance.messages.create.return_value = _make_claude_response(old_response)
        mock_anthropic_cls.return_value = instance

        result = generate_candidate_summary(candidate_data)

        assert result["areas_to_dig"] == []
        assert result["red_flags"] == []
        assert result["key_questions"] == []
        assert result["pitch"] == "Dev backend senior."
        assert result["overall_score"] == 70.0

    @patch("app.services.candidate_summary.Anthropic")
    def test_summary_preserves_existing_fields(self, mock_anthropic_cls, candidate_data):
        """Existing fields (pitch, strengths, concerns, score, recommendation) still work."""
        instance = MagicMock()
        instance.messages.create.return_value = _make_claude_response(MOCK_FULL_SUMMARY)
        mock_anthropic_cls.return_value = instance

        result = generate_candidate_summary(candidate_data)

        assert result["pitch"] == MOCK_FULL_SUMMARY["pitch"]
        assert result["strengths"] == MOCK_FULL_SUMMARY["strengths"]
        assert result["concerns"] == MOCK_FULL_SUMMARY["concerns"]
        assert result["overall_score"] == 74.0
        assert result["recommendation"] == "go"
        assert "generated_at" in result

    @patch("app.services.candidate_summary.Anthropic")
    def test_summary_with_markdown_wrapped_json(self, mock_anthropic_cls, candidate_data):
        """Claude response wrapped in ```json should still parse."""
        json_text = json.dumps(MOCK_FULL_SUMMARY, ensure_ascii=False)
        wrapped = f"```json\n{json_text}\n```"
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text=wrapped)]
        instance = MagicMock()
        instance.messages.create.return_value = mock_resp
        mock_anthropic_cls.return_value = instance

        result = generate_candidate_summary(candidate_data)

        assert result["pitch"] == MOCK_FULL_SUMMARY["pitch"]
        assert len(result["areas_to_dig"]) == 3

    @patch("app.services.candidate_summary.Anthropic")
    def test_summary_invalid_json_raises(self, mock_anthropic_cls, candidate_data):
        """Non-JSON response should raise ValueError."""
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="This is not JSON at all")]
        instance = MagicMock()
        instance.messages.create.return_value = mock_resp
        mock_anthropic_cls.return_value = instance

        with pytest.raises(ValueError, match="Reponse Claude non parseable"):
            generate_candidate_summary(candidate_data)
