"""Async psychometric analysis — Phase 4.1.

Triggered by the POST /interviews/{id}/psychometrics endpoint after a row
is committed. Uses Claude to derive `traits_json` (Big-Five-ish) and a
coarse `turnover_risk` ('low' | 'medium' | 'high') from the 5 raw scores.

If ANTHROPIC_API_KEY is empty, the task falls back to a deterministic
rule-based estimate so the recruiter still sees something. This keeps
the feature usable in dev / on-prem without an LLM tier.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from celery import shared_task

from app.workers.base import get_sync_session

logger = structlog.get_logger()


# ─── Rule-based fallback ──────────────────────────────────────────────────────


def _fallback_traits(scores: dict[str, int]) -> dict[str, Any]:
    """Deterministic traits estimate. Keeps fields stable so the UI can
    render them even when no LLM is configured."""
    avg = sum(scores.values()) / len(scores)
    return {
        "openness": round(scores["score_problem_solving"] / 5, 2),
        "conscientiousness": round(avg / 5, 2),
        "extraversion": round(scores["score_communication"] / 5, 2),
        "agreeableness": round(scores["score_team_fit"] / 5, 2),
        "neuroticism": round((6 - scores["score_stress_handling"]) / 5, 2),
        "_source": "rule_based",
    }


def _fallback_risk(scores: dict[str, int]) -> str:
    """Stress + team_fit dominate retention odds in our internal cohort."""
    composite = scores["score_stress_handling"] + scores["score_team_fit"]
    if composite >= 8:
        return "low"
    if composite >= 6:
        return "medium"
    return "high"


# ─── LLM path ─────────────────────────────────────────────────────────────────


def _build_prompt(scores: dict[str, int]) -> str:
    """Render the LLM prompt. Built via f-string rather than .format() so the
    JSON example braces don't accidentally collide with placeholders."""
    return f"""You are an HR psychometrics analyst. Given five 1-5 scores
graded post-interview, estimate Big Five traits (each 0.0-1.0) and a
coarse retention risk ('low' | 'medium' | 'high').

Reply with ONLY a JSON object:
{{
  "openness": 0.0-1.0,
  "conscientiousness": 0.0-1.0,
  "extraversion": 0.0-1.0,
  "agreeableness": 0.0-1.0,
  "neuroticism": 0.0-1.0,
  "turnover_risk": "low|medium|high"
}}

Scores:
- communication: {scores['score_communication']}
- problem_solving: {scores['score_problem_solving']}
- team_fit: {scores['score_team_fit']}
- stress_handling: {scores['score_stress_handling']}
- leadership: {scores['score_leadership']}
"""


def _call_claude(scores: dict[str, int]) -> dict[str, Any] | None:
    """Returns None on any error or if not configured — caller falls back."""
    from app.core.config import get_settings
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=settings.ANTHROPIC_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": _build_prompt(scores)}],
        )
        text = response.content[0].text if response.content else ""
        # Extract first {...} JSON object — defensive against preamble.
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            return None
        parsed = json.loads(text[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        logger.warning("psychometrics_claude_failed", exc_info=True)
        return None


# ─── Celery task ──────────────────────────────────────────────────────────────


@shared_task(name="psychometrics.analyze", bind=True, max_retries=2)
def analyze_psychometric(self, assessment_id: str) -> None:
    """Fill traits_json + turnover_risk + analyzed_at on the row.

    Idempotent: if the row already has traits_json AND analyzed_at, skip.
    Errors don't propagate — the row stays usable with raw scores only.
    """
    from uuid import UUID

    from app.models.psychometric import PsychometricAssessment

    session = get_sync_session()
    try:
        assessment = session.get(PsychometricAssessment, UUID(assessment_id))
        if assessment is None:
            logger.warning("psychometrics_analyze_not_found", assessment_id=assessment_id)
            return

        if assessment.analyzed_at is not None:
            return  # already done

        scores = {
            "score_communication": assessment.score_communication,
            "score_problem_solving": assessment.score_problem_solving,
            "score_team_fit": assessment.score_team_fit,
            "score_stress_handling": assessment.score_stress_handling,
            "score_leadership": assessment.score_leadership,
        }

        llm_result = _call_claude(scores)
        if llm_result is not None:
            traits = {k: v for k, v in llm_result.items() if k != "turnover_risk"}
            risk = llm_result.get("turnover_risk")
            if risk not in ("low", "medium", "high"):
                risk = _fallback_risk(scores)
            assessment.traits_json = traits
            assessment.turnover_risk = risk
        else:
            assessment.traits_json = _fallback_traits(scores)
            assessment.turnover_risk = _fallback_risk(scores)

        assessment.analyzed_at = datetime.now(timezone.utc)
        session.commit()
        logger.info("psychometrics_analyzed", assessment_id=assessment_id, source=assessment.traits_json.get("_source", "claude"))
    except Exception as e:
        session.rollback()
        logger.warning("psychometrics_analyze_failed", assessment_id=assessment_id, error=str(e))
        # Don't retry on persistent failures — the row stays usable raw.
    finally:
        session.close()
