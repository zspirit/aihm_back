"""Schemas email templates + logs — Phase 2.1."""
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

EmailType = Literal["invitation", "rejection", "offer_followup", "interview_reminder", "generic"]


class EmailTemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: EmailType = "generic"
    subject: str = Field(..., min_length=1, max_length=500)
    body_markdown: str = Field(..., min_length=1, max_length=20000)
    is_active: bool = True


class EmailTemplateUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    type: Optional[EmailType] = None
    subject: Optional[str] = Field(None, min_length=1, max_length=500)
    body_markdown: Optional[str] = Field(None, min_length=1, max_length=20000)
    is_active: Optional[bool] = None


class EmailTemplateResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    type: str
    subject: str
    body_markdown: str
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SendEmailFromTemplate(BaseModel):
    template_id: UUID
    # Variables additionnelles a injecter dans le rendu (au-dessus du candidate context auto-resolu)
    extra_variables: dict = Field(default_factory=dict)


class SendEmailDirect(BaseModel):
    to_email: EmailStr
    subject: str = Field(..., min_length=1, max_length=500)
    body_markdown: str = Field(..., min_length=1, max_length=20000)


class EmailLogResponse(BaseModel):
    id: UUID
    candidate_id: Optional[UUID] = None
    template_id: Optional[UUID] = None
    template_name: Optional[str] = None
    to_email: str
    subject: str
    body_rendered: str
    status: str
    provider: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime
    sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class TemplatePreview(BaseModel):
    """Preview rendered template avec variables sample."""

    subject: str
    body_rendered: str
    variables_used: list[str]
