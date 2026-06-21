"""Timesheet (Kairos) domain models.

Tables prefixed ``ts_``. Public identifiers are human slugs/codes (``acme``,
``ACM-2024``, ``mohammed``) exposed by the API; UUIDs stay internal. Date-like
fields are stored as display strings to match the front contract 1:1 for the
integration phase (normalisation to real dates is a follow-up).

See .claude/specs/KAIROS_INTEGRATION_PLAN.md and ADR-03/04/05.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TsClient(Base):
    __tablename__ = "ts_clients"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_ts_client_slug"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(255))
    initials: Mapped[str | None] = mapped_column(String(8), nullable=True)
    sector: Mapped[str | None] = mapped_column(String(120), nullable=True)
    since: Mapped[str | None] = mapped_column(String(20), nullable=True)
    health: Mapped[str] = mapped_column(String(20), default="good")  # good | watch | risk
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    siret: Mapped[str | None] = mapped_column(String(40), nullable=True)
    contact: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {name, role, email}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TsProject(Base):
    __tablename__ = "ts_projects"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_ts_project_code"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(255))
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_clients.id"))
    billing: Mapped[str] = mapped_column(String(40))  # Régie | Forfait | Régie plafonnée
    tjm: Mapped[float | None] = mapped_column(Float, nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="En cours")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    margin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    margin_flag: Mapped[str | None] = mapped_column(String(20), nullable=True)  # good | warning | danger
    budget_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ends_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_sold: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_consumed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    contract: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {type, signed, tjmAvg, ceiling, renewal, po}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TsConsultant(Base):
    __tablename__ = "ts_consultants"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_ts_consultant_slug"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    slug: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(255))
    initials: Mapped[str | None] = mapped_column(String(8), nullable=True)
    role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    type: Mapped[str] = mapped_column(String(40), default="Salarié")  # Salarié | Sous-traitant
    seniority: Mapped[str | None] = mapped_column(String(40), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    daily_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Platform bridges (loose coupling — see ADR-01/05)
    ex_candidate_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    party_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"), nullable=True)
    # Login link → espace consultant self-service
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    current_project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ts_projects.id"), nullable=True
    )
    occupation: Mapped[int] = mapped_column(Integer, default=0)  # %
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | ending | intercontrat
    available_on: Mapped[str | None] = mapped_column(String(20), nullable=True)
    skills: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)
    cra_totals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {booked, billable}
    # Dossier de compétence / profil LinkedIn-like (EPIC J) — réutilisable par AIHM
    profile_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TsMission(Base):
    """Consultant mission history (internal projects + external past missions)."""

    __tablename__ = "ts_missions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    consultant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_consultants.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_projects.id"), nullable=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_clients.id"), nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)  # external mission label
    role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    period: Mapped[str | None] = mapped_column(String(60), nullable=True)
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current: Mapped[bool] = mapped_column(Boolean, default=False)


class TsCraMonth(Base):
    """Validated CRA summary per project per month/milestone."""

    __tablename__ = "ts_cra_months"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_projects.id"))
    month: Mapped[str] = mapped_column(String(40))  # "Mai 2026" | "Jalon 2"
    days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="à facturer")  # facturé | à facturer | validé


class TsInvoice(Base):
    __tablename__ = "ts_invoices"
    __table_args__ = (UniqueConstraint("tenant_id", "number", name="uq_ts_invoice_number"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    number: Mapped[str] = mapped_column(String(40))  # F-2026-058
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_clients.id"))
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_projects.id"))
    period: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="à émettre")  # payée | envoyée | à émettre
    issued: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TsDocument(Base):
    """Document attaché à une entité (projet, client, consultant) : contrat, avenant, etc.

    Polymorphe via entity_type + entity_id (UUID interne). Fichier dans MinIO/S3
    (``file_path`` = "bucket/key"). Centralisation juridique (cf. ADR-03).
    """

    __tablename__ = "ts_documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    entity_type: Mapped[str] = mapped_column(String(20))   # project | client | consultant
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    doc_type: Mapped[str] = mapped_column(String(30), default="other")  # contract | amendment | po | nda | other
    title: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))    # "bucket/key"
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TsExpense(Base):
    """Note de frais d'un consultant (EPIC G) — Km, repas, transport, hébergement…

    Workflow draft→submitted→approved|rejected→reimbursed. Justificatif (PDF/scan)
    rattaché via ``receipt_document_id`` (TsDocument).
    """

    __tablename__ = "ts_expenses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    consultant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_consultants.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_projects.id"), nullable=True)
    expense_date: Mapped[date] = mapped_column(Date)
    month: Mapped[str] = mapped_column(String(7))  # "2026-06"
    type: Mapped[str] = mapped_column(String(30))  # km | meal | lodging | transport | toll | parking | fuel | supplies | other
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[float] = mapped_column(Float, default=0)        # € TTC (calculé pour km)
    km: Mapped[float | None] = mapped_column(Float, nullable=True)
    km_rate: Mapped[float | None] = mapped_column(Float, nullable=True)  # €/km appliqué
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|submitted|approved|rejected|reimbursed
    receipt_document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reimbursed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TsConsultantInvoice(Base):
    """Facture émise par un consultant/sous-traitant vers l'ESN (EPIC H).

    Workflow submitted→received→paid. PDF rattaché via ``document_id``.
    Échéance de paiement (``due_date``) typiquement émission + 45 j.
    """

    __tablename__ = "ts_consultant_invoices"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    consultant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_consultants.id"))
    number: Mapped[str] = mapped_column(String(40))
    month: Mapped[str] = mapped_column(String(7))
    amount: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="submitted")  # submitted|received|paid
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TsTimesheet(Base):
    """Timesheet mensuel d'un consultant — workflow de validation (EPIC E).

    Un par (consultant, mois). Statut draft→submitted→approved|rejected.
    Distinct des ``ts_cra_months`` (résumé par projet) ; les ``ts_time_entries``
    du consultant+mois se rattachent logiquement ici.
    """

    __tablename__ = "ts_timesheets"
    __table_args__ = (UniqueConstraint("tenant_id", "consultant_id", "month", name="uq_ts_timesheet"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    consultant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_consultants.id"))
    month: Mapped[str] = mapped_column(String(7))  # "2026-06"
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|submitted|approved|rejected
    worked_days: Mapped[float] = mapped_column(Float, default=0)
    absence_days: Mapped[float] = mapped_column(Float, default=0)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Demande de réouverction (révocation post-traitement) — KAI-E6
    reopen_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    reopen_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TsContactRequest(Base):
    """Demande de contact d'un consultant vers le management (EPIC K).

    Statut : open → in_progress → resolved. Conversation via TsContactMessage.
    """

    __tablename__ = "ts_contact_requests"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    consultant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_consultants.id"))
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | in_progress | resolved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TsContactMessage(Base):
    """Message dans le fil d'une demande de contact."""

    __tablename__ = "ts_contact_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_contact_requests.id"))
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    author_role: Mapped[str] = mapped_column(String(20))  # consultant | admin
    author_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TsTimeEntry(Base):
    """Daily CRA cell (detailed grid). Endpoint exposed in a follow-up (B7)."""

    __tablename__ = "ts_time_entries"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    consultant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_consultants.id"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_projects.id"), nullable=True)
    absence_code: Mapped[str | None] = mapped_column(String(8), nullable=True)  # CP|RTT|MAL|INT|FOR|SS
    entry_date: Mapped[date] = mapped_column(Date)
    month: Mapped[str] = mapped_column(String(40))
    value: Mapped[float] = mapped_column(Float, default=1.0)  # 1.0 | 0.5
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | timer | ai_suggested


class TsCopilotMessage(Base):
    """Historique de conversation du copilot consultant — scopé tenant + consultant.

    ``meta`` conserve la trace (outils appelés, action proposée) pour audit/affichage.
    """
    __tablename__ = "ts_copilot_messages"

    id: Mapped[uuid.UUID] = _uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"))
    consultant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("ts_consultants.id"))
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # {tools:[], pendingAction:{}}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
