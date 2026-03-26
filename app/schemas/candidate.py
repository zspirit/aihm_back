from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class CandidateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)
    phone: str | None = None


class CandidateUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    tags: list | None = None
    notes: str | None = None


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
    viewed_at: datetime | None = None
    profile_score: float | None = None
    profile_score_explanation: dict | None = None
    profile_competencies: dict | None = None
    profile_suggestions: dict | None = None
    tags: list | None = None
    notes: str | None = None

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
    profile_score: float | None = None
    pipeline_status: str
    interview_count: int = 0
    position_id: str | None
    position_title: str
    created_at: datetime
    viewed_at: datetime | None = None

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


class CandidateInterviewResponse(BaseModel):
    id: str
    candidate_id: str
    position_id: str | None = None
    position_title: str | None = None
    status: str
    scheduled_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    duration_seconds: int | None = None
    attempt_number: int = 1
    # Analysis data
    analysis_score: float | None = None
    analysis_summary: str | None = None
    skill_scores: dict | None = None
    # Report
    has_report: bool = False
    report_id: str | None = None
    created_at: str


class InterviewStatsResponse(BaseModel):
    total_interviews: int
    completed: int
    completion_rate: float
    average_score: float | None
    average_duration_seconds: int | None
    best_score: float | None
    worst_score: float | None
    interviews_by_status: dict


class BenchmarkResponse(BaseModel):
    candidate_id: str
    profile_score: float | None
    profile_score_percentile: float | None
    skill_benchmarks: list[dict]
    total_candidates_in_pool: int


class TopPositionsResponse(BaseModel):
    positions: list[dict]
    computed: bool


class ScoringHistoryResponse(BaseModel):
    entries: list[dict]
