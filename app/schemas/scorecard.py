from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, field_validator


class ScorecardCreate(BaseModel):
    technical: int
    problem_solving: int
    communication: int
    behavioral: int
    notes: str | None = None

    @field_validator("technical", "problem_solving", "communication", "behavioral")
    @classmethod
    def score_range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError("Le score doit etre entre 1 et 5")
        return v


class ScorecardResponse(BaseModel):
    id: str
    evaluator_id: str
    technical: int
    problem_solving: int
    communication: int
    behavioral: int
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScorecardAggregated(BaseModel):
    technical_avg: float
    problem_solving_avg: float
    communication_avg: float
    behavioral_avg: float
    total_evaluators: int


class ScorecardListResponse(BaseModel):
    scorecards: list[ScorecardResponse]
    aggregated: ScorecardAggregated
