from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


class EnterpriseCreate(BaseModel):
    """Create a new enterprise."""
    name: str = Field(..., min_length=1, max_length=255, description="Enterprise name")
    industry: Optional[str] = Field(None, max_length=100, description="Industry type")
    domain: Optional[str] = Field(None, max_length=255, description="Domain (e.g., example.com)")
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=500)


class EnterpriseUpdate(BaseModel):
    """Update an enterprise."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    industry: Optional[str] = Field(None, max_length=100)
    domain: Optional[str] = Field(None, max_length=255)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, max_length=20)
    address: Optional[str] = Field(None, max_length=500)
    status: Optional[str] = Field(None, pattern="^(active|inactive|archived)$")


class EnterpriseResponse(BaseModel):
    """Response schema for an enterprise (minimal)."""
    id: UUID
    tenant_id: UUID
    name: str
    industry: Optional[str] = None
    domain: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class EnterpriseFull(EnterpriseResponse):
    """Response schema for an enterprise (full with metadata)."""
    created_by: UUID
    address: Optional[str] = None
