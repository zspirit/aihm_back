import json
import uuid
from unittest.mock import MagicMock, patch

import pytest


def _make_position(required_skills=None):
    p = MagicMock()
    p.title = "Developpeur Python"
    p.seniority_level = "mid"
    p.required_skills = required_skills or ["Python", "FastAPI"]
    return p


def _make_candidate(cv_data=None):
    c = MagicMock()
    c.cv_parsed_data = cv_data or {"skills": ["Python"]}
    c.pipeline_status = "interviewed"
    return c


def _make_transcription():
    t = MagicMock()
    t.full_text = "Q: Parlez-moi de votre experience Python. R: J'ai 5 ans d'experience."
    t.segments = {"q1": "experience Python"}
    t.interview_id = uuid.uuid4()
    return t


def _make_interview(candidate_id=None, position_id=None, tenant_id=None):
    i = MagicMock()
    i.id = uuid.uuid4()
    i.candidate_id = candidate_id or uuid.uuid4()
    i.position_id = position_id or uuid.uuid4()
    i.tenant_id = tenant_id or uuid.uuid4()
    return i


VALID_ANALYSIS_RESULT = {
    "skill_scores": [{"skill": "Python", "category": "technique", "level_required": 3, "demonstrated": 4, "motivation": 3, "evidence": "5 ans", "gap_analysis": "ok"}],
    "skills_extracted": [{"skill": "Python", "evidence": "5 ans", "level": "avance", "type": "demontre"}],
    "experience_examples": [{"situation": "projet", "task": "dev", "action": "code", "result": "livraison", "missing_star_elements": []}],
    "communication_indicators": {"clarity": {"score": 80, "evidence": "clair"}, "structure": {"score": 75, "evidence": "ok"}, "fluency": {"score": 85, "evidence": "fluide"}},
    "scores": {"technical": 80, "experience": 75, "communication": 78, "global": 78},
    "score_explanations": {"technical": "bon", "experience": "bon", "communication": "bon", "global": "bon", "unanswered_questions": []},
}
VALID_ANALYSIS_JSON = json.dumps(VALID_ANALYSIS_RESULT)


class TestFormatSkillsForPrompt:
    def test_empty_skills(self):
        from app.workers.analysis import _format_skills_for_prompt
        assert _format_skills_for_prompt(None) == "Aucune competence specifique listee."
        assert _format_skills_for_prompt([]) == "Aucune competence specifique listee."

    def test_string_skills(self):
        from app.workers.analysis import _format_skills_for_prompt
        result = _format_skills_for_prompt(["Python", "FastAPI"])
        assert "Python" in result
        assert "FastAPI" in result
        assert "niveau requis 3/5" in result

    def test_dict_skills(self):
        from app.workers.analysis import _format_skills_for_prompt
        skills = [{"name": "Python", "level_required": 4, "weight": 3, "category": "backend"}]
        result = _format_skills_for_prompt(skills)
        assert "Python" in result
        assert "niveau requis 4/5" in result
        assert "poids 3" in result
        assert "categorie backend" in result

    def test_dict_skills_defaults(self):
        from app.workers.analysis import _format_skills_for_prompt
        result = _format_skills_for_prompt([{"name": "Go"}])
        assert "niveau requis 3/5" in result
        assert "poids 2" in result

    def test_other_type_skills(self):
        from app.workers.analysis import _format_skills_for_prompt
        result = _format_skills_for_prompt([42])
        assert "42" in result


class TestBuildSkillScoresSchema:
    def test_empty(self):
        from app.workers.analysis import _build_skill_scores_schema
        assert _build_skill_scores_schema(None) == "[]"
        assert _build_skill_scores_schema([]) == "[]"

    def test_string_skills(self):
        from app.workers.analysis import _build_skill_scores_schema
        result = _build_skill_scores_schema(["Python", "SQL", "Docker"])
        assert "Python" in result
        assert "SQL" in result
        assert "Docker" not in result  # max 2 examples

    def test_dict_skills(self):
        from app.workers.analysis import _build_skill_scores_schema
        skills = [{"name": "React", "level_required": 4, "category": "frontend"}]
        result = _build_skill_scores_schema(skills)
        assert "React" in result
        assert '"level_required": 4' in result
        assert "frontend" in result


