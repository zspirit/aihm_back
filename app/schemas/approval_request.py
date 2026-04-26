"""Schemas pour les approval requests."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

EntityType = Literal["offer", "application", "position", "candidate", "other"]
ApprovalStatus = Literal["pending", "approved", "rejected", "canceled"]


class ApprovalRequestCreate(BaseModel):
    approver_id: UUID
    entity_type: EntityType
    entity_id: UUID
    title: str = Field(..., min_length=1, max_length=200)
    rationale: Optional[str] = Field(None, max_length=5000)


class ApprovalDecision(BaseModel):
    """Approver decides : approved | rejected (avec raison optionnelle)."""

    decision: Literal["approved", "rejected"]
    decision_reason: Optional[str] = Field(None, max_length=5000)


class UserSummary(BaseModel):
    id: UUID
    full_name: Optional[str] = None
    email: str
    role: str


class ApprovalRequestResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    requester: UserSummary
    approver: UserSummary
    entity_type: str
    entity_id: UUID
    title: str
    rationale: Optional[str] = None
    status: str
    decision_reason: Optional[str] = None
    requested_at: datetime
    decided_at: Optional[datetime] = None

    class Config:
        from_attributes = True
