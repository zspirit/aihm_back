import json
import uuid
from unittest.mock import MagicMock, patch

import pytest


def _make_position(required_skills=None, custom_questions=None):
    p = MagicMock()
    p.title = "Developpeur Python"
    p.description = "Poste de developpeur Python senior avec experience FastAPI."
    p.seniority_level = "senior"
    p.required_skills = ["Python", "FastAPI"] if required_skills is None else required_skills
    p.custom_questions = [] if custom_questions is None else custom_questions
    return p


def _make_candidate(cv_data=None):
    c = MagicMock()
    c.id = uuid.uuid4()
    c.position_id = uuid.uuid4()
    c.cv_parsed_data = cv_data or {"skills": ["Python", "Django"], "experience": "5 ans"}
    return c


VALID_QUESTIONS = [
    {
        "id": 1,
        "text": "Pouvez-vous decrire un projet FastAPI complexe ?",
        "category": "technique",
        "target_skill": "FastAPI",
        "expected_duration_seconds": 45,
        "evaluation_criteria": "Maitrise du framework",
    },
    {
        "id": 2,
        "text": "Parlez-moi d'une experience de travail en equipe.",
        "category": "soft_skills",
        "target_skill": "collaboration",
        "expected_duration_seconds": 45,
        "evaluation_criteria": "Capacite de collaboration",
    },
]
VALID_QUESTIONS_JSON = json.dumps(VALID_QUESTIONS)


# ── Helper functions ──────────────────────────────────────────────

class TestFormatSkillsForPrompt:
    def test_empty_skills(self):
        from app.workers.question_generation import _format_skills_for_prompt

        assert _format_skills_for_prompt([]) == "Aucune competence specifiee"
        assert _format_skills_for_prompt(None) == "Aucune competence specifiee"

    def test_string_skills(self):
        from app.workers.question_generation import _format_skills_for_prompt

        result = _format_skills_for_prompt(["Python", "FastAPI"])
        assert "Python" in result
        assert "FastAPI" in result
        assert "niveau requis: 3/5" in result
        assert "important" in result

    def test_dict_skills(self):
        from app.workers.question_generation import _format_skills_for_prompt

        skills = [{"name": "Python", "level_required": 4, "weight": 3, "category": "backend"}]
        result = _format_skills_for_prompt(skills)
        assert "Python" in result
        assert "niveau requis: 4/5" in result
        assert "critique" in result
        assert "[backend]" in result

    def test_dict_skills_defaults(self):
        from app.workers.question_generation import _format_skills_for_prompt

        result = _format_skills_for_prompt([{"name": "Go"}])
        assert "Go" in result
        assert "niveau requis: 3/5" in result
        assert "important" in result

    def test_other_type_skill(self):
        from app.workers.question_generation import _format_skills_for_prompt

        result = _format_skills_for_prompt([42])
        assert "42" in result

    def test_weight_labels(self):
        from app.workers.question_generation import _format_skills_for_prompt

        skills = [
            {"name": "A", "weight": 1},
            {"name": "B", "weight": 2},
            {"name": "C", "weight": 3},
        ]
        result = _format_skills_for_prompt(skills)
        assert "souhaitable" in result
        assert "important" in result
        assert "critique" in result


class TestGetCriticalSkills:
    def test_no_critical(self):
        from app.workers.question_generation import _get_critical_skills

        assert _get_critical_skills([{"name": "Python", "weight": 2}]) == []

    def test_with_critical(self):
        from app.workers.question_generation import _get_critical_skills

        skills = [
            {"name": "Python", "weight": 3},
            {"name": "SQL", "weight": 2},
            {"name": "Docker", "weight": 3},
        ]
        result = _get_critical_skills(skills)
        assert result == ["Python", "Docker"]

    def test_string_skills_ignored(self):
        from app.workers.question_generation import _get_critical_skills

        assert _get_critical_skills(["Python", "SQL"]) == []

    def test_empty(self):
        from app.workers.question_generation import _get_critical_skills

        assert _get_critical_skills([]) == []


# ── generate_interview_questions (unit function) ─────────────────

