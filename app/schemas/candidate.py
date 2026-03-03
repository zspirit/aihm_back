from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class CandidateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = None


class CandidateResponse(BaseModel):
    id: str
    position_id: str
    name: str
    email: str | None
    phone: str | None
    cv_file_path: str | None
    cv_score: float | None
    cv_score_explanation: dict | None
    cv_parsed_data: dict | None
    pipeline_status: str
    interview_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CandidateListResponse(BaseModel):
    id: str
    name: str
    email: str | None
    phone: str | None
    cv_score: float | None
    pipeline_status: str
    interview_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class CandidateGlobalListResponse(BaseModel):
    id: str
    name: str
    email: str | None
    phone: str | None
    cv_score: float | None
    pipeline_status: str
    interview_count: int = 0
    position_id: str
    position_title: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PaginatedCandidates(BaseModel):
    items: list[CandidateListResponse]
    total: int
    page: int
    page_size: int


class PaginatedCandidatesGlobal(BaseModel):
    items: list[CandidateGlobalListResponse]
    total: int
    page: int
    page_size: int


class CandidateComparisonItem(BaseModel):
    id: str
    name: str
    email: str | None
    phone: str | None
    cv_score: float | None
    cv_score_explanation: dict | None
    cv_parsed_data: dict | None
    pipeline_status: str
    interview: dict | None  # {duration_seconds, ended_at, attempt_number}
    scores: dict | None  # {global, technical, experience, communication}
    skill_scores: list | None  # [{skill, demonstrated, motivation, ...}]
    report_summary: str | None
