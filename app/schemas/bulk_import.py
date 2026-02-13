from datetime import datetime

from pydantic import BaseModel


class BulkImportResponse(BaseModel):
    import_id: str
    filename: str
    total_count: int
    status: str


class BulkImportDetail(BaseModel):
    id: str
    filename: str
    total_count: int
    processed_count: int
    success_count: int
    error_count: int
    status: str
    error_details: dict | None = None
    created_at: datetime
    completed_at: datetime | None = None


class BulkActionRequest(BaseModel):
    action: str  # "schedule" | "reject" | "delete"
    candidate_ids: list[str]


class BulkActionResult(BaseModel):
    candidate_id: str
    status: str  # "ok" | "error"
    reason: str | None = None


class BulkActionResponse(BaseModel):
    action: str
    total: int
    success: int
    failed: int
    details: list[BulkActionResult]