class TestGenerateInterviewQuestions:
    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_happy_path(self, mock_anthropic_cls, mock_settings):
        from app.workers.question_generation import generate_interview_questions

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=VALID_QUESTIONS_JSON)]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = generate_interview_questions(_make_candidate(), _make_position())

        assert len(result) == 2
        assert result[0]["category"] == "technique"
        assert result[1]["target_skill"] == "collaboration"
        mock_anthropic_cls.return_value.messages.create.assert_called_once()

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_json_in_code_block(self, mock_anthropic_cls, mock_settings):
        from app.workers.question_generation import generate_interview_questions

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=f"```json\n{VALID_QUESTIONS_JSON}\n```")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = generate_interview_questions(_make_candidate(), _make_position())
        assert len(result) == 2

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_generic_code_block(self, mock_anthropic_cls, mock_settings):
        from app.workers.question_generation import generate_interview_questions

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=f"```\n{VALID_QUESTIONS_JSON}\n```")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = generate_interview_questions(_make_candidate(), _make_position())
        assert len(result) == 2

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_invalid_json_fallback(self, mock_anthropic_cls, mock_settings):
        from app.workers.question_generation import generate_interview_questions

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="not valid json")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        position = _make_position()
        result = generate_interview_questions(_make_candidate(), position)

        # Should return 3 fallback questions
        assert len(result) == 3
        assert result[0]["category"] == "experience"
        assert position.title in result[0]["text"]

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_empty_content_fallback(self, mock_anthropic_cls, mock_settings):
        from app.workers.question_generation import generate_interview_questions

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = []  # empty content list
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = generate_interview_questions(_make_candidate(), _make_position())
        assert len(result) == 3  # fallback

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_fallback_question_structure(self, mock_anthropic_cls, mock_settings):
        from app.workers.question_generation import generate_interview_questions

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="garbage")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = generate_interview_questions(_make_candidate(), _make_position())

        for q in result:
            assert "id" in q
            assert "text" in q
            assert "category" in q
            assert "target_skill" in q
            assert "expected_duration_seconds" in q
            assert "evaluation_criteria" in q

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_with_dict_skills_and_critical(self, mock_anthropic_cls, mock_settings):
        from app.workers.question_generation import generate_interview_questions

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=VALID_QUESTIONS_JSON)]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        position = _make_position(required_skills=[
            {"name": "Python", "level_required": 4, "weight": 3, "category": "backend"},
            {"name": "SQL", "level_required": 3, "weight": 2, "category": "data"},
        ])

        result = generate_interview_questions(_make_candidate(), position)
        assert len(result) == 2

        # Verify the prompt included critical skill instruction
        call_args = mock_anthropic_cls.return_value.messages.create.call_args
        prompt_text = call_args[1]["messages"][0]["content"]
        assert "Python" in prompt_text
        assert "critique" in prompt_text.lower() or "critiques" in prompt_text.lower()


# ── generate_questions Celery task ───────────────────────────────

class TestGenerateQuestionsTask:
    def _setup_session(self, candidate, position):
        session = MagicMock()

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            return None

        session.get.side_effect = get_side_effect
        return session

    @patch("app.workers.cv_processing.get_sync_session")
    def test_happy_path(self, mock_get_session):
        from app.workers.question_generation import generate_questions

        candidate = _make_candidate()
        position = _make_position()
        session = self._setup_session(candidate, position)
        mock_get_session.return_value = session

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=VALID_QUESTIONS_JSON)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

            result = generate_questions(str(candidate.id))

        assert len(result) == 2
        session.commit.assert_called_once()
        session.close.assert_called_once()

    @patch("app.workers.cv_processing.get_sync_session")
    def test_candidate_not_found(self, mock_get_session):
        from app.workers.question_generation import generate_questions

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        result = generate_questions(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.cv_processing.get_sync_session")
    def test_position_not_found(self, mock_get_session):
        from app.workers.question_generation import generate_questions

        candidate = _make_candidate()
        session = MagicMock()
        mock_get_session.return_value = session

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Candidate":
                return candidate
            return None

        session.get.side_effect = get_side_effect

        result = generate_questions(str(candidate.id))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.cv_processing.get_sync_session")
    def test_claude_error_retries(self, mock_get_session):
        from app.workers.question_generation import generate_questions

        candidate = _make_candidate()
        position = _make_position()
        session = self._setup_session(candidate, position)
        mock_get_session.return_value = session

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_anthropic_cls.return_value.messages.create.side_effect = RuntimeError("Claude API down")

            with pytest.raises(RuntimeError):
                generate_questions(str(candidate.id))

        session.rollback.assert_called_once()
        session.close.assert_called_once()

    @patch("app.workers.cv_processing.get_sync_session")
    def test_empty_cv_data(self, mock_get_session):
        from app.workers.question_generation import generate_questions

        candidate = _make_candidate(cv_data={})
        position = _make_position()
        session = self._setup_session(candidate, position)
        mock_get_session.return_value = session

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=VALID_QUESTIONS_JSON)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

            result = generate_questions(str(candidate.id))

        assert len(result) == 2
        session.commit.assert_called_once()

    @patch("app.workers.cv_processing.get_sync_session")
    def test_empty_skills(self, mock_get_session):
        from app.workers.question_generation import generate_questions

        candidate = _make_candidate()
        position = _make_position(required_skills=[])
        session = self._setup_session(candidate, position)
        mock_get_session.return_value = session

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=VALID_QUESTIONS_JSON)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

            result = generate_questions(str(candidate.id))

            assert len(result) == 2
            # Verify prompt included "Aucune competence specifiee"
            call_args = mock_anthropic_cls.return_value.messages.create.call_args
            prompt = call_args[1]["messages"][0]["content"]
            assert "Aucune competence specifiee" in prompt
