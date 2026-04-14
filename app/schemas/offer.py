from typing import Optional
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field


class OfferCreate(BaseModel):
    """Create a new offer from an application."""
    salary_min: Optional[float] = Field(None, ge=0, description="Minimum salary")
    salary_max: Optional[float] = Field(None, ge=0, description="Maximum salary")
    currency: str = Field("EUR", pattern="^[A-Z]{3}$", description="Currency code (EUR, MAD, USD)")
    contract_type: str = Field("permanent", pattern="^(permanent|contract|temp|internship)$")
    start_date: Optional[datetime] = None
    benefits: Optional[str] = Field(None, max_length=5000, description="Benefits description")
    additional_info: Optional[str] = Field(None, max_length=5000, description="Additional information")


class OfferUpdate(BaseModel):
    """Update an offer (only draft offers can be updated)."""
    salary_min: Optional[float] = Field(None, ge=0)
    salary_max: Optional[float] = Field(None, ge=0)
    currency: Optional[str] = Field(None, pattern="^[A-Z]{3}$")
    contract_type: Optional[str] = Field(None, pattern="^(permanent|contract|temp|internship)$")
    start_date: Optional[datetime] = None
    benefits: Optional[str] = Field(None, max_length=5000)
    additional_info: Optional[str] = Field(None, max_length=5000)


class OfferResponse(BaseModel):
    """Response schema for an offer (minimal)."""
    id: UUID
    tenant_id: UUID
    enterprise_id: UUID
    application_id: UUID
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: str
    contract_type: str
    start_date: Optional[datetime] = None
    status: str
    sent_at: Optional[datetime] = None
    signed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OfferSend(BaseModel):
    """Send offer to candidate."""
    expires_at: Optional[datetime] = Field(None, description="Offer expiration date")


class OfferSign(BaseModel):
    """Sign an offer (callback from e-signature provider)."""
    signature_token: str
    signed_by: UUID


class OfferReject(BaseModel):
    """Reject an offer."""
    rejection_reason: Optional[str] = Field(None, max_length=5000)
