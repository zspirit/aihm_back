from datetime import datetime

from pydantic import BaseModel


class ConsentGrantRequest(BaseModel):
    granted: bool


class ConsentResponse(BaseModel):
    id: str
    candidate_id: str
    type: str
    granted: bool
    granted_at: datetime | None
    channel: str | None

    model_config = {"from_attributes": True}


class ConsentPageResponse(BaseModel):
    candidate_name: str
    company_name: str
    position_title: str
    consent_types: list[str]
    already_granted: bool
