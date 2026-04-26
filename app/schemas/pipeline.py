from datetime import datetime

from pydantic import BaseModel, Field


PIPELINE_STATUSES = [
    "new",
    "cv_analyzed",
    "cv_scored",
    "interview_scheduled",
    "interview_completed",
    "evaluated",
    "shortlisted",
    "rejected",
    "hired",
]

PIPELINE_LABELS = {
    "new": "Nouveau",
    "cv_analyzed": "CV analysé",
    "cv_scored": "CV scoré",
    "interview_scheduled": "Entretien planifié",
    "interview_completed": "Entretien terminé",
    "evaluated": "Évalué",
    "shortlisted": "Présélectionné",
    "rejected": "Rejeté",
    "hired": "Recruté",
}


class PipelineCandidateItem(BaseModel):
    id: str
    name: str
    email: str | None
    position_title: str | None
    cv_score: float | None
    pipeline_status: str
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class PipelineColumn(BaseModel):
    status: str
    label: str
    candidates: list[PipelineCandidateItem]
    count: int


class PipelineBoardResponse(BaseModel):
    columns: list[PipelineColumn]


class PipelineMoveRequest(BaseModel):
    candidate_id: str
    new_status: str = Field(..., description="Target pipeline status")


class PipelineMoveResponse(BaseModel):
    id: str
    pipeline_status: str
    previous_status: str
