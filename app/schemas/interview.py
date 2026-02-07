from datetime import datetime
from pydantic import BaseModel


class InterviewCreate(BaseModel):
    scheduled_at: datetime | None = None


class InterviewResponse(BaseModel):
    id: str
    candidate_id: str
    position_id: str
    status: str
    scheduled_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    duration_seconds: int | None
    questions_asked: dict | None
    attempt_number: int
    created_at: datetime

    model_config = {"from_attributes": True}


class TranscriptionResponse(BaseModel):
    id: str
    interview_id: str
    full_text: str
    segments: dict | None
    language_detected: str | None
    confidence_score: float | None

    model_config = {"from_attributes": True}


class AnalysisResponse(BaseModel):
    id: str
    interview_id: str
    skills_extracted: dict | None
    experience_examples: dict | None
    communication_indicators: dict | None
    scores: dict | None
    score_explanations: dict | None

    model_config = {"from_attributes": True}


class ReportResponse(BaseModel):
    id: str
    candidate_id: str
    interview_id: str
    content: dict | None
    pdf_file_path: str | None
    generated_at: datetime

    model_config = {"from_attributes": True}
