from datetime import datetime

from pydantic import BaseModel


class ReportListItem(BaseModel):
    id: str
    candidate_id: str
    candidate_name: str
    interview_id: str
    position_id: str
    position_title: str
    global_score: float | None
    summary: str | None
    generated_at: datetime
    has_pdf: bool

    model_config = {"from_attributes": True}


class PaginatedReports(BaseModel):
    items: list[ReportListItem]
    total: int
    page: int
    page_size: int
