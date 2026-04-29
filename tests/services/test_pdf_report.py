"""Tests for PDF report generation service."""
import pytest
from app.services.pdf_report import (
    generate_pdf,
    _score_color,
    _score_bg,
    _level_color,
    _level_bg,
    _level_bar_text,
    _draw_radar_chart,
)
from reportlab.lib import colors


# --- Helper color tests ---

class TestScoreColor:
    def test_high_score_green(self):
        assert _score_color(85) == colors.HexColor("#16A34A")

    def test_medium_score_orange(self):
        assert _score_color(55) == colors.HexColor("#CA8A04")

    def test_low_score_red(self):
        assert _score_color(30) == colors.HexColor("#DC2626")

    def test_boundary_70(self):
        assert _score_color(70) == colors.HexColor("#16A34A")

    def test_boundary_50(self):
        assert _score_color(50) == colors.HexColor("#CA8A04")

    def test_boundary_49(self):
        assert _score_color(49) == colors.HexColor("#DC2626")


class TestScoreBg:
    def test_high(self):
        assert _score_bg(80) == colors.HexColor("#DCFCE7")

    def test_medium(self):
        assert _score_bg(60) == colors.HexColor("#FEF9C3")

    def test_low(self):
        assert _score_bg(20) == colors.HexColor("#FEE2E2")


class TestLevelColor:
    def test_meets_requirement(self):
        assert _level_color(4, 3) == colors.HexColor("#16A34A")

    def test_one_below(self):
        assert _level_color(3, 4) == colors.HexColor("#CA8A04")

    def test_far_below(self):
        assert _level_color(1, 4) == colors.HexColor("#DC2626")


class TestLevelBg:
    def test_meets(self):
        assert _level_bg(5, 3) == colors.HexColor("#DCFCE7")

    def test_one_below(self):
        assert _level_bg(2, 3) == colors.HexColor("#FEF9C3")

    def test_far_below(self):
        assert _level_bg(1, 4) == colors.HexColor("#FEE2E2")


class TestLevelBarText:
    def test_full(self):
        result = _level_bar_text(5)
        assert "5/5" in result
        assert "\u2588" * 5 in result

    def test_partial(self):
        result = _level_bar_text(3)
        assert "3/5" in result
        assert "\u2588" * 3 in result
        assert "\u2591" * 2 in result

    def test_zero(self):
        result = _level_bar_text(0)
        assert "0/5" in result


class TestDrawRadarChart:
    def test_less_than_3_skills_returns_none(self):
        assert _draw_radar_chart([{"skill": "A", "required": 3, "demonstrated": 2}]) is None
        assert _draw_radar_chart([]) is None

    def test_3_skills_returns_drawing(self):
        skills = [
            {"skill": "Python", "required": 4, "demonstrated": 3},
            {"skill": "SQL", "required": 3, "demonstrated": 4},
            {"skill": "Docker", "required": 2, "demonstrated": 2},
        ]
        drawing = _draw_radar_chart(skills)
        assert drawing is not None

    def test_long_skill_names_truncated(self):
        skills = [
            {"skill": "VeryLongSkillNameHere", "required": 3, "demonstrated": 2},
            {"skill": "AnotherLongName12345", "required": 3, "demonstrated": 3},
            {"skill": "Short", "required": 3, "demonstrated": 3},
        ]
        drawing = _draw_radar_chart(skills)
        assert drawing is not None


# --- PDF generation ---

class TestGeneratePdf:
    def test_minimal_content(self):
        content = {"title": "John Doe", "position": "Dev", "scores": {}}
        pdf_bytes = generate_pdf(content)
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_full_content(self):
        content = {
            "title": "Jane Smith",
            "position": "Senior Backend",
            "company_name": "Acme Corp",
            "date": "01/04/2026",
            "matching_score": 78,
            "scores": {
                "global": 72,
                "technical": 80,
                "experience": 65,
                "communication": 70,
            },
            "skill_matrix": [
                {"skill": "Python", "required": 4, "demonstrated": 4, "motivation": 5, "evidence": "5 ans exp"},
                {"skill": "SQL", "required": 3, "demonstrated": 3, "motivation": 4, "evidence": "Projets DB"},
                {"skill": "Docker", "required": 3, "demonstrated": 2, "motivation": None, "evidence": "Usage basique"},
            ],
            "summary": "Bonne candidate avec solide experience backend.",
            "strengths": ["Maitrise Python", "Communication claire"],
            "areas_to_explore": ["Docker/K8s", "Leadership"],
            "key_quotes": ["Je suis passionnee par le backend"],
            "metadata": {
                "interview_duration": "6 min 07 s",
                "questions_count": 5,
                "disclaimer": "Rapport genere par IA.",
            },
        }
        pdf_bytes = generate_pdf(content)
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 1000

    def test_legacy_skills_without_matrix(self):
        content = {
            "title": "Legacy Candidate",
            "scores": {"global": 50},
            "skills_assessment": [
                {"skill": "Java", "level": "Intermediaire", "evidence": "2 ans"},
            ],
        }
        pdf_bytes = generate_pdf(content)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_empty_content(self):
        pdf_bytes = generate_pdf({})
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_scores_with_none_values(self):
        content = {
            "scores": {"global": 60, "technical": None, "experience": 40},
        }
        pdf_bytes = generate_pdf(content)
        assert pdf_bytes[:5] == b"%PDF-"
