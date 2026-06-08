"""Compliance endpoints — DPIA / bias monitoring / regulatory exports.

COMP-06 implementation. Lets each tenant export their own DPIA (Data
Protection Impact Assessment) as Markdown, generated from current tenant
configuration + live stats (counts, scoring thresholds, modules enabled).

Why per-tenant: the DPIA template is identical across tenants but the
*facts* differ (volumes, processing modules, retention). A static PDF
attached once at signup goes stale within a quarter. Generating on-demand
keeps it current.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_role
from app.models.audit_log import AuditLog
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.position import Position
from app.models.tenant import Tenant
from app.models.user import User

router = APIRouter(tags=["compliance"])


def _build_dpia_markdown(*, tenant: Tenant, stats: dict) -> str:
    """Render the DPIA Markdown body. Pure function — no DB access here.

    Stays in this module rather than a Jinja template because: (a) only one
    consumer, (b) we want it diff-reviewable next to the endpoint that emits
    it, (c) avoids dragging a templating dep for a single doc.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    weights = (
        f"Compétences {tenant.scoring_skills_weight or 50} % · "
        f"Expérience {tenant.scoring_experience_weight or 30} % · "
        f"Formation {tenant.scoring_education_weight or 20} %"
    )
    return f"""# Analyse d'impact relative à la protection des données (DPIA)

**Tenant** : {tenant.name}
**Généré le** : {today}
**Référence** : RGPD Art. 35 — Analyse d'impact obligatoire pour les
traitements à risque élevé (incluant l'évaluation systématique et automatisée
des personnes physiques par décisions automatisées au sens de l'Art. 22).

---

## 1. Description systématique du traitement

### 1.1 Finalités
- Aide au recrutement : tri assisté par IA des candidatures reçues,
  conduite d'entretiens téléphoniques structurés, génération de scorecards.
- Base légale : intérêt légitime du responsable de traitement (Art. 6.1.f
  RGPD) pour la phase de pré-sélection, exécution de mesures précontractuelles
  (Art. 6.1.b) pour la phase d'entretien.

### 1.2 Catégories de données traitées
- Données d'identification : nom, email, téléphone, adresse postale optionnelle.
- Données professionnelles : CV, expérience, formation, compétences déclarées.
- Données vocales : enregistrement de l'appel téléphonique IA (consentement
  explicite préalable obligatoire) et sa transcription textuelle.
- Données dérivées : scores IA, feedback, recommandations, logs d'audit.

### 1.3 Catégories de personnes concernées
- Candidats à un poste géré par le tenant.
- Utilisateurs internes du tenant (recruteurs, admins).

### 1.4 Sous-traitants
- Anthropic (USA) — modèles Claude pour scoring/conversation. Encadré par
  clauses contractuelles types (SCC) UE 2021.
- OpenAI / ElevenLabs — synthèse vocale facultative selon configuration
  TTS_PROVIDER (par défaut : edge-tts, sans transfert hors UE).
- Twilio — passerelle téléphonique (USA, SCC).
- Resend — envoi des emails transactionnels (USA, SCC).
- Hetzner — hébergement infrastructure (Allemagne, UE).

---

## 2. Mesures techniques et organisationnelles

### 2.1 Pondération du scoring CV pour le tenant
{weights}

### 2.2 Modules activés
- Module entretien IA téléphonique : actif par défaut.
- Module matching automatique : actif.
- Module sourcing : selon souscription tenant.

### 2.3 Volumétrie observée
- Candidats stockés : {stats['candidates']}
- Postes ouverts : {stats['positions_open']}
- Entretiens IA conduits (90 derniers jours) : {stats['interviews_90d']}
- Décisions IA loggées (90 derniers jours) : {stats['ai_decisions_90d']}

### 2.4 Conservation des données
- CV + scorecards : 24 mois max après dernière interaction
  (purge configurable au niveau tenant, conforme délibération CNIL-2018-038).
- Enregistrements audio + transcriptions : 6 mois max après l'entretien.
- Logs d'audit : 5 ans (obligation EU AI Act Art. 19).

### 2.5 Sécurité
- Chiffrement TLS 1.2+ en transit (Caddy + Let's Encrypt).
- Chiffrement au repos pour les OAuth tokens via Fernet.
- Isolation multi-tenant : tenant_id sur chaque table, filtre systématique
  au niveau service.
- Authentification : JWT + refresh, mot de passe bcrypt 12 rounds.

---

## 3. Décisions automatisées (Art. 22 RGPD)

### 3.1 Périmètre
Le système peut produire :
- Un score de pertinence du CV (0-100) par rapport à un poste.
- Une recommandation "écarter / approfondir / privilégier" dérivée du score.
- Une scorecard d'entretien post-appel.

### 3.2 Garanties humaines
- **Aucune décision finale n'est prise automatiquement.** Le passage à
  l'état `rejected` requiert toujours une action explicite d'un utilisateur
  authentifié (audit-loggué avec actor='human').
- Le candidat est informé en amont (page de consentement, EU AI Act Art. 50).
- Le candidat peut demander à tout moment :
  - Une explication écrite (endpoint public `/public/explanation/{{token}}`).
  - Une revue 100 % humaine de son dossier.
  - Le retrait de son consentement et l'effacement de ses données.

### 3.3 Traçabilité
Chaque décision IA produit un audit log avec :
- `actor='ai'`
- `model` + `model_version`
- `prompt_hash` (SHA-256 court) pour traçabilité du prompt employé
- `confidence_score`
- Résumé humain de la décision (champ `summary`)

---

## 4. Risques identifiés et mesures de mitigation

| Risque | Probabilité | Gravité | Mesure |
|---|---|---|---|
| Biais de scoring envers une catégorie protégée | Moyenne | Élevée | Bias monitoring trimestriel (COMP-13), prompt anti-discrimination explicite, garantie human-final |
| Fuite de CV via accès non autorisé | Faible | Élevée | Isolation multi-tenant, audit logs accès, MFA admin |
| Hallucination IA (compétence inventée) | Moyenne | Moyenne | Justifications obligatoires extraites du CV uniquement, exposition de la transcription brute |
| Réidentification à partir des transcriptions | Faible | Moyenne | Rétention 6 mois, pseudonymisation des exports |
| Atteinte à la disponibilité (perte de données) | Faible | Élevée | Backups Postgres quotidiens, MinIO réplication |

---

## 5. Conclusion

Sur la base de l'analyse ci-dessus, le tenant **{tenant.name}** considère
que les mesures techniques et organisationnelles mises en œuvre sont
proportionnées au risque et permettent de garantir un niveau de protection
adéquat des données personnelles traitées.

Une nouvelle DPIA sera générée à chaque changement majeur du modèle IA
(`model_version` bump), des sous-traitants ou de la finalité du traitement.

---

*Document généré automatiquement par AIHM — Compliance module v1.0.*
"""


