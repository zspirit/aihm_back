"""Tests for position_templates service."""
from app.services.position_templates import POSITION_TEMPLATES


def test_templates_is_list():
    assert isinstance(POSITION_TEMPLATES, list)
    assert len(POSITION_TEMPLATES) >= 10


def test_each_template_has_required_fields():
    required = {"id", "title", "description", "required_skills", "seniority_level", "custom_questions", "category"}
    for tpl in POSITION_TEMPLATES:
        missing = required - set(tpl.keys())
        assert not missing, f"Template {tpl.get('id', '?')} missing: {missing}"


def test_ids_are_unique():
    ids = [t["id"] for t in POSITION_TEMPLATES]
    assert len(ids) == len(set(ids)), "Duplicate template IDs found"


def test_categories_are_valid():
    valid = {"tech", "business", "marketing", "finance", "operations", "hr"}
    for tpl in POSITION_TEMPLATES:
        assert tpl["category"] in valid, f"Invalid category: {tpl['category']}"


def test_seniority_levels_valid():
    valid = {"junior", "mid", "senior"}
    for tpl in POSITION_TEMPLATES:
        assert tpl["seniority_level"] in valid, f"Invalid seniority: {tpl['seniority_level']}"


def test_skills_and_questions_non_empty():
    for tpl in POSITION_TEMPLATES:
        assert len(tpl["required_skills"]) > 0, f"{tpl['id']} has no skills"
        assert len(tpl["custom_questions"]) > 0, f"{tpl['id']} has no questions"
