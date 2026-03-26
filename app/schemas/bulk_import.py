from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class BulkImportResponse(BaseModel):
    import_id: str
    filename: str
    total_count: int
    status: str


class BulkImportBulkResponse(BaseModel):
    import_id: str
    total_count: int
    status: str
    source_type: str


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


# ---------------------------------------------------------------------------
# Preview / Confirm flow
# ---------------------------------------------------------------------------


class FilePreview(BaseModel):
    index: int
    filename: str
    candidate_name: str
    size_bytes: int
    status: Literal["new", "duplicate", "error"]
    error_message: str | None = None
    duplicate_info: dict | None = None  # {candidate_id, candidate_name, position_title, match_type}


class ImportPreviewResponse(BaseModel):
    import_id: str
    total_count: int
    new_count: int
    duplicate_count: int
    error_count: int
    files: list[FilePreview]


class FileDecision(BaseModel):
    index: int
    action: Literal["import", "overwrite", "skip"]


class ImportConfirmRequest(BaseModel):
    decisions: list[FileDecision]


class ImportConfirmResponse(BaseModel):
    import_id: str
    imported: int
    overwritten: int
    skipped: int
    errors: int
    status: str
