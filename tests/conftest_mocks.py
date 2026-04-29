"""Shared mock fixtures for external services (Claude API, Twilio, Whisper, MinIO)."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Claude API Mock ────────────────────────────────────────────────────────

MOCK_CV_PARSED = {
    "name": "Test Candidat",
    "email": "test@example.com",
    "phone": "+33612345678",
    "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
    "experience_years": 5,
    "experiences": [
        {
            "title": "Backend Developer",
            "company": "TechCorp",
            "duration": "3 ans",
            "description": "Developpement API REST, microservices, CI/CD",
        },
        {
            "title": "Junior Developer",
            "company": "StartupXYZ",
            "duration": "2 ans",
            "description": "Full-stack Python/React",
        },
    ],
    "education": [
        {"degree": "Master Informatique", "school": "Universite Paris", "year": "2018"}
    ],
    "languages": ["Francais", "Anglais"],
    "summary": "Developpeur backend 5 ans, specialise Python et APIs.",
    "quality_score": {
        "score": 68,
        "explanation": {
            "technical_depth": {"score": 72, "justification": "Competences demontrees en projet"},
            "experience_quality": {"score": 65, "justification": "Parcours coherent"},
            "education_relevance": {"score": 70, "justification": "Formation adaptee"},
            "cv_completeness": {"score": 65, "justification": "CV bien structure"},
        },
    },
}

MOCK_CV_SCORE = {
    "score": 75,
    "explanation": {
        "skills_match": {
            "score": 80,
            "matched": ["Python", "FastAPI"],
            "missing": ["Kubernetes"],
            "justification": "Bonne couverture des competences cles",
        },
        "experience_match": {"score": 70, "justification": "5 ans pertinents"},
        "education_match": {"score": 75, "justification": "Master pertinent"},
    },
}

MOCK_CV_QUALITY = {
    "score": 68,
    "explanation": {
        "technical_depth": {"score": 72, "justification": "Competences demontrees en projet"},
        "experience_quality": {"score": 65, "justification": "Parcours coherent"},
        "education_relevance": {"score": 70, "justification": "Formation adaptee"},
        "cv_completeness": {"score": 65, "justification": "CV bien structure"},
    },
}

MOCK_MATCHING_SCORE = {
    "score": 82,
    "reasons": {
        "skills_match": {"score": 85, "matched": ["Python", "FastAPI"], "missing": []},
        "experience_match": {"score": 80, "justification": "Experience pertinente"},
        "education_match": {"score": 78, "justification": "Formation adequate"},
    },
}

MOCK_QUESTIONS = [
    "Decrivez votre experience avec FastAPI.",
    "Comment gerez-vous les migrations de base de donnees ?",
    "Parlez-moi d'un bug complexe que vous avez resolu.",
]

MOCK_ANALYSIS = {
    "skills_extracted": ["Python", "FastAPI", "PostgreSQL"],
    "experience_examples": [{"skill": "Python", "context": "API REST", "level": "avance"}],
    "communication_indicators": {"clarity": 4, "structure": 4, "fluency": 3},
    "scores": {"technical": 75, "communication": 72, "overall": 74},
    "explanations": {"overall": "Candidat avec un bon profil technique"},
}

MOCK_OPTIMIZE_RESULT = {
    "scores": {"clarity": 8, "completeness": 7, "attractiveness": 7},
    "improved_description": "Description amelioree par IA",
    "suggestions": ["Ajouter les avantages", "Preciser le teletravail"],
    "missing_skills": [],
}


def _make_claude_response(content: dict | list | str):
    """Create a mock Anthropic message response."""
    if isinstance(content, (dict, list)):
        text = json.dumps(content, ensure_ascii=False)
    else:
        text = content
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=text)]
    mock_resp.stop_reason = "end_turn"
    return mock_resp


@pytest.fixture
def mock_claude():
    """Mock Anthropic client that returns configurable responses."""

    class ClaudeMocker:
        def __init__(self):
            self._responses = {}
            self._default = _make_claude_response(MOCK_CV_PARSED)
            self._call_count = 0

        def set_response(self, content):
            self._default = _make_claude_response(content)

        def set_responses(self, responses: list):
            """Set multiple responses returned in sequence."""
            self._responses = {i: _make_claude_response(r) for i, r in enumerate(responses)}

        def _create(self, **kwargs):
            self._call_count += 1
            idx = self._call_count - 1
            if idx in self._responses:
                return self._responses[idx]
            return self._default

    mocker = ClaudeMocker()

    with patch("app.workers.cv_processing.Anthropic") as mock_cls:
        instance = MagicMock()
        instance.messages.create = MagicMock(side_effect=mocker._create)
        mock_cls.return_value = instance
        yield mocker


@pytest.fixture
def mock_claude_api():
    """Mock Anthropic for API-level calls (async routes using asyncio.to_thread)."""

    def _make_mock(content):
        resp = _make_claude_response(content)
        return resp

    with patch("asyncio.get_event_loop") as mock_loop:
        mock_loop.return_value.run_in_executor = AsyncMock(
            return_value=_make_mock(MOCK_CV_PARSED)
        )
        yield mock_loop


# ─── MinIO / Storage Mock ───────────────────────────────────────────────────

@pytest.fixture
def mock_storage():
    """Mock MinIO S3 storage operations."""
    with patch("app.services.storage.s3_client") as mock_s3:
        mock_s3.put_object = MagicMock(return_value=None)
        mock_s3.get_object = MagicMock(
            return_value={"Body": MagicMock(read=MagicMock(return_value=b"%PDF-1.4 fake content"))}
        )
        mock_s3.head_bucket = MagicMock(return_value=None)
        mock_s3.create_bucket = MagicMock(return_value=None)

        with patch("app.services.storage.ensure_bucket", return_value=None):
            with patch("app.services.storage.upload_file", return_value="cvs/test/fake.pdf"):
                with patch("app.services.storage.download_file", return_value=b"%PDF-1.4 fake"):
                    yield mock_s3


# ─── Twilio Mock ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_twilio():
    """Mock Twilio client for telephony."""
    with patch("app.workers.telephony.Client") as mock_cls:
        instance = MagicMock()
        call = MagicMock()
        call.sid = "CA_FAKE_SID_123"
        call.status = "completed"
        instance.calls.create = MagicMock(return_value=call)
        mock_cls.return_value = instance
        yield instance


# ─── Celery Mock ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_celery():
    """Mock Celery task.delay() to run synchronously or skip."""
    mocks = {}
    task_paths = [
        "app.workers.cv_processing.process_cv",
        "app.workers.matching.compute_match_matrix",
        "app.workers.bulk_import.process_bulk_cv_import",
        "app.workers.notifications.send_consent_email",
        "app.workers.question_generation.generate_questions",
        "app.workers.telephony.initiate_call",
        "app.workers.report_generation.generate_report",
    ]
    patches = []
    for path in task_paths:
        p = patch(f"{path}.delay", MagicMock(return_value=None))
        mock = p.start()
        mocks[path.split(".")[-1]] = mock
        patches.append(p)

    yield mocks

    for p in patches:
        p.stop()


# ─── Whisper Mock ───────────────────────────────────────────────────────────

@pytest.fixture
def mock_whisper():
    """Mock faster-whisper transcription."""
    segments = [
        MagicMock(text="Bonjour, je suis candidat.", start=0.0, end=2.5),
        MagicMock(text="J'ai 5 ans d'experience en Python.", start=2.5, end=5.0),
    ]
    mock_model = MagicMock()
    mock_model.transcribe = MagicMock(
        return_value=(iter(segments), MagicMock(language="fr", language_probability=0.95))
    )

    with patch("app.workers.transcription.WhisperModel", return_value=mock_model):
        yield mock_model


# ─── Helper fixtures ────────────────────────────────────────────────────────

@pytest.fixture
def sample_cv_bytes():
    """Return fake PDF bytes for upload tests."""
    return b"%PDF-1.4 fake cv content for testing"


@pytest.fixture
def sample_position_data():
    """Return valid position creation data."""
    return {
        "title": "Developpeur Backend Python",
        "description": "Nous recherchons un dev backend Python/FastAPI.",
        "required_skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "seniority_level": "confirme",
        "auto_advance_threshold": 75,
        "auto_reject_threshold": 30,
    }


@pytest.fixture
def sample_candidate_data():
    """Return valid candidate data for direct creation."""
    return {
        "name": "Test Candidat",
        "email": "candidat@test.com",
        "phone": "+33612345678",
    }
