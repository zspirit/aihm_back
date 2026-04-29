"""Tests for matching service — ai_score_matches edge cases."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.matching import ai_score_matches


def _make_candidate(candidate_id="aaa-111", name="Alice", cv_score=80, skills=None):
    return {
        "candidate_id": candidate_id,
        "name": name,
        "email": f"{name.lower()}@test.com",
        "source_position_id": "pos-1",
        "source_position_title": "Dev Python",
        "cv_score": cv_score,
        "cv_parsed_data": {
            "skills": skills or ["Python", "FastAPI"],
            "experience_years": 5,
            "summary": "Senior dev",
        },
    }


POSITION_DATA = {
    "title": "Backend Engineer",
    "description": "We need a backend engineer.",
    "required_skills": ["Python", "PostgreSQL"],
    "seniority_level": "senior",
}


class TestAiScoreMatchesEmptyInput:
    def test_empty_candidates_returns_empty(self):
        result = ai_score_matches([], POSITION_DATA)
        assert result == []

    def test_none_candidates_edge(self):
        # Should not crash on empty list
        result = ai_score_matches([], {})
        assert result == []


class TestAiScoreMatchesHappyPath:
    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_valid_response_parsed(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="test-key", ANTHROPIC_MODEL="claude-test"
        )
        candidates = [_make_candidate("c1", "Alice"), _make_candidate("c2", "Bob")]

        api_response = {
            "matches": [
                {
                    "candidate_id": "c1",
                    "match_score": 90,
                    "match_reasons": {"skills_overlap": {"score": 95, "details": "ok"}},
                },
                {
                    "candidate_id": "c2",
                    "match_score": 70,
                    "match_reasons": {"skills_overlap": {"score": 60, "details": "partial"}},
                },
            ]
        }

        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(api_response))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches(candidates, POSITION_DATA)

        assert len(result) == 2
        assert result[0]["match_score"] == 90
        assert result[0]["name"] == "Alice"
        assert result[1]["match_score"] == 70

    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_response_with_json_code_block(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        candidates = [_make_candidate("c1")]

        raw_text = '```json\n{"matches": [{"candidate_id": "c1", "match_score": 85, "match_reasons": {}}]}\n```'
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=raw_text)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches(candidates, POSITION_DATA)
        assert len(result) == 1
        assert result[0]["match_score"] == 85

    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_response_with_plain_code_block(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        candidates = [_make_candidate("c1")]

        raw_text = '```\n{"matches": [{"candidate_id": "c1", "match_score": 50, "match_reasons": {}}]}\n```'
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=raw_text)]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches(candidates, POSITION_DATA)
        assert len(result) == 1
        assert result[0]["match_score"] == 50


class TestAiScoreMatchesEdgeCases:
    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_invalid_json_returns_empty(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="not json at all")]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches([_make_candidate()], POSITION_DATA)
        assert result == []

    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_unknown_candidate_id_filtered(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        candidates = [_make_candidate("c1")]
        api_response = {
            "matches": [
                {"candidate_id": "unknown-id", "match_score": 90, "match_reasons": {}},
                {"candidate_id": "c1", "match_score": 80, "match_reasons": {}},
            ]
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(api_response))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches(candidates, POSITION_DATA)
        assert len(result) == 1
        assert result[0]["candidate_id"] == "c1"

    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_missing_match_score_defaults_to_zero(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        candidates = [_make_candidate("c1")]
        api_response = {
            "matches": [
                {"candidate_id": "c1", "match_reasons": {"x": "y"}},
            ]
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(api_response))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches(candidates, POSITION_DATA)
        assert len(result) == 1
        assert result[0]["match_score"] == 0

    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_empty_matches_array(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='{"matches": []}')]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches([_make_candidate()], POSITION_DATA)
        assert result == []

    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_no_matches_key_in_response(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text='{"results": []}')]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches([_make_candidate()], POSITION_DATA)
        assert result == []

    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_candidate_with_no_cv_parsed_data(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        candidate = _make_candidate("c1")
        candidate["cv_parsed_data"] = {}

        api_response = {
            "matches": [{"candidate_id": "c1", "match_score": 40, "match_reasons": {}}]
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(api_response))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches([candidate], POSITION_DATA)
        assert len(result) == 1

    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_results_sorted_by_score_desc(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        candidates = [
            _make_candidate("c1", "Alice"),
            _make_candidate("c2", "Bob"),
            _make_candidate("c3", "Charlie"),
        ]
        api_response = {
            "matches": [
                {"candidate_id": "c1", "match_score": 50, "match_reasons": {}},
                {"candidate_id": "c2", "match_score": 90, "match_reasons": {}},
                {"candidate_id": "c3", "match_score": 70, "match_reasons": {}},
            ]
        }
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=json.dumps(api_response))]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches(candidates, POSITION_DATA)
        scores = [r["match_score"] for r in result]
        assert scores == [90, 70, 50]

    @patch("app.services.matching.get_settings")
    @patch("app.services.matching.Anthropic")
    def test_empty_content_raises_returns_empty(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        mock_msg = MagicMock()
        mock_msg.content = []  # empty content
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = ai_score_matches([_make_candidate()], POSITION_DATA)
        assert result == []
