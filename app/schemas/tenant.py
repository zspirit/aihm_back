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
