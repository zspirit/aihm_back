"""Unit tests for the psychometrics analysis worker."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.core.config import get_settings
from app.workers import psychometrics_analysis as worker


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings is lru_cached at module load — clear so each test sees
    its patched values."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ─── Rule-based fallback ──────────────────────────────────────────────────────


def test_fallback_traits_normalizes_to_0_1_range():
    scores = {
        "score_communication": 5,
        "score_problem_solving": 4,
        "score_team_fit": 3,
        "score_stress_handling": 2,
        "score_leadership": 4,
    }
    traits = worker._fallback_traits(scores)
    for key in ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"):
        assert 0.0 <= traits[key] <= 1.0
    assert traits["_source"] == "rule_based"


def test_fallback_traits_neuroticism_inverts_stress_handling():
    """High stress_handling → low neuroticism, and vice-versa."""
    high = worker._fallback_traits({
        "score_communication": 3, "score_problem_solving": 3,
        "score_team_fit": 3, "score_stress_handling": 5, "score_leadership": 3,
    })
    low = worker._fallback_traits({
        "score_communication": 3, "score_problem_solving": 3,
        "score_team_fit": 3, "score_stress_handling": 1, "score_leadership": 3,
    })
    assert high["neuroticism"] < low["neuroticism"]


@pytest.mark.parametrize("stress, team, expected", [
    (5, 5, "low"),       # composite 10
    (5, 3, "low"),       # composite 8
    (4, 3, "medium"),    # composite 7
    (3, 3, "medium"),    # composite 6
    (2, 3, "high"),      # composite 5
    (1, 1, "high"),
])
def test_fallback_risk_thresholds(stress, team, expected):
    scores = {
        "score_communication": 3,
        "score_problem_solving": 3,
        "score_team_fit": team,
        "score_stress_handling": stress,
        "score_leadership": 3,
    }
    assert worker._fallback_risk(scores) == expected


# ─── _call_claude ─────────────────────────────────────────────────────────────


def test_call_claude_returns_none_when_no_api_key():
    with patch("app.core.config.get_settings") as gs:
        gs.return_value.ANTHROPIC_API_KEY = ""
        gs.return_value.ANTHROPIC_MODEL = "claude-x"
        assert worker._call_claude({
            "score_communication": 3, "score_problem_solving": 3,
            "score_team_fit": 3, "score_stress_handling": 3, "score_leadership": 3,
        }) is None


def test_call_claude_extracts_json_from_preamble():
    """Claude often prefixes JSON with prose. The parser must still find it."""
    fake_text_block = MagicMock()
    fake_text_block.text = (
        "Here is the analysis:\n"
        '{"openness": 0.7, "conscientiousness": 0.8, "extraversion": 0.6, '
        '"agreeableness": 0.5, "neuroticism": 0.3, "turnover_risk": "low"}\n'
        "Let me know if you need more."
    )
    fake_response = MagicMock()
    fake_response.content = [fake_text_block]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_response)

    with patch("app.core.config.get_settings") as gs:
        gs.return_value.ANTHROPIC_API_KEY = "sk-test"
        gs.return_value.ANTHROPIC_MODEL = "claude-x"
        with patch("anthropic.Anthropic", return_value=fake_client):
            result = worker._call_claude({
                "score_communication": 4, "score_problem_solving": 5,
                "score_team_fit": 3, "score_stress_handling": 4, "score_leadership": 3,
            })

    assert result == {
        "openness": 0.7, "conscientiousness": 0.8, "extraversion": 0.6,
        "agreeableness": 0.5, "neuroticism": 0.3, "turnover_risk": "low",
    }


def test_call_claude_returns_none_on_api_error():
    """Network/SDK errors must not propagate — caller falls back to rules."""
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(side_effect=ConnectionError("api down"))

    with patch("app.core.config.get_settings") as gs:
        gs.return_value.ANTHROPIC_API_KEY = "sk-test"
        gs.return_value.ANTHROPIC_MODEL = "claude-x"
        with patch("anthropic.Anthropic", return_value=fake_client):
            assert worker._call_claude({
                "score_communication": 3, "score_problem_solving": 3,
                "score_team_fit": 3, "score_stress_handling": 3, "score_leadership": 3,
            }) is None


def test_call_claude_returns_none_on_unparseable_response():
    fake_text_block = MagicMock()
    fake_text_block.text = "I cannot help with that."
    fake_response = MagicMock()
    fake_response.content = [fake_text_block]
    fake_client = MagicMock()
    fake_client.messages.create = MagicMock(return_value=fake_response)

    with patch("app.core.config.get_settings") as gs:
        gs.return_value.ANTHROPIC_API_KEY = "sk-test"
        gs.return_value.ANTHROPIC_MODEL = "claude-x"
        with patch("anthropic.Anthropic", return_value=fake_client):
            assert worker._call_claude({
                "score_communication": 3, "score_problem_solving": 3,
                "score_team_fit": 3, "score_stress_handling": 3, "score_leadership": 3,
            }) is None
