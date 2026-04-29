"""Tests for position_import service — extract_position_from_text edge cases."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.position_import import extract_position_from_text


def _mock_claude_response(text_content):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=text_content)]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    return mock_client


class TestExtractPositionHappyPath:
    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_valid_json_response(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        response_data = {
            "title": "Developpeur Python Senior",
            "description": "Poste de dev backend",
            "required_skills": ["Python", "PostgreSQL", "Docker", "FastAPI"],
            "seniority_level": "senior",
            "custom_questions": ["Parlez-nous de votre experience Python"],
        }
        mock_anthropic_cls.return_value = _mock_claude_response(json.dumps(response_data))

        result = extract_position_from_text("Nous cherchons un dev Python senior")

        assert result["title"] == "Developpeur Python Senior"
        assert len(result["required_skills"]) == 4
        assert result["seniority_level"] == "senior"

    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_json_in_code_block(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        raw = '```json\n{"title": "PM", "description": "Product Manager", "required_skills": ["Agile"], "seniority_level": "mid", "custom_questions": []}\n```'
        mock_anthropic_cls.return_value = _mock_claude_response(raw)

        result = extract_position_from_text("Product Manager role")
        assert result["title"] == "PM"

    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_plain_code_block(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        raw = '```\n{"title": "QA", "description": "QA Engineer", "required_skills": [], "seniority_level": "junior", "custom_questions": []}\n```'
        mock_anthropic_cls.return_value = _mock_claude_response(raw)

        result = extract_position_from_text("QA job")
        assert result["title"] == "QA"


class TestExtractPositionEdgeCases:
    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_invalid_json_returns_fallback(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        mock_anthropic_cls.return_value = _mock_claude_response("This is not JSON")

        result = extract_position_from_text("Some job description")

        assert result["title"] == "Poste importe"
        assert result["required_skills"] == []
        assert result["seniority_level"] == "mid"

    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_empty_title_gets_default(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        data = {
            "title": "",
            "description": "A role",
            "required_skills": ["Java"],
            "seniority_level": "mid",
            "custom_questions": [],
        }
        mock_anthropic_cls.return_value = _mock_claude_response(json.dumps(data))

        result = extract_position_from_text("Java developer")
        assert result["title"] == "Poste sans titre"

    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_missing_title_gets_default(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        data = {"description": "No title here", "required_skills": []}
        mock_anthropic_cls.return_value = _mock_claude_response(json.dumps(data))

        result = extract_position_from_text("text")
        assert result["title"] == "Poste sans titre"

    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_invalid_seniority_defaults_to_mid(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        data = {
            "title": "Dev",
            "description": "x",
            "required_skills": [],
            "seniority_level": "expert",  # invalid value
            "custom_questions": [],
        }
        mock_anthropic_cls.return_value = _mock_claude_response(json.dumps(data))

        result = extract_position_from_text("text")
        assert result["seniority_level"] == "mid"

    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_skills_not_list_defaults_to_empty(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        data = {
            "title": "Dev",
            "description": "x",
            "required_skills": "Python, Java",  # string instead of list
            "seniority_level": "mid",
        }
        mock_anthropic_cls.return_value = _mock_claude_response(json.dumps(data))

        result = extract_position_from_text("text")
        assert result["required_skills"] == []

    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_custom_questions_not_list_defaults_to_empty(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        data = {
            "title": "Dev",
            "description": "x",
            "required_skills": [],
            "seniority_level": "mid",
            "custom_questions": "une question",
        }
        mock_anthropic_cls.return_value = _mock_claude_response(json.dumps(data))

        result = extract_position_from_text("text")
        assert result["custom_questions"] == []

    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_empty_content_returns_fallback(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        mock_msg = MagicMock()
        mock_msg.content = []  # empty
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_msg
        mock_anthropic_cls.return_value = mock_client

        result = extract_position_from_text("text")
        assert result["title"] == "Poste importe"

    @patch("app.services.position_import.get_settings")
    @patch("app.services.position_import.Anthropic")
    def test_very_long_text_truncated_in_prompt(self, mock_anthropic_cls, mock_settings):
        mock_settings.return_value = MagicMock(
            ANTHROPIC_API_KEY="k", ANTHROPIC_MODEL="m"
        )
        data = {"title": "Dev", "description": "ok", "required_skills": [], "seniority_level": "mid", "custom_questions": []}
        mock_anthropic_cls.return_value = _mock_claude_response(json.dumps(data))

        long_text = "A" * 10000
        result = extract_position_from_text(long_text)

        # Verify the API was called with truncated text (4000 chars)
        call_args = mock_anthropic_cls.return_value.messages.create.call_args
        prompt_content = call_args[1]["messages"][0]["content"]
        # The text[:4000] truncation means max 4000 chars of input text in prompt
        assert "A" * 4000 in prompt_content
        assert result["title"] == "Dev"
