from pydantic import BaseModel


class MatchRequest(BaseModel):
    title: str = ""
    description: str = ""
    required_skills: list[str] = []
    seniority_level: str = "mid"
    limit: int = 20


class MatchResult(BaseModel):
    candidate_id: str
    name: str
    email: str | None = None
    source_position_id: str
    source_position_title: str
    cv_score: float | None = None
    match_score: float
    match_reasons: dict


class MatchResponse(BaseModel):
    matches: list[MatchResult]


class AddFromMatchRequest(BaseModel):
    candidate_ids: list[str]
