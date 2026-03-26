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
    # Scoring weights
    scoring_skills_weight: int = 50
    scoring_experience_weight: int = 30
    scoring_education_weight: int = 20
    # Compliance
    compliance_framework: str = "CNDP"
    compliance_config: dict | None = None


class TenantSettingsUpdate(BaseModel):
    name: str | None = None
    logo_url: str | None = None
    website: str | None = None
    primary_color: str | None = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    timezone: str | None = None
    data_retention_days: int | None = Field(None, ge=30, le=730)
    max_interview_duration: int | None = Field(None, ge=120, le=1800)
    # Scoring weights
    scoring_skills_weight: int | None = Field(None, ge=0, le=100)
    scoring_experience_weight: int | None = Field(None, ge=0, le=100)
    scoring_education_weight: int | None = Field(None, ge=0, le=100)
    # Compliance
    compliance_framework: str | None = None
    compliance_config: dict | None = None


# Compliance frameworks registry
COMPLIANCE_FRAMEWORKS = {
    "CNDP": {
        "legal_framework": "Loi 09-08 (Protection des donnees personnelles)",
        "regulatory_body": "CNDP (Commission Nationale de controle de la protection des Donnees)",
        "telecom_authority": "ANRT",
        "country": "Maroc",
    },
    "RGPD": {
        "legal_framework": "RGPD (Reglement General sur la Protection des Donnees)",
        "regulatory_body": "CNIL (Commission Nationale de l'Informatique et des Libertes)",
        "telecom_authority": "ARCEP",
        "country": "France / UE",
    },
    "GDPR": {
        "legal_framework": "GDPR (General Data Protection Regulation)",
        "regulatory_body": "ICO (Information Commissioner's Office)",
        "telecom_authority": "Ofcom",
        "country": "UK",
    },
    "PIPEDA": {
        "legal_framework": "PIPEDA (Personal Information Protection and Electronic Documents Act)",
        "regulatory_body": "OPC (Office of the Privacy Commissioner)",
        "telecom_authority": "CRTC",
        "country": "Canada",
    },
}


class ComplianceInfo(BaseModel):
    legal_framework: str = "Loi 09-08 (Protection des donnees personnelles)"
    regulatory_body: str = "CNDP (Commission Nationale de controle de la protection des Donnees)"
    telecom_authority: str = "ANRT"
    country: str = "Maroc"
    compliance_framework: str = "CNDP"
    data_retention_days: int
    consent_required: bool = True
    audit_logging: bool = True
    data_encryption: str = "AES-256 at rest, TLS 1.3 in transit"
    last_audit_action: datetime | None
    total_audit_entries: int
