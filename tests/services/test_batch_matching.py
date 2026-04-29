"""Tests for batch_matching service helpers."""
import uuid
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from app.services.batch_matching import BATCH_SIZE


def test_batch_size_default():
    assert BATCH_SIZE == 20


def test_load_position_data_found():
    from app.services.batch_matching import _load_position_data

    position = MagicMock()
    position.title = "Dev Backend"
    position.description = "Build APIs"
    position.required_skills = ["Python", "FastAPI"]
    position.seniority_level = "mid"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = position

    db = MagicMock()
    db.execute.return_value = mock_result

    data = _load_position_data(db, uuid.uuid4(), uuid.uuid4())
    assert data == {
        "title": "Dev Backend",
        "description": "Build APIs",
        "required_skills": ["Python", "FastAPI"],
        "seniority_level": "mid",
    }


def test_load_position_data_not_found():
    from app.services.batch_matching import _load_position_data

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    db = MagicMock()
    db.execute.return_value = mock_result

    assert _load_position_data(db, uuid.uuid4(), uuid.uuid4()) is None


def test_load_candidates():
    from app.services.batch_matching import _load_candidates

    cid = uuid.uuid4()
    pid = uuid.uuid4()

    candidate = MagicMock()
    candidate.id = cid
    candidate.name = "Alice"
    candidate.email = "alice@test.com"
    candidate.cv_score = 85
    candidate.cv_parsed_data = {"skills": ["Python"]}

    position = MagicMock()
    position.id = pid
    position.title = "Dev"

    mock_result = MagicMock()
    mock_result.all.return_value = [(candidate, position)]

    db = MagicMock()
    db.execute.return_value = mock_result

    tid = uuid.uuid4()
    results = _load_candidates(db, tid)
    assert len(results) == 1
    assert results[0]["name"] == "Alice"
    assert results[0]["source_position_title"] == "Dev"
    assert results[0]["candidate_id"] == str(cid)


def test_load_candidates_no_position():
    from app.services.batch_matching import _load_candidates

    candidate = MagicMock()
    candidate.id = uuid.uuid4()
    candidate.name = "Bob"
    candidate.email = "bob@test.com"
    candidate.cv_score = 70
    candidate.cv_parsed_data = {}

    mock_result = MagicMock()
    mock_result.all.return_value = [(candidate, None)]

    db = MagicMock()
    db.execute.return_value = mock_result

    results = _load_candidates(db, uuid.uuid4())
    assert results[0]["source_position_title"] == "Vivier"
    assert results[0]["source_position_id"] is None
