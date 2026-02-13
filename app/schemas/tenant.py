from datetime import datetime

from pydantic import BaseModel, Field


class TenantSettings(BaseModel):
    id: str
    name: str
    plan: str
    logo_url: str | None = None
    website: str | None = None
    primary_color: str = "#4F46E5"
    timezone: str = "Africa/Casablanca"
    data_retention_days: int = 180
    max_interview_duration: int = 600


class TenantSettingsUpdate(BaseModel):
    name: str | None = None
    logo_url: str | None = None
    website: str | None = None
    primary_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    timezone: str | None = None
    data_retention_days: int | None = Field(None, ge=30, le=730)
    max_interview_duration: int | None = Field(None, ge=120, le=1800)


class ComplianceInfo(BaseModel):
    legal_framework: str = "Loi 09-08 (Protection des donnees personnelles)"
    regulatory_body: str = "CNDP (Commission Nationale de controle de la protection des Donnees)"
    telecom_authority: str = "ANRT"
    data_retention_days: int
    consent_required: bool = True
    audit_logging: bool = True
    data_encryption: str = "AES-256 at rest, TLS 1.3 in transit"
    last_audit_action: datetime | None
    total_audit_entries: int
