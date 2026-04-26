"""Schemas pour les shortlists candidats."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ShortlistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    position_id: Optional[UUID] = None


class ShortlistUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    position_id: Optional[UUID] = None


class AddCandidateToShortlist(BaseModel):
    candidate_id: UUID
    note: Optional[str] = Field(None, max_length=1000)


class BulkAddCandidates(BaseModel):
    candidate_ids: list[UUID] = Field(..., min_length=1, max_length=200)


class ShortlistItemResponse(BaseModel):
    id: UUID
    candidate_id: UUID
    candidate_name: str
    candidate_email: Optional[str] = None
    cv_score: Optional[float] = None
    pipeline_status: Optional[str] = None
    note: Optional[str] = None
    position: int
    added_at: datetime
    added_by: UUID

    class Config:
        from_attributes = True


class ShortlistOwner(BaseModel):
    id: UUID
    full_name: Optional[str] = None
    email: str


class ShortlistResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    owner: ShortlistOwner
    position_id: Optional[UUID] = None
    position_title: Optional[str] = None
    name: str
    description: Optional[str] = None
    candidates_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ShortlistDetailResponse(ShortlistResponse):
    items: list[ShortlistItemResponse] = Field(default_factory=list)
