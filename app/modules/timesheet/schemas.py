"""Pydantic response schemas for the Kairos module.

Field names are **camelCase on purpose** — they mirror the front contract
(`design-review/kairos/data.js` / `hub-data.js`) 1:1 so the UI plugs in without
any key transformation. Passthrough JSONB blobs (contact, contract, craTotals,
kpis, ...) are typed as ``dict`` and shaped in the serializers.
"""
from __future__ import annotations

from pydantic import BaseModel


# ---------- shared rows ----------

class ProjectRow(BaseModel):
    code: str
    name: str
    client: str          # client display name
    clientId: str        # client slug
    billing: str
    staffed: int
    tjm: float | None = None
    amount: float | None = None
    progress: int
    margin: int | None = None
    marginFlag: str | None = None
    endsIn: int | None = None
    budgetFlag: bool = False
    status: str


class ConsultantRow(BaseModel):
    id: str              # slug
    name: str
    initials: str | None = None
    role: str | None = None
    type: str
    project: str | None = None      # current project/client display
    occupation: int
    endsIn: int | None = None
    status: str
    exCandidate: bool = False


class CraMonthOut(BaseModel):
    month: str
    days: int | None = None
    amount: float
    status: str


class InvoiceOut(BaseModel):
    id: str              # invoice number
    clientId: str        # client slug
    projectId: str       # project code
    period: str
    amount: float
    status: str
    issued: str | None = None


class MissionOut(BaseModel):
    projectId: str | None = None   # project code or null (external)
    clientId: str | None = None    # client slug or null
    label: str | None = None
    role: str | None = None
    period: str | None = None
    current: bool = False
    days: int | None = None


# ---------- clients ----------

class ClientListItem(BaseModel):
    id: str              # slug
    name: str
    initials: str | None = None
    sector: str | None = None
    health: str
    location: str | None = None
    projectCount: int


class ClientDetail(BaseModel):
    id: str
    name: str
    initials: str | None = None
    sector: str | None = None
    since: str | None = None
    health: str
    location: str | None = None
    siret: str | None = None
    contact: dict | None = None
    projects: list[ProjectRow]
    consultants: list[ConsultantRow]
    invoices: list[InvoiceOut]


# ---------- projects ----------

class ProjectDetail(BaseModel):
    id: str              # = code
    code: str
    name: str
    clientId: str        # slug
    client: dict         # {id, name, initials, sector, health}
    billing: str
    tjm: float | None = None
    amount: float | None = None
    status: str
    progress: int
    margin: int | None = None
    marginFlag: str | None = None
    budgetFlag: bool = False
    start: str | None = None
    end: str | None = None
    endsIn: int | None = None
    daysSold: int | None = None
    daysConsumed: int | None = None
    desc: str | None = None
    contract: dict | None = None
    team: list[ConsultantRow]
    history: list[dict] = []     # toutes les missions sur le projet (présents + partis)
    craMonths: list[CraMonthOut]
    invoices: list[InvoiceOut]


# ---------- consultants ----------

class ConsultantDetail(BaseModel):
    id: str              # slug
    name: str
    initials: str | None = None
    role: str | None = None
    type: str
    seniority: str | None = None
    location: str | None = None
    dailyCost: float | None = None
    exCandidateId: str | None = None
    currentProjectId: str | None = None   # project code
    occupation: int
    status: str
    availableOn: str | None = None
    skills: list[str] = []
    missions: list[MissionOut]
    craTotals: dict | None = None


# ---------- hub ----------

class HubOut(BaseModel):
    period: dict
    narrative: str
    recommendations: list[dict]
    kpis: list[dict]
    projects: list[ProjectRow]
    consultants: list[ConsultantRow]
    toInvoice: list[dict]


# ---------- actions ----------

class GenerateInvoiceIn(BaseModel):
    projectCode: str
    period: str


class GenerateInvoiceOut(BaseModel):
    created: list[InvoiceOut]


# ---------- CRA détaillé (grille mensuelle jours/absences) ----------

class CraDay(BaseModel):
    d: int          # day of month
    dow: int        # 0=Sun .. 6=Sat (front parity)
    we: bool        # weekend
    wd: str         # French weekday letter (L/M/M/J/V/S/D)


class CraRef(BaseModel):
    code: str
    name: str
    client: str | None = None
    tjm: float | None = None
    kind: str       # 'mission' | 'absence'


class CraGridOut(BaseModel):
    consultantId: str
    month: str      # "2026-06"
    label: str      # "Juin 2026"
    days: list[CraDay]
    missions: list[CraRef]
    absences: list[CraRef]
    cells: dict[str, float]   # { "ACM-2024:12": 1, "CP:18": 0.5 }
    totals: dict              # { worked, absence, billable }
    # Workflow (EPIC E)
    status: str = "draft"            # draft | submitted | approved | rejected
    locked: bool = False             # True si soumis/validé → grille en lecture seule
    submittedAt: str | None = None
    rejectReason: str | None = None
    reopenRequested: bool = False    # demande de réouverction en attente (KAI-E6)


class CraGridIn(BaseModel):
    month: str                # "2026-06"
    cells: dict[str, float]


# ---------- CRUD inputs (camelCase = front forms) ----------

class ClientIn(BaseModel):
    name: str
    slug: str | None = None
    initials: str | None = None
    sector: str | None = None
    since: str | None = None
    health: str = "good"
    location: str | None = None
    siret: str | None = None
    contact: dict | None = None


