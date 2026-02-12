from datetime import datetime
from pydantic import BaseModel


class PositionCreate(BaseModel):
    title: str
    description: str = ""
    required_skills: list[str] = []
    seniority_level: str = "mid"
    custom_questions: list[str] = []
    deadline: datetime | None = None


class PositionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    required_skills: list[str] | None = None
    seniority_level: str | None = None
    custom_questions: list[str] | None = None
    status: str | None = None
    deadline: datetime | None = None


class PositionResponse(BaseModel):
    id: str
    title: str
    description: str
    required_skills: list
    seniority_level: str
    custom_questions: list
    status: str
    deadline: datetime | None
    created_by: str
    created_at: datetime
    candidate_count: int = 0

    model_config = {"from_attributes": True}


class PaginatedPositions(BaseModel):
    items: list[PositionResponse]
    total: int
    page: int
    page_size: int
