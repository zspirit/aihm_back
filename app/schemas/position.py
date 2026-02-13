from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class SkillRequirement(BaseModel):
    name: str
    level_required: int = Field(3, ge=1, le=5, description="1=basic, 5=expert")
    weight: int = Field(2, ge=1, le=3, description="1=nice-to-have, 2=important, 3=critical")
    category: str = Field("technique", pattern=r"^(technique|experience|soft_skills|langue)$")


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
    title: str
    description: str = ""
    required_skills: list = []
    seniority_level: str = "mid"
    custom_questions: list[str] = []
    deadline: datetime | None = None

    @field_validator("required_skills", mode="before")
    @classmethod
    def normalize_required_skills(cls, v):
        return normalize_skills(v) if v else []


class PositionUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    required_skills: list | None = None
    seniority_level: str | None = None
    custom_questions: list[str] | None = None
    status: str | None = None
    deadline: datetime | None = None

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
    custom_questions: list
    status: str
    deadline: datetime | None
    created_by: str
    created_at: datetime
    candidate_count: int = 0

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
