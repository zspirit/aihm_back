"""Skill schemas."""
from pydantic import BaseModel
from uuid import UUID


class SkillBase(BaseModel):
    name: str
    category: str | None = None
    description: str | None = None


class SkillCreate(SkillBase):
    pass


class SkillUpdate(SkillBase):
    pass


class SkillResponse(SkillBase):
    id: UUID
    tenant_id: UUID

    class Config:
        from_attributes = True


class SkillSearchResponse(SkillResponse):
    category: str | None = None


class SkillTrendingResponse(BaseModel):
    id: str
    name: str
    category: str | None = None
    mention_count: int
