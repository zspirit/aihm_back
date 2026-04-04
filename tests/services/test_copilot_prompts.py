"""Tests for copilot_prompts constants."""
from app.services.copilot_prompts import COPILOT_SYSTEM_PROMPT, COPILOT_TOOLS


def test_system_prompt_is_string():
    assert isinstance(COPILOT_SYSTEM_PROMPT, str)
    assert len(COPILOT_SYSTEM_PROMPT) > 100


def test_system_prompt_guardrails():
    assert "NE recommande JAMAIS" in COPILOT_SYSTEM_PROMPT
    assert "NE déduis JAMAIS" in COPILOT_SYSTEM_PROMPT


def test_tools_is_list():
    assert isinstance(COPILOT_TOOLS, list)
    assert len(COPILOT_TOOLS) == 8


def test_each_tool_has_schema():
    for tool in COPILOT_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "input_schema" in tool
        assert tool["input_schema"]["type"] == "object"


def test_tool_names():
    names = {t["name"] for t in COPILOT_TOOLS}
    expected = {
        "search_candidates", "list_positions", "get_position_details",
        "get_candidate_details", "get_analytics_overview", "aggregate_scores",
        "get_pipeline_breakdown", "export_data",
    }
    assert names == expected
