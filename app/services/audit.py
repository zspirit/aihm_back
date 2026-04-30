"""Audit logging service — records sensitive actions for compliance.

Conformité AI Act EU (High-Risk RH Systems, Art. 13 + Annexe III) :
- Toute décision IA exposée à l'utilisateur DOIT être loggée avec
  `details.actor='ai' + model + model_version + confidence_score`.
- Utiliser `log_ai_action()` — pas `log_action()` — pour ces décisions.
- L'endpoint `/candidates/{id}/ai-decisions` filtre `details.actor=='ai'`
  et expose ces logs au candidat (right-to-explanation).
"""

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def log_action(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    user_id: UUID | None = None,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    details: dict | None = None,
):
    """Write an audit log entry. Fire-and-forget, never raises.

    Pour les décisions **IA** (scoring, matching, screening, feedback IA, etc.)
    utiliser plutôt `log_ai_action()` qui force le contexte AI Act.
    """
    try:
        entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
        db.add(entry)
    except Exception:
        pass


async def log_ai_action(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    model: str,
    model_version: str | None = None,
    confidence_score: float | None = None,
    summary: str = "",
    extra: dict[str, Any] | None = None,
    user_id: UUID | None = None,
):
    """Audit log spécialisé pour les décisions IA.

    Force `details.actor='ai'` + le contexte modèle requis par l'AI Act
    (Art. 13 transparence + Annexe III audit trail).

    Args:
        action          : ex. 'cv_scoring', 'matching_run', 'screening_call_analysis'
        entity_type     : 'candidate', 'application', 'interview', ...
        entity_id       : str(uuid) de l'entité touchée
        model           : 'claude-sonnet-4-5', 'whisper-large-v3', ...
        model_version   : tag de version (date, hash, ou semver)
        confidence_score: 0.0 → 1.0 (None si pas applicable)
        summary         : résumé humain de la décision (visible candidat)
        extra           : dict libre (raw output, weights, scoring breakdown)
        user_id         : rare — utilisateur qui a TRIGGER l'IA, pas l'auteur
                          de la décision (qui est l'IA)
    """
    details: dict[str, Any] = {
        "actor": "ai",
        "model": model,
        "summary": summary,
    }
    if model_version is not None:
        details["model_version"] = model_version
    if confidence_score is not None:
        details["confidence_score"] = float(confidence_score)
    if extra:
        # Ne pas écraser les keys réservées si extra contient les mêmes
        for k, v in extra.items():
            if k not in details:
                details[k] = v

    await log_action(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
    )


def log_ai_action_sync(
    session,
    *,
    tenant_id: UUID,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    model: str,
    model_version: str | None = None,
    confidence_score: float | None = None,
    summary: str = "",
    extra: dict[str, Any] | None = None,
    user_id: UUID | None = None,
) -> None:
    """Variante sync de `log_ai_action` pour les workers Celery (sessions sync).

    Même contrat que `log_ai_action` async — voir doc de cette fonction.
    Fire-and-forget, never raises.
    """
    try:
        details: dict[str, Any] = {
            "actor": "ai",
            "model": model,
            "summary": summary,
        }
        if model_version is not None:
            details["model_version"] = model_version
        if confidence_score is not None:
            details["confidence_score"] = float(confidence_score)
        if extra:
            for k, v in extra.items():
                if k not in details:
                    details[k] = v

        entry = AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
        session.add(entry)
    except Exception:
        pass
