from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator

from app.models.position import PositionLevel

UrgencyLevel = Literal["normal", "soon", "urgent", "late"]


def compute_urgency(
    sla_deadline: datetime | None,
    now: datetime | None = None,
) -> UrgencyLevel | None:
    """Dérive le niveau d'urgence d'un poste à partir de sa deadline SLA.

    Règles:
      - Pas de deadline → None (pas de SLA configuré)
      - now >= deadline → "late"
      - reste <= 2 jours → "urgent"
      - reste <= 7 jours → "soon"
      - sinon → "normal"

    `sla_deadline` peut être naive ou timezone-aware : on normalise sur UTC pour
    la comparaison afin d'éviter les surprises.
    """
    if sla_deadline is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    # Normalisation tz : on suppose UTC si naive (convention DB = TIMESTAMPTZ côté Postgres)
    if sla_deadline.tzinfo is None:
        sla_deadline = sla_deadline.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    remaining = sla_deadline - now
    if remaining.total_seconds() <= 0:
        return "late"
    remaining_days = remaining.total_seconds() / 86400
    if remaining_days <= 2:
        return "urgent"
    if remaining_days <= 7:
        return "soon"
    return "normal"


class SkillRequirement(BaseModel):
    name: str
    level_required: int = Field(3, ge=1, le=5, description="1=basic, 5=expert")
    weight: int = Field(2, ge=1, le=3, description="1=nice-to-have, 2=important, 3=critical")
    category: str = Field("technique")


def normalize_skills(skills: list) -> list[dict]:
    """Convert mixed list (strings and dicts) to list of SkillRequirement dicts.

    Handles backward compatibility: old format ["Python", "FastAPI"]
    becomes [{"name": "Python", ...}, {"name": "FastAPI", ...}] with defaults.
    """
    result = []
    for s in skills:
        if isinstance(s, str):
            result.append(SkillRequirement(name=s).model_dump())
        elif isinstance(s, dict):
            result.append(SkillRequirement(**s).model_dump())
        elif isinstance(s, SkillRequirement):
            result.append(s.model_dump())
        else:
            result.append(SkillRequirement(name=str(s)).model_dump())
    return result


class PositionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="", max_length=10000)
    required_skills: list = []
    seniority_level: str = "mid"
    level: PositionLevel | None = None
    sla_days: int | None = Field(None, ge=1, le=365)
    custom_questions: list[str] = []
    deadline: datetime | None = None
    auto_advance_threshold: int | None = Field(None, ge=0, le=100)
    auto_reject_threshold: int | None = Field(None, ge=0, le=100)

    @field_validator("required_skills", mode="before")
    @classmethod
    def normalize_required_skills(cls, v):
        return normalize_skills(v) if v else []


class PositionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    required_skills: list | None = None
    seniority_level: str | None = None
    level: PositionLevel | None = None
    sla_days: int | None = Field(None, ge=1, le=365)
    custom_questions: list[str] | None = None
    status: str | None = None
    deadline: datetime | None = None
    auto_advance_threshold: int | None = Field(None, ge=0, le=100)
    auto_reject_threshold: int | None = Field(None, ge=0, le=100)

    @field_validator("required_skills", mode="before")
    @classmethod
    def normalize_required_skills(cls, v):
        if v is None:
            return None
        return normalize_skills(v)


class PositionResponse(BaseModel):
    id: str
    title: str
    description: str
    required_skills: list[dict]
    seniority_level: str
    level: PositionLevel | None = None
    sla_days: int | None = None
    sla_deadline: datetime | None = None
    custom_questions: list
    status: str
    deadline: datetime | None
    auto_advance_threshold: int | None
    auto_reject_threshold: int | None
    created_by: str
    created_at: datetime
    candidate_count: int = 0

    @computed_field  # type: ignore[misc]
    @property
    def urgency_level(self) -> UrgencyLevel | None:
        """Champ dérivé : niveau d'urgence calculé à partir de sla_deadline et now().

        None si pas de SLA configuré. Se rafraîchit à chaque sérialisation (pas stocké).
        """
        return compute_urgency(self.sla_deadline)

    model_config = {"from_attributes": True}


class PaginatedPositions(BaseModel):
    items: list[PositionResponse]
    total: int
    page: int
    page_size: int


class PositionImportTextRequest(BaseModel):
    text: str


class PositionDuplicateRequest(BaseModel):
    title: str | None = None


class PositionOptimization(BaseModel):
    clarity_score: int  # 1-10
    clarity_suggestions: list[str]
    missing_skills: list[dict]  # [{name, category, level_required, reason}]
    inclusivity_score: int  # 1-10
    inclusivity_flags: list[str]
    competitiveness_score: int  # 1-10
    competitiveness_suggestions: list[str]
    suggested_questions: list[str]
    improved_description: str  # rewritten description
