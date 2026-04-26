from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class MatchSessionCreate(BaseModel):
    position_ids: list[str]
    candidate_ids: list[str] | None = None  # null = all candidates with parsed CV
    force_recompute: bool = False


class MatchSessionResponse(BaseModel):
    session_id: str
    total_pairs: int
    status: str


class MatchSessionStatus(BaseModel):
    session_id: str
    status: str
    total_pairs: int
    computed_pairs: int
    created_at: datetime
    completed_at: datetime | None = None


class MatrixScore(BaseModel):
    candidate_id: str
    position_id: str
    score: float
    reasons: dict | None = None


class MatrixResponse(BaseModel):
    positions: list[dict]
    candidates: list[dict]
    scores: list[MatrixScore]
    total_candidates: int


class AssignRequest(BaseModel):
    assignments: list[dict]  # [{candidate_id, position_id}]


class MatchCandidatesRequest(BaseModel):
    """POST /positions/{id}/match-candidates"""
    candidate_ids: list[str] | None = None  # null = tous les candidats avec CV parsé
    force_recompute: bool = False


class MatchPositionsRequest(BaseModel):
    """POST /candidates/{id}/match-positions"""
    position_ids: list[str] | None = None  # null = tous les postes actifs du tenant
    force_recompute: bool = False


class ConfirmApplicationsRequest(BaseModel):
    pairs: list[dict]  # [{candidate_id: str, position_id: str}]


class ConfirmApplicationsResponse(BaseModel):
    created: int
    skipped: int