class TestRunAnalysis:
    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_happy_path(self, mock_anthropic_cls, mock_settings):
        from app.workers.analysis import run_analysis

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=VALID_ANALYSIS_JSON)]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = run_analysis(_make_transcription(), _make_position(), _make_candidate())

        assert result["scores"]["global"] == 78
        assert len(result["skills_extracted"]) == 1
        mock_anthropic_cls.return_value.messages.create.assert_called_once()

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_json_in_code_block(self, mock_anthropic_cls, mock_settings):
        from app.workers.analysis import run_analysis

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=f"```json\n{VALID_ANALYSIS_JSON}\n```")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = run_analysis(_make_transcription(), _make_position(), _make_candidate())
        assert result["scores"]["global"] == 78

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_generic_code_block(self, mock_anthropic_cls, mock_settings):
        from app.workers.analysis import run_analysis

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text=f"```\n{VALID_ANALYSIS_JSON}\n```")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = run_analysis(_make_transcription(), _make_position(), _make_candidate())
        assert result["scores"]["global"] == 78

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_invalid_json_fallback(self, mock_anthropic_cls, mock_settings):
        from app.workers.analysis import run_analysis

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = [MagicMock(text="not valid json at all")]
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = run_analysis(_make_transcription(), _make_position(), _make_candidate())
        assert result["scores"]["global"] == 0
        assert result["score_explanations"]["error"] == "Analysis failed"

    @patch("app.core.config.get_settings")
    @patch("anthropic.Anthropic")
    def test_empty_content_fallback(self, mock_anthropic_cls, mock_settings):
        from app.workers.analysis import run_analysis

        mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
        mock_msg = MagicMock()
        mock_msg.content = []
        mock_anthropic_cls.return_value.messages.create.return_value = mock_msg

        result = run_analysis(_make_transcription(), _make_position(), _make_candidate())
        assert result["scores"]["global"] == 0


class TestAnalyzeInterviewTask:
    def _setup_session(self, interview, candidate, position, transcription):
        session = MagicMock()

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            if name == "Candidate":
                return candidate
            if name == "Position":
                return position
            return None

        session.get.side_effect = get_side_effect
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = transcription
        session.execute.return_value = mock_scalar
        return session

    @patch("app.workers.cv_processing.get_sync_session")
    def test_happy_path(self, mock_get_session):
        from app.workers.analysis import analyze_interview

        interview_id = uuid.uuid4()
        interview = _make_interview()
        interview.id = interview_id
        candidate = _make_candidate()
        position = _make_position()
        transcription = _make_transcription()

        session = self._setup_session(interview, candidate, position, transcription)
        mock_get_session.return_value = session

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("app.workers.report_generation.generate_report") as mock_report:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_msg = MagicMock()
            mock_msg.content = [MagicMock(text=VALID_ANALYSIS_JSON)]
            mock_anthropic_cls.return_value.messages.create.return_value = mock_msg
            mock_report.delay = MagicMock()

            analyze_interview(str(interview_id))

        session.add.assert_called_once()
        session.commit.assert_called_once()
        assert candidate.pipeline_status == "evaluated"

    @patch("app.workers.cv_processing.get_sync_session")
    def test_interview_not_found(self, mock_get_session):
        from app.workers.analysis import analyze_interview

        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = None

        result = analyze_interview(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.cv_processing.get_sync_session")
    def test_no_transcription(self, mock_get_session):
        from app.workers.analysis import analyze_interview

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session
        session.get.return_value = interview

        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = None
        session.execute.return_value = mock_scalar

        result = analyze_interview(str(uuid.uuid4()))
        assert result is None
        session.commit.assert_not_called()

    @patch("app.workers.cv_processing.get_sync_session")
    def test_candidate_not_found(self, mock_get_session):
        from app.workers.analysis import analyze_interview

        interview = _make_interview()
        session = MagicMock()
        mock_get_session.return_value = session

        transcription = _make_transcription()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = transcription
        session.execute.return_value = mock_scalar

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            return None

        session.get.side_effect = get_side_effect

        result = analyze_interview(str(uuid.uuid4()))
        assert result is None

    @patch("app.workers.cv_processing.get_sync_session")
    def test_position_not_found(self, mock_get_session):
        from app.workers.analysis import analyze_interview

        interview = _make_interview()
        candidate = _make_candidate()
        session = MagicMock()
        mock_get_session.return_value = session

        transcription = _make_transcription()
        mock_scalar = MagicMock()
        mock_scalar.scalar_one_or_none.return_value = transcription
        session.execute.return_value = mock_scalar

        def get_side_effect(model_cls, uid):
            name = model_cls.__name__
            if name == "Interview":
                return interview
            if name == "Candidate":
                return candidate
            return None

        session.get.side_effect = get_side_effect

        result = analyze_interview(str(uuid.uuid4()))
        assert result is None

    @patch("app.workers.cv_processing.get_sync_session")
    def test_analysis_error_retries(self, mock_get_session):
        from app.workers.analysis import analyze_interview

        interview = _make_interview()
        candidate = _make_candidate()
        position = _make_position()
        transcription = _make_transcription()

        session = self._setup_session(interview, candidate, position, transcription)
        mock_get_session.return_value = session

        with patch("app.core.config.get_settings") as mock_settings, \
             patch("anthropic.Anthropic") as mock_anthropic_cls:
            mock_settings.return_value = MagicMock(ANTHROPIC_API_KEY="sk-test", ANTHROPIC_MODEL="claude-3")
            mock_anthropic_cls.return_value.messages.create.side_effect = RuntimeError("Claude API down")

            with pytest.raises(RuntimeError):
                analyze_interview(str(uuid.uuid4()))

        session.rollback.assert_called_once()
        session.close.assert_called_once()
