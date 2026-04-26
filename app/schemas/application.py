from datetime import datetime
from pydantic import BaseModel


class ApplicationResponse(BaseModel):
    id: str
    candidate_id: str
    position_id: str
    position_title: str | None = None
    match_score: float | None = None
    match_score_explanation: dict | None = None
    pipeline_status: str
    decision: str | None = None
    decision_note: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplicationCreate(BaseModel):
    position_id: str


class ApplicationDecision(BaseModel):
    decision: str  # "accepted" | "rejected" | "pending"
    note: str | None = None