class ProjectIn(BaseModel):
    name: str
    code: str | None = None
    clientId: str                      # client slug
    billing: str = "Régie"
    tjm: float | None = None
    amount: float | None = None
    status: str = "En cours"
    progress: int = 0
    margin: int | None = None
    marginFlag: str | None = None
    budgetFlag: bool = False
    start: str | None = None
    end: str | None = None
    endsIn: int | None = None
    daysSold: int | None = None
    daysConsumed: int | None = None
    desc: str | None = None
    contract: dict | None = None


class ConsultantIn(BaseModel):
    name: str
    slug: str | None = None
    initials: str | None = None
    role: str | None = None
    type: str = "Salarié"
    seniority: str | None = None
    location: str | None = None
    dailyCost: float | None = None
    occupation: int = 0
    status: str = "active"
    availableOn: str | None = None
    skills: list[str] = []
    currentProjectId: str | None = None   # project code


class InvoiceIn(BaseModel):
    number: str | None = None
    clientId: str                      # client slug
    projectId: str                     # project code
    period: str
    amount: float = 0
    status: str = "à émettre"
    issued: str | None = None


class DocumentOut(BaseModel):
    id: str
    docType: str
    title: str
    filename: str
    contentType: str | None = None
    size: int | None = None
    createdAt: str | None = None


class MyProfileIn(BaseModel):
    """Champs qu'un consultant peut éditer sur son propre profil."""
    location: str | None = None
    seniority: str | None = None
    skills: list[str] | None = None
    availableOn: str | None = None


# ---------- Workflow timesheet (EPIC E) ----------

class TimesheetRow(BaseModel):
    id: str
    consultantId: str
    consultantName: str
    initials: str | None = None
    month: str
    label: str
    status: str
    workedDays: float
    absenceDays: float
    submittedAt: str | None = None
    reviewedAt: str | None = None
    rejectReason: str | None = None
    reopenRequested: bool = False


class MonthIn(BaseModel):
    month: str


class RejectIn(BaseModel):
    reason: str | None = None


# ---------- Frais (EPIC G) ----------

class ExpenseIn(BaseModel):
    type: str                     # km|meal|lodging|transport|toll|parking|fuel|supplies|other
    date: str                     # "2026-06-12"
    description: str | None = None
    amount: float = 0
    km: float | None = None
    projectId: str | None = None  # project code


class ExpenseOut(BaseModel):
    id: str
    date: str
    month: str
    type: str
    typeLabel: str
    description: str | None = None
    amount: float
    km: float | None = None
    kmRate: float | None = None
    status: str
    hasReceipt: bool = False
    receiptId: str | None = None
    projectId: str | None = None
    consultantId: str | None = None
    consultantName: str | None = None
    initials: str | None = None
    submittedAt: str | None = None
    reviewedAt: str | None = None
    reimbursedAt: str | None = None
    rejectReason: str | None = None


# ---------- Factures consultant & 360° (EPIC H) ----------

class ConsultantInvoiceIn(BaseModel):
    month: str
    amount: float
    number: str | None = None
    issueDate: str | None = None


class ConsultantInvoiceOut(BaseModel):
    id: str
    number: str
    month: str
    amount: float
    status: str
    issueDate: str
    dueDate: str | None = None
    paidAt: str | None = None
    receivedAt: str | None = None
    hasDocument: bool = False
    documentId: str | None = None
    consultantId: str | None = None
    consultantName: str | None = None
    initials: str | None = None


class Summary360(BaseModel):
    workedDays: float = 0
    billable: float = 0       # CA estimé (jours × TJ)
    invoiced: float = 0       # total facturé
    collected: float = 0      # encaissé (payé)
    pendingPayment: float = 0
    spent: float = 0          # frais (hors refusés)
    reimbursed: float = 0     # frais remboursés


# ---------- Profil / dossier de compétence (EPIC J) ----------

class ProfileOut(BaseModel):
    name: str
    role: str | None = None
    type: str | None = None
    seniority: str | None = None
    location: str | None = None
    email: str | None = None
    headline: str | None = None
    summary: str | None = None
    skills: list[str] = []
    experiences: list[dict] = []      # {title, company, period, description}
    education: list[dict] = []        # {degree, school, year}
    certifications: list[dict] = []   # {name, issuer, year}
    languages: list[dict] = []        # {name, level}
    hasCv: bool = False
    cvId: str | None = None


class ProfileIn(BaseModel):
    headline: str | None = None
    summary: str | None = None
    skills: list[str] | None = None
    experiences: list[dict] | None = None
    education: list[dict] | None = None
    certifications: list[dict] | None = None
    languages: list[dict] | None = None


# ---------- Contacts (EPIC K) ----------

class MessageOut(BaseModel):
    id: str
    authorRole: str
    authorName: str | None = None
    body: str
    createdAt: str


class ContactOut(BaseModel):
    id: str
    subject: str
    status: str
    createdAt: str
    updatedAt: str
    consultantId: str | None = None
    consultantName: str | None = None
    initials: str | None = None
    messageCount: int = 0
    lastMessage: str | None = None


class ContactDetailOut(ContactOut):
    messages: list[MessageOut] = []


class ContactIn(BaseModel):
    subject: str
    message: str


class MessageIn(BaseModel):
    body: str


class ContactStatusIn(BaseModel):
    status: str   # open | in_progress | resolved


# ---------- Copilot consultant (EPIC L) ----------

class CopilotChatIn(BaseModel):
    message: str


class PendingAction(BaseModel):
    type: str
    label: str
    params: dict = {}


class CopilotMsgOut(BaseModel):
    id: str
    role: str            # user | assistant
    content: str
    createdAt: str
    tools: list[str] = []
    pendingAction: PendingAction | None = None


class CopilotChatOut(BaseModel):
    reply: str
    pendingAction: PendingAction | None = None
    tools: list[str] = []


class CopilotConfirmIn(BaseModel):
    type: str
    params: dict = {}