@router.get("/compliance/dpia.md")
async def export_dpia_markdown(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Export DPIA Markdown for the caller's tenant.

    Admin-only. Returns the doc as `text/markdown` with a Content-Disposition
    that suggests a dated filename so admins can archive successive versions.
    """
    tenant_res = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_res.scalar_one_or_none()
    if not tenant:
        return Response(status_code=404, content="Tenant introuvable")

    # 90-day window for live stats
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=90)

    candidates_total = (await db.execute(
        select(func.count(Candidate.id)).where(Candidate.tenant_id == tenant.id)
    )).scalar() or 0
    positions_open = (await db.execute(
        select(func.count(Position.id)).where(
            Position.tenant_id == tenant.id,
            Position.status == "active",
        )
    )).scalar() or 0
    interviews_90d = (await db.execute(
        select(func.count(Interview.id)).where(
            Interview.tenant_id == tenant.id,
            Interview.created_at >= since,
        )
    )).scalar() or 0
    ai_decisions_90d = (await db.execute(
        select(func.count(AuditLog.id)).where(
            AuditLog.tenant_id == tenant.id,
            AuditLog.created_at >= since,
            AuditLog.details["actor"].astext == "ai",
        )
    )).scalar() or 0

    body = _build_dpia_markdown(
        tenant=tenant,
        stats={
            "candidates": candidates_total,
            "positions_open": positions_open,
            "interviews_90d": interviews_90d,
            "ai_decisions_90d": ai_decisions_90d,
        },
    )
    filename = f"DPIA_{tenant.name.replace(' ', '_')}_{datetime.now(timezone.utc):%Y%m%d}.md"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/compliance/bias-report.md")
async def export_bias_report_markdown(
    current_user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """COMP-13 — quarterly bias monitoring report (Markdown).

    Light-weight aggregator over `cv_score` in the past 90 days. Surfaces
    cohort means + flagged Δs without inferring protected attributes.
    """
    from app.services.bias_monitoring import compute_bias_report, render_report_markdown

    report = await compute_bias_report(db, tenant_id=current_user.tenant_id, days=90)
    body = render_report_markdown(report)
    filename = f"bias_report_{datetime.now(timezone.utc):%Y%m%d}.md"
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
