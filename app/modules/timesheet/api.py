"""Kairos (timesheet/delivery) REST API.

Serves the exact data shapes consumed by the design front
(`design-review/kairos/`). Public identifiers are slugs/codes; relationships are
resolved to those. Module-gated by the ``timesheet`` entitlement, tenant-scoped.

Loading is intentionally simple (load-all-per-tenant + compute in Python): an ESN
has tens of clients/projects/consultants, not thousands. Optimise later if needed.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tenant_id, require_module
from app.models.user import User
from app.modules.timesheet.models import (
    TsClient,
    TsConsultant,
    TsConsultantInvoice,
    TsContactMessage,
    TsContactRequest,
    TsCopilotMessage,
    TsCraMonth,
    TsDocument,
    TsExpense,
    TsInvoice,
    TsMission,
    TsProject,
    TsTimeEntry,
    TsTimesheet,
)
from app.modules.timesheet.pdf import build_timesheet_pdf
from app.services.storage import delete_file, download_file, upload_file
from app.modules.timesheet.schemas import (
    ClientDetail,
    ClientListItem,
    ClientIn,
    ConsultantDetail,
    ConsultantIn,
    ConsultantInvoiceIn,
    ConsultantInvoiceOut,
    ConsultantRow,
    ContactDetailOut,
    ContactIn,
    ContactOut,
    ContactStatusIn,
    DocumentOut,
    MessageIn,
    MessageOut,
    ExpenseIn,
    ExpenseOut,
    CopilotChatIn,
    CopilotChatOut,
    CopilotMsgOut,
    PendingAction,
    Summary360,
    CraDay,
    CraGridIn,
    CraGridOut,
    CraMonthOut,
    CraRef,
    GenerateInvoiceIn,
    GenerateInvoiceOut,
    HubOut,
    InvoiceIn,
    InvoiceOut,
    MissionOut,
    MonthIn,
    MyProfileIn,
    ProfileIn,
    ProfileOut,
    RejectIn,
    TimesheetRow,
    ProjectDetail,
    ProjectIn,
    ProjectRow,
)
from app.modules.timesheet.dossier import build_dossier_docx, build_dossier_pdf
from app.modules.timesheet.cv_parse import extract_cv_text, parse_cv_to_profile
from app.modules.timesheet.copilot import run_turn as copilot_run_turn, check_rate_limit as copilot_rate_limit

# CRA détaillé — catalogues
_MONTHS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
              "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]
_WD_FR = {0: "L", 1: "M", 2: "M", 3: "J", 4: "V", 5: "S", 6: "D"}  # Python Mon=0..Sun=6
_ABSENCES = [
    ("CP", "Congés payés"), ("RTT", "RTT"), ("MAL", "Maladie"),
    ("INT", "Intercontrat"), ("FOR", "Formation"), ("SS", "Sans solde"),
]
_ABS_CODES = {code for code, _ in _ABSENCES}

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/kairos",
    tags=["kairos"],
    dependencies=[require_module("timesheet")],
)


# ──────────────────────────── context ────────────────────────────

class _Ctx:
    def __init__(self, clients, projects, consultants, missions, cras, invoices):
        self.clients = clients
        self.projects = projects
        self.consultants = consultants
        self.missions = missions
        self.cras = cras
        self.invoices = invoices
        self.cli_by_id = {c.id: c for c in clients}
        self.proj_by_id = {p.id: p for p in projects}
        self.cons_by_id = {c.id: c for c in consultants}


async def _load_ctx(db: AsyncSession, tenant_id: UUID) -> _Ctx:
    async def fetch(model):
        res = await db.execute(select(model).where(model.tenant_id == tenant_id))
        return list(res.scalars().all())

    return _Ctx(
        await fetch(TsClient),
        await fetch(TsProject),
        await fetch(TsConsultant),
        await fetch(TsMission),
        await fetch(TsCraMonth),
        await fetch(TsInvoice),
    )


# ──────────────────────────── serializers ────────────────────────────

def _project_row(p: TsProject, ctx: _Ctx) -> ProjectRow:
    client = ctx.cli_by_id.get(p.client_id)
    staffed = sum(1 for c in ctx.consultants if c.current_project_id == p.id)
    return ProjectRow(
        code=p.code, name=p.name,
        client=client.name if client else "",
        clientId=client.slug if client else "",
        billing=p.billing, staffed=staffed, tjm=p.tjm, amount=p.amount,
        progress=p.progress, margin=p.margin, marginFlag=p.margin_flag,
        endsIn=p.ends_in, budgetFlag=p.budget_flag, status=p.status,
    )


def _consultant_row(c: TsConsultant, ctx: _Ctx) -> ConsultantRow:
    proj = ctx.proj_by_id.get(c.current_project_id) if c.current_project_id else None
    client = ctx.cli_by_id.get(proj.client_id) if proj else None
    return ConsultantRow(
        id=c.slug, name=c.name, initials=c.initials, role=c.role, type=c.type,
        project=(client.name if client else (proj.name if proj else None)),
        occupation=c.occupation, endsIn=(proj.ends_in if proj else None),
        status=c.status, exCandidate=c.ex_candidate_id is not None,
    )


def _invoice_out(inv: TsInvoice, ctx: _Ctx) -> InvoiceOut:
    cl = ctx.cli_by_id.get(inv.client_id)
    pr = ctx.proj_by_id.get(inv.project_id)
    return InvoiceOut(
        id=inv.number, clientId=cl.slug if cl else "", projectId=pr.code if pr else "",
        period=inv.period, amount=inv.amount, status=inv.status, issued=inv.issued,
    )


def _cra_out(m: TsCraMonth) -> CraMonthOut:
    return CraMonthOut(month=m.month, days=m.days, amount=m.amount, status=m.status)


def _mission_out(m: TsMission, ctx: _Ctx) -> MissionOut:
    pr = ctx.proj_by_id.get(m.project_id) if m.project_id else None
    cl = ctx.cli_by_id.get(m.client_id) if m.client_id else None
    return MissionOut(
        projectId=pr.code if pr else None, clientId=cl.slug if cl else None,
        label=m.label, role=m.role, period=m.period, current=bool(m.current), days=m.days,
    )


# ──────────────────────────── endpoints ────────────────────────────

@router.get("/clients", response_model=list[ClientListItem])
async def list_clients(
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _load_ctx(db, tenant_id)
    return [
        ClientListItem(
            id=c.slug, name=c.name, initials=c.initials, sector=c.sector,
            health=c.health, location=c.location,
            projectCount=sum(1 for p in ctx.projects if p.client_id == c.id),
        )
        for c in ctx.clients
    ]


@router.get("/clients/{slug}", response_model=ClientDetail)
async def get_client(
    slug: str,
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _load_ctx(db, tenant_id)
    client = next((c for c in ctx.clients if c.slug == slug), None)
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    projects = [p for p in ctx.projects if p.client_id == client.id]
    # Engaged consultants = union of mission history on this client (past included).
    engaged_ids = {m.consultant_id for m in ctx.missions if m.client_id == client.id}
    consultants = [c for c in ctx.consultants if c.id in engaged_ids]
    invoices = [i for i in ctx.invoices if i.client_id == client.id]

    return ClientDetail(
        id=client.slug, name=client.name, initials=client.initials, sector=client.sector,
        since=client.since, health=client.health, location=client.location, siret=client.siret,
        contact=client.contact,
        projects=[_project_row(p, ctx) for p in projects],
        consultants=[_consultant_row(c, ctx) for c in consultants],
        invoices=[_invoice_out(i, ctx) for i in invoices],
    )


@router.get("/projects", response_model=list[ProjectRow])
async def list_projects(
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _load_ctx(db, tenant_id)
    return [_project_row(p, ctx) for p in ctx.projects]


@router.get("/projects/{code}", response_model=ProjectDetail)
async def get_project(
    code: str,
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _load_ctx(db, tenant_id)
    p = next((x for x in ctx.projects if x.code == code), None)
    if not p:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    client = ctx.cli_by_id.get(p.client_id)
    team = [c for c in ctx.consultants if c.current_project_id == p.id]
    cras = [m for m in ctx.cras if m.project_id == p.id]
    invoices = [i for i in ctx.invoices if i.project_id == p.id]

    # Historique : toutes les missions sur ce projet (présents + partis)
    history = []
    for m in [x for x in ctx.missions if x.project_id == p.id]:
        cons = ctx.cons_by_id.get(m.consultant_id)
        history.append({
            "consultantId": cons.slug if cons else None,
            "name": cons.name if cons else "—",
            "initials": cons.initials if cons else None,
            "role": m.role, "period": m.period, "current": bool(m.current), "days": m.days,
        })
    history.sort(key=lambda h: (not h["current"], h["name"]))

    return ProjectDetail(
        id=p.code, code=p.code, name=p.name,
        clientId=client.slug if client else "",
        client={
            "id": client.slug, "name": client.name, "initials": client.initials,
            "sector": client.sector, "health": client.health,
        } if client else {},
        billing=p.billing, tjm=p.tjm, amount=p.amount, status=p.status,
        progress=p.progress, margin=p.margin, marginFlag=p.margin_flag, budgetFlag=p.budget_flag,
        start=p.start, end=p.end, endsIn=p.ends_in, daysSold=p.days_sold, daysConsumed=p.days_consumed,
        desc=p.description, contract=p.contract,
        team=[_consultant_row(c, ctx) for c in team],
        history=history,
        craMonths=[_cra_out(m) for m in cras],
        invoices=[_invoice_out(i, ctx) for i in invoices],
    )


@router.get("/consultants", response_model=list[ConsultantRow])
async def list_consultants(
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _load_ctx(db, tenant_id)
    return [_consultant_row(c, ctx) for c in ctx.consultants]


@router.get("/consultants/{slug}", response_model=ConsultantDetail)
async def get_consultant(
    slug: str,
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _load_ctx(db, tenant_id)
    c = next((x for x in ctx.consultants if x.slug == slug), None)
    if not c:
        raise HTTPException(status_code=404, detail="Consultant introuvable")

    proj = ctx.proj_by_id.get(c.current_project_id) if c.current_project_id else None
    missions = [m for m in ctx.missions if m.consultant_id == c.id]

    return ConsultantDetail(
        id=c.slug, name=c.name, initials=c.initials, role=c.role, type=c.type,
        seniority=c.seniority, location=c.location, dailyCost=c.daily_cost,
        exCandidateId=str(c.ex_candidate_id) if c.ex_candidate_id else None,
        currentProjectId=proj.code if proj else None,
        occupation=c.occupation, status=c.status, availableOn=c.available_on,
        skills=c.skills or [],
        missions=[_mission_out(m, ctx) for m in missions],
        craTotals=c.cra_totals,
    )


@router.get("/invoices", response_model=list[InvoiceOut])
async def list_invoices(
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _load_ctx(db, tenant_id)
    return [_invoice_out(i, ctx) for i in ctx.invoices]


@router.get("/hub", response_model=HubOut)
async def get_hub(
    period: str | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx = await _load_ctx(db, tenant_id)
    active_projects = [p for p in ctx.projects if p.status != "Clôturé"]

    total = len(ctx.consultants) or 1
    staffed = sum(1 for c in ctx.consultants if c.occupation > 0)
    intercontrat = [c for c in ctx.consultants if c.status == "intercontrat"]
    ending = [c for c in ctx.consultants if c.status == "ending"]
    tace = round(100 * staffed / total)

    to_invoice_cras = [m for m in ctx.cras if m.status in ("à facturer", "validé")]
    to_bill_total = sum((m.amount or 0) for m in to_invoice_cras)
    margins = [p.margin for p in active_projects if p.margin is not None]
    avg_margin = round(sum(margins) / len(margins)) if margins else 0
    over_budget = [p for p in active_projects if p.budget_flag]

    kpis = [
        {"key": "tace", "label": "Taux d'occupation (TACE)", "value": str(tace), "unit": "%",
         "delta": 0, "deltaUnit": "pp", "goodWhen": "up", "sub": f"{staffed} / {len(ctx.consultants)} consultants staffés"},
        {"key": "inter", "label": "Intercontrat", "value": str(len(intercontrat)), "unit": "cons.",
         "delta": 0, "deltaUnit": "", "goodWhen": "down", "sub": f"+{len(ending)} prévus sous 3 sem."},
        {"key": "tobill", "label": "À facturer", "value": str(round(to_bill_total / 1000)), "unit": "k€",
         "delta": 0, "deltaUnit": "%", "goodWhen": "up", "sub": f"{len(to_invoice_cras)} CRA validés non facturés", "money": True},
        {"key": "margin", "label": "Marge moyenne", "value": str(avg_margin), "unit": "%",
         "delta": 0, "deltaUnit": "pp", "goodWhen": "up", "sub": f"sur {len(active_projects)} projets actifs"},
    ]

    recommendations = []
    if intercontrat or ending:
        recommendations.append({"id": "staff", "icon": "user-search",
                                "label": f"Restaffer {len(intercontrat) + len(ending)} consultants", "tone": "warning"})
    if to_invoice_cras:
        recommendations.append({"id": "bill", "icon": "receipt",
                                "label": f"Générer {len(to_invoice_cras)} factures ({round(to_bill_total / 1000)} k€)", "tone": "success"})
    for p in over_budget:
        cl = ctx.cli_by_id.get(p.client_id)
        recommendations.append({"id": "budget", "icon": "alert-octagon",
                                "label": f"{cl.name if cl else p.code} : dépassement budget", "tone": "danger"})

    narrative_bits = []
    if ending:
        names = ", ".join(c.name.split()[0] for c in ending)
        narrative_bits.append(f"{len(ending)} consultant(s) entrent en intercontrat sous 3 semaines ({names}).")
    if to_bill_total:
        narrative_bits.append(f"{int(to_bill_total):,} € de CRA validés ne sont pas encore facturés.".replace(",", " "))
    if over_budget:
        narrative_bits.append(f"{len(over_budget)} projet(s) dépassent le budget jour.")
    narrative = " ".join(narrative_bits) or "Aucune alerte de pilotage cette période."

    to_invoice_rows = []
    for m in to_invoice_cras:
        pr = ctx.proj_by_id.get(m.project_id)
        cl = ctx.cli_by_id.get(pr.client_id) if pr else None
        to_invoice_rows.append({
            "client": cl.name if cl else "", "project": pr.code if pr else "",
            "period": m.month, "days": m.days, "amount": m.amount, "status": m.status,
        })

    return HubOut(
        period={"label": period or "Période courante"},
        narrative=narrative,
        recommendations=recommendations,
        kpis=kpis,
        projects=[_project_row(p, ctx) for p in active_projects],
        consultants=[_consultant_row(c, ctx) for c in ctx.consultants],
        toInvoice=to_invoice_rows,
    )


@router.post("/invoices/generate", response_model=GenerateInvoiceOut)
async def generate_invoices(
    body: GenerateInvoiceIn,
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an invoice (status 'à émettre') from a validated CRA month.

    Factur-X emission via the Plateforme Agréée (Iopole) is wired in v1.1.
    """
    ctx = await _load_ctx(db, tenant_id)
    project = next((p for p in ctx.projects if p.code == body.projectCode), None)
    if not project:
        raise HTTPException(status_code=404, detail="Projet introuvable")

    cra = next(
        (m for m in ctx.cras if m.project_id == project.id and m.month == body.period
         and m.status in ("à facturer", "validé")),
        None,
    )
    if not cra:
        raise HTTPException(status_code=400, detail="Aucun CRA à facturer pour cette période")

    seq = len(ctx.invoices) + 1
    invoice = TsInvoice(
        tenant_id=tenant_id,
        number=f"F-2026-{seq:03d}",
        client_id=project.client_id,
        project_id=project.id,
        period=cra.month,
        amount=cra.amount,
        status="à émettre",
        issued=None,
    )
    db.add(invoice)
    cra.status = "facturé"
    await db.flush()
    await db.refresh(invoice)
    await db.commit()

    return GenerateInvoiceOut(created=[_invoice_out(invoice, ctx)])


# ──────────────────────── CRA détaillé (grille mensuelle) ────────────────────────

def _parse_month(month: str) -> tuple[int, int]:
    try:
        y, m = month.split("-")
        return int(y), int(m)
    except Exception:
        raise HTTPException(status_code=400, detail="Paramètre 'month' invalide (attendu AAAA-MM)")


def _consultant_project_refs(cons: TsConsultant, ctx: _Ctx) -> list[CraRef]:
    # Seules les missions ACTIVES sont imputables (un intercontrat n'a aucune mission
    # facturable → il ne voit que les absences/INT). Cohérence avec le statut.
    pids = {m.project_id for m in ctx.missions if m.consultant_id == cons.id and m.project_id and m.current}
    if cons.current_project_id:
        pids.add(cons.current_project_id)
    refs = []
    for pid in pids:
        p = ctx.proj_by_id.get(pid)
        if not p:
            continue
        cl = ctx.cli_by_id.get(p.client_id)
        refs.append(CraRef(code=p.code, name=p.name, client=cl.name if cl else None, tjm=p.tjm, kind="mission"))
    refs.sort(key=lambda r: r.code)
    return refs


def _build_grid(cons: TsConsultant, month: str, ctx: _Ctx, entries) -> CraGridOut:
    year, mon = _parse_month(month)
    ndays = calendar.monthrange(year, mon)[1]
    days = []
    for d in range(1, ndays + 1):
        wd = date(year, mon, d).weekday()  # Mon=0..Sun=6
        days.append(CraDay(d=d, dow=(wd + 1) % 7, we=wd >= 5, wd=_WD_FR[wd]))

    cells: dict[str, float] = {}
    worked = absence = billable = 0.0
    for e in entries:
        if e.project_id:
            p = ctx.proj_by_id.get(e.project_id)
            code = p.code if p else str(e.project_id)
            cells[f"{code}:{e.entry_date.day}"] = e.value
            worked += e.value
            if p and p.tjm:
                billable += e.value * p.tjm
        elif e.absence_code:
            cells[f"{e.absence_code}:{e.entry_date.day}"] = e.value
            absence += e.value

    return CraGridOut(
        consultantId=cons.slug, month=month, label=f"{_MONTHS_FR[mon - 1]} {year}",
        days=days,
        missions=_consultant_project_refs(cons, ctx),
        absences=[CraRef(code=c, name=n, client="Absence", kind="absence") for c, n in _ABSENCES],
        cells=cells,
        totals={"worked": worked, "absence": absence, "billable": billable},
    )


async def _load_cons_and_entries(db, tenant_id, slug, month):
    ctx = await _load_ctx(db, tenant_id)
    cons = next((c for c in ctx.consultants if c.slug == slug), None)
    if not cons:
        raise HTTPException(status_code=404, detail="Consultant introuvable")
    res = await db.execute(
        select(TsTimeEntry).where(
            TsTimeEntry.tenant_id == tenant_id,
            TsTimeEntry.consultant_id == cons.id,
            TsTimeEntry.month == month,
        )
    )
    return ctx, cons, list(res.scalars().all())


@router.get("/consultants/{slug}/cra", response_model=CraGridOut)
async def get_consultant_cra(
    slug: str,
    month: str = Query(..., description="Mois au format AAAA-MM (ex. 2026-06)"),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ctx, cons, entries = await _load_cons_and_entries(db, tenant_id, slug, month)
    ts = await _ts_for(db, tenant_id, cons.id, month)
    return _apply_status(_build_grid(cons, month, ctx, entries), ts)


@router.put("/consultants/{slug}/cra", response_model=CraGridOut)
async def save_consultant_cra(
    slug: str,
    body: CraGridIn,
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace the month's daily entries for a consultant (idempotent upsert)."""
    ctx = await _load_ctx(db, tenant_id)
    cons = next((c for c in ctx.consultants if c.slug == slug), None)
    if not cons:
        raise HTTPException(status_code=404, detail="Consultant introuvable")

    year, mon = _parse_month(body.month)
    proj_by_code = {p.code: p for p in ctx.projects}

    await db.execute(
        delete(TsTimeEntry).where(
            TsTimeEntry.tenant_id == tenant_id,
            TsTimeEntry.consultant_id == cons.id,
            TsTimeEntry.month == body.month,
        )
    )

    for key, value in body.cells.items():
        if not value:
            continue
        code, _, day_s = key.partition(":")
        try:
            day = int(day_s)
            entry_date = date(year, mon, day)
        except (ValueError, TypeError):
            continue
        entry = TsTimeEntry(
            tenant_id=tenant_id, consultant_id=cons.id, month=body.month,
            entry_date=entry_date, value=float(value), source="manual",
        )
        if code in _ABS_CODES:
            entry.absence_code = code
        else:
            p = proj_by_code.get(code)
            if not p:
                continue  # unknown project code -> skip silently
            entry.project_id = p.id
        db.add(entry)

    await db.commit()

    res = await db.execute(
        select(TsTimeEntry).where(
            TsTimeEntry.tenant_id == tenant_id,
            TsTimeEntry.consultant_id == cons.id,
            TsTimeEntry.month == body.month,
        )
    )
    return _build_grid(cons, body.month, ctx, list(res.scalars().all()))


# ──────────────────────────── CRUD ────────────────────────────

def _slugify(s: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:60]
    return base or "item"


def _initials(name: str) -> str:
    return "".join(w[0] for w in name.split()[:2]).upper() or "?"


async def _uniq(db, model, field, tenant_id, value: str) -> str:
    col = getattr(model, field)
    base, i, candidate = value, 1, value
    while (await db.execute(select(model).where(model.tenant_id == tenant_id, col == candidate))).scalar_one_or_none():
        i += 1
        candidate = f"{base}-{i}"
    return candidate


async def _get(db, model, field, tenant_id, value):
    return (await db.execute(select(model).where(model.tenant_id == tenant_id, getattr(model, field) == value))).scalar_one_or_none()


# --- Clients ---

@router.post("/clients", response_model=ClientListItem, status_code=201)
async def create_client(body: ClientIn, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    slug = await _uniq(db, TsClient, "slug", tenant_id, body.slug or _slugify(body.name))
    c = TsClient(tenant_id=tenant_id, slug=slug, name=body.name, initials=body.initials or _initials(body.name),
                 sector=body.sector, since=body.since, health=body.health, location=body.location, siret=body.siret, contact=body.contact)
    db.add(c)
    await db.commit()
    return ClientListItem(id=c.slug, name=c.name, initials=c.initials, sector=c.sector, health=c.health, location=c.location, projectCount=0)


@router.put("/clients/{slug}", response_model=ClientListItem)
async def update_client(slug: str, body: ClientIn, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _get(db, TsClient, "slug", tenant_id, slug)
    if not c:
        raise HTTPException(404, "Client introuvable")
    for f, v in {"name": body.name, "initials": body.initials, "sector": body.sector, "since": body.since,
                 "health": body.health, "location": body.location, "siret": body.siret, "contact": body.contact}.items():
        if v is not None:
            setattr(c, f, v)
    await db.commit()
    n = (await db.execute(select(TsProject).where(TsProject.client_id == c.id))).scalars().all()
    return ClientListItem(id=c.slug, name=c.name, initials=c.initials, sector=c.sector, health=c.health, location=c.location, projectCount=len(n))


@router.delete("/clients/{slug}", status_code=204)
async def delete_client(slug: str, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _get(db, TsClient, "slug", tenant_id, slug)
    if not c:
        raise HTTPException(404, "Client introuvable")
    if (await db.execute(select(TsProject).where(TsProject.client_id == c.id))).scalars().first():
        raise HTTPException(400, "Ce client a des projets — supprimez-les d'abord.")
    await db.delete(c)
    await db.commit()


# --- Projects ---

@router.post("/projects", response_model=ProjectRow, status_code=201)
async def create_project(body: ProjectIn, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    client = await _get(db, TsClient, "slug", tenant_id, body.clientId)
    if not client:
        raise HTTPException(400, "Client introuvable")
    code = await _uniq(db, TsProject, "code", tenant_id, body.code or _slugify(body.name).upper())
    p = TsProject(tenant_id=tenant_id, code=code, name=body.name, client_id=client.id, billing=body.billing,
                  tjm=body.tjm, amount=body.amount, status=body.status, progress=body.progress, margin=body.margin,
                  margin_flag=body.marginFlag, budget_flag=body.budgetFlag, start=body.start, end=body.end,
                  ends_in=body.endsIn, days_sold=body.daysSold, days_consumed=body.daysConsumed, description=body.desc, contract=body.contract)
    db.add(p)
    await db.commit()
    return ProjectRow(code=p.code, name=p.name, client=client.name, clientId=client.slug, billing=p.billing, staffed=0,
                      tjm=p.tjm, amount=p.amount, progress=p.progress, margin=p.margin, marginFlag=p.margin_flag,
                      endsIn=p.ends_in, budgetFlag=p.budget_flag, status=p.status)


@router.put("/projects/{code}", response_model=ProjectRow)
async def update_project(code: str, body: ProjectIn, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _get(db, TsProject, "code", tenant_id, code)
    if not p:
        raise HTTPException(404, "Projet introuvable")
    client = await _get(db, TsClient, "slug", tenant_id, body.clientId)
    if not client:
        raise HTTPException(400, "Client introuvable")
    p.name, p.client_id, p.billing, p.tjm, p.amount, p.status, p.progress = body.name, client.id, body.billing, body.tjm, body.amount, body.status, body.progress
    p.margin, p.margin_flag, p.budget_flag, p.start, p.end, p.ends_in = body.margin, body.marginFlag, body.budgetFlag, body.start, body.end, body.endsIn
    p.days_sold, p.days_consumed, p.description, p.contract = body.daysSold, body.daysConsumed, body.desc, body.contract
    await db.commit()
    staffed = len((await db.execute(select(TsConsultant).where(TsConsultant.current_project_id == p.id))).scalars().all())
    return ProjectRow(code=p.code, name=p.name, client=client.name, clientId=client.slug, billing=p.billing, staffed=staffed,
                      tjm=p.tjm, amount=p.amount, progress=p.progress, margin=p.margin, marginFlag=p.margin_flag,
                      endsIn=p.ends_in, budgetFlag=p.budget_flag, status=p.status)


@router.delete("/projects/{code}", status_code=204)
async def delete_project(code: str, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    p = await _get(db, TsProject, "code", tenant_id, code)
    if not p:
        raise HTTPException(404, "Projet introuvable")
    # detach/clean dependents to avoid FK violations
    await db.execute(delete(TsCraMonth).where(TsCraMonth.project_id == p.id))
    await db.execute(delete(TsInvoice).where(TsInvoice.project_id == p.id))
    for m in (await db.execute(select(TsMission).where(TsMission.project_id == p.id))).scalars().all():
        m.project_id = None
    for c in (await db.execute(select(TsConsultant).where(TsConsultant.current_project_id == p.id))).scalars().all():
        c.current_project_id = None
    await db.flush()
    await db.delete(p)
    await db.commit()


# --- Consultants ---

@router.post("/consultants", response_model=ConsultantRow, status_code=201)
async def create_consultant(body: ConsultantIn, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    slug = await _uniq(db, TsConsultant, "slug", tenant_id, body.slug or _slugify(body.name))
    proj = await _get(db, TsProject, "code", tenant_id, body.currentProjectId) if body.currentProjectId else None
    c = TsConsultant(tenant_id=tenant_id, slug=slug, name=body.name, initials=body.initials or _initials(body.name),
                     role=body.role, type=body.type, seniority=body.seniority, location=body.location, daily_cost=body.dailyCost,
                     occupation=body.occupation, status=body.status, available_on=body.availableOn, skills=body.skills,
                     current_project_id=proj.id if proj else None)
    db.add(c)
    await db.commit()
    return ConsultantRow(id=c.slug, name=c.name, initials=c.initials, role=c.role, type=c.type,
                         project=proj.name if proj else None, occupation=c.occupation, endsIn=proj.ends_in if proj else None,
                         status=c.status, exCandidate=False)


@router.put("/consultants/{slug}", response_model=ConsultantRow)
async def update_consultant(slug: str, body: ConsultantIn, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _get(db, TsConsultant, "slug", tenant_id, slug)
    if not c:
        raise HTTPException(404, "Consultant introuvable")
    proj = await _get(db, TsProject, "code", tenant_id, body.currentProjectId) if body.currentProjectId else None
    c.name, c.initials, c.role, c.type, c.seniority, c.location = body.name, body.initials or c.initials, body.role, body.type, body.seniority, body.location
    c.daily_cost, c.occupation, c.status, c.available_on, c.skills = body.dailyCost, body.occupation, body.status, body.availableOn, body.skills
    c.current_project_id = proj.id if proj else None
    await db.commit()
    return ConsultantRow(id=c.slug, name=c.name, initials=c.initials, role=c.role, type=c.type,
                         project=proj.name if proj else None, occupation=c.occupation, endsIn=proj.ends_in if proj else None,
                         status=c.status, exCandidate=c.ex_candidate_id is not None)


@router.delete("/consultants/{slug}", status_code=204)
async def delete_consultant(slug: str, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _get(db, TsConsultant, "slug", tenant_id, slug)
    if not c:
        raise HTTPException(404, "Consultant introuvable")
    await db.execute(delete(TsMission).where(TsMission.consultant_id == c.id))
    await db.flush()
    await db.delete(c)
    await db.commit()


# --- Invoices ---

@router.post("/invoices", response_model=InvoiceOut, status_code=201)
async def create_invoice(body: InvoiceIn, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    client = await _get(db, TsClient, "slug", tenant_id, body.clientId)
    project = await _get(db, TsProject, "code", tenant_id, body.projectId)
    if not client or not project:
        raise HTTPException(400, "Client ou projet introuvable")
    seq = len((await db.execute(select(TsInvoice).where(TsInvoice.tenant_id == tenant_id))).scalars().all()) + 1
    number = await _uniq(db, TsInvoice, "number", tenant_id, body.number or f"F-2026-{seq:03d}")
    inv = TsInvoice(tenant_id=tenant_id, number=number, client_id=client.id, project_id=project.id,
                    period=body.period, amount=body.amount, status=body.status, issued=body.issued)
    db.add(inv)
    await db.commit()
    return InvoiceOut(id=inv.number, clientId=client.slug, projectId=project.code, period=inv.period, amount=inv.amount, status=inv.status, issued=inv.issued)


@router.put("/invoices/{number}", response_model=InvoiceOut)
async def update_invoice(number: str, body: InvoiceIn, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    inv = await _get(db, TsInvoice, "number", tenant_id, number)
    if not inv:
        raise HTTPException(404, "Facture introuvable")
    client = await _get(db, TsClient, "slug", tenant_id, body.clientId)
    project = await _get(db, TsProject, "code", tenant_id, body.projectId)
    if not client or not project:
        raise HTTPException(400, "Client ou projet introuvable")
    inv.client_id, inv.project_id, inv.period, inv.amount, inv.status, inv.issued = client.id, project.id, body.period, body.amount, body.status, body.issued
    await db.commit()
    return InvoiceOut(id=inv.number, clientId=client.slug, projectId=project.code, period=inv.period, amount=inv.amount, status=inv.status, issued=inv.issued)


@router.delete("/invoices/{number}", status_code=204)
async def delete_invoice(number: str, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    inv = await _get(db, TsInvoice, "number", tenant_id, number)
    if not inv:
        raise HTTPException(404, "Facture introuvable")
    await db.delete(inv)
    await db.commit()


# ──────────────────────────── Documents ────────────────────────────

_DOC_ENTITIES = {
    "projects": (TsProject, "code", "project"),
    "clients": (TsClient, "slug", "client"),
    "consultants": (TsConsultant, "slug", "consultant"),
}


async def _resolve_entity(db, tenant_id, entity_type: str, ref: str):
    spec = _DOC_ENTITIES.get(entity_type)
    if not spec:
        raise HTTPException(404, "Type d'entité inconnu")
    model, field, etype = spec
    obj = await _get(db, model, field, tenant_id, ref)
    if not obj:
        raise HTTPException(404, "Entité introuvable")
    return obj, etype


def _doc_out(d: TsDocument) -> DocumentOut:
    return DocumentOut(id=str(d.id), docType=d.doc_type, title=d.title, filename=d.filename,
                       contentType=d.content_type, size=d.size, createdAt=d.created_at.isoformat() if d.created_at else None)


@router.get("/{entity_type}/{ref}/documents", response_model=list[DocumentOut])
async def list_documents(entity_type: str, ref: str, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    obj, etype = await _resolve_entity(db, tenant_id, entity_type, ref)
    rows = (await db.execute(
        select(TsDocument).where(TsDocument.tenant_id == tenant_id, TsDocument.entity_type == etype, TsDocument.entity_id == obj.id)
        .order_by(TsDocument.created_at.desc())
    )).scalars().all()
    return [_doc_out(d) for d in rows]


@router.post("/{entity_type}/{ref}/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    entity_type: str, ref: str,
    file: UploadFile = File(...),
    docType: str = Form("other"),
    title: str | None = Form(None),
    tenant_id: UUID = Depends(get_tenant_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    obj, etype = await _resolve_entity(db, tenant_id, entity_type, ref)
    path = await upload_file(file, "kairos-docs", prefix=f"{etype}/{obj.id}")
    doc = TsDocument(
        tenant_id=tenant_id, entity_type=etype, entity_id=obj.id, doc_type=docType,
        title=title or file.filename or "Document", filename=file.filename or "document",
        file_path=path, content_type=file.content_type, uploaded_by=current_user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return _doc_out(doc)


@router.get("/documents/{doc_id}/download")
async def download_document(doc_id: UUID, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = (await db.execute(select(TsDocument).where(TsDocument.id == doc_id, TsDocument.tenant_id == tenant_id))).scalar_one_or_none()
    if not d:
        raise HTTPException(404, "Document introuvable")
    bucket, key = d.file_path.split("/", 1)
    data = download_file(bucket, key)
    return Response(content=data, media_type=d.content_type or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{d.filename}"'})


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: UUID, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    d = (await db.execute(select(TsDocument).where(TsDocument.id == doc_id, TsDocument.tenant_id == tenant_id))).scalar_one_or_none()
    if not d:
        raise HTTPException(404, "Document introuvable")
    try:
        delete_file(d.file_path)
    except Exception:
        logger.warning("doc_file_delete_failed", doc_id=str(doc_id))
    await db.delete(d)
    await db.commit()


# ──────────────────────────── Espace consultant (self-service) ────────────────────────────

async def _me_consultant(db: AsyncSession, current_user: User) -> TsConsultant:
    c = (await db.execute(
        select(TsConsultant).where(TsConsultant.tenant_id == current_user.tenant_id, TsConsultant.user_id == current_user.id)
    )).scalar_one_or_none()
    if not c:
        raise HTTPException(404, "Aucun profil consultant n'est lié à votre compte.")
    return c


def _consultant_detail(c: TsConsultant, ctx: _Ctx) -> ConsultantDetail:
    proj = ctx.proj_by_id.get(c.current_project_id) if c.current_project_id else None
    missions = [m for m in ctx.missions if m.consultant_id == c.id]
    return ConsultantDetail(
        id=c.slug, name=c.name, initials=c.initials, role=c.role, type=c.type,
        seniority=c.seniority, location=c.location, dailyCost=c.daily_cost,
        exCandidateId=str(c.ex_candidate_id) if c.ex_candidate_id else None,
        currentProjectId=proj.code if proj else None, occupation=c.occupation, status=c.status,
        availableOn=c.available_on, skills=c.skills or [],
        missions=[_mission_out(m, ctx) for m in missions], craTotals=c.cra_totals,
    )


@router.get("/me", response_model=ConsultantDetail)
async def my_profile(tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    return _consultant_detail(c, ctx)


@router.put("/me", response_model=ConsultantDetail)
async def update_my_profile(body: MyProfileIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    if body.location is not None:
        c.location = body.location
    if body.seniority is not None:
        c.seniority = body.seniority
    if body.skills is not None:
        c.skills = body.skills
    if body.availableOn is not None:
        c.available_on = body.availableOn
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _consultant_detail(c, ctx)


@router.get("/me/documents", response_model=list[DocumentOut])
async def my_documents(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    rows = (await db.execute(
        select(TsDocument).where(TsDocument.tenant_id == current_user.tenant_id, TsDocument.entity_type == "consultant", TsDocument.entity_id == c.id)
        .order_by(TsDocument.created_at.desc())
    )).scalars().all()
    return [_doc_out(d) for d in rows]


@router.post("/me/documents", response_model=DocumentOut, status_code=201)
async def upload_my_document(
    file: UploadFile = File(...),
    docType: str = Form("cv"),
    title: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    c = await _me_consultant(db, current_user)
    path = await upload_file(file, "kairos-docs", prefix=f"consultant/{c.id}")
    doc = TsDocument(
        tenant_id=current_user.tenant_id, entity_type="consultant", entity_id=c.id, doc_type=docType,
        title=title or file.filename or "Document", filename=file.filename or "document",
        file_path=path, content_type=file.content_type, uploaded_by=current_user.id,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return _doc_out(doc)


@router.get("/me/cra", response_model=CraGridOut)
async def my_cra(month: str = Query(..., description="AAAA-MM"), tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    entries = (await db.execute(
        select(TsTimeEntry).where(TsTimeEntry.tenant_id == tenant_id, TsTimeEntry.consultant_id == c.id, TsTimeEntry.month == month)
    )).scalars().all()
    ts = await _ts_for(db, tenant_id, c.id, month)
    return _apply_status(_build_grid(c, month, ctx, list(entries)), ts)


@router.put("/me/cra", response_model=CraGridOut)
async def save_my_cra(body: CraGridIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    existing = await _ts_for(db, tenant_id, c.id, body.month)
    if existing and existing.status in ("submitted", "approved"):
        raise HTTPException(400, "CRA verrouillé (soumis ou validé). Révoquez-le pour le modifier.")
    ctx = await _load_ctx(db, tenant_id)
    year, mon = _parse_month(body.month)
    proj_by_code = {p.code: p for p in ctx.projects}
    await db.execute(delete(TsTimeEntry).where(
        TsTimeEntry.tenant_id == tenant_id, TsTimeEntry.consultant_id == c.id, TsTimeEntry.month == body.month))
    for key, value in body.cells.items():
        if not value:
            continue
        code, _, day_s = key.partition(":")
        try:
            entry_date = date(year, mon, int(day_s))
        except (ValueError, TypeError):
            continue
        entry = TsTimeEntry(tenant_id=tenant_id, consultant_id=c.id, month=body.month, entry_date=entry_date, value=float(value), source="manual")
        if code in _ABS_CODES:
            entry.absence_code = code
        else:
            p = proj_by_code.get(code)
            if not p:
                continue
            entry.project_id = p.id
        db.add(entry)
    await db.commit()
    entries = (await db.execute(
        select(TsTimeEntry).where(TsTimeEntry.tenant_id == tenant_id, TsTimeEntry.consultant_id == c.id, TsTimeEntry.month == body.month)
    )).scalars().all()
    ts = await _ts_upsert_draft(db, tenant_id, c.id, body.month, list(entries), ctx)
    return _apply_status(_build_grid(c, body.month, ctx, list(entries)), ts)


# ──────────────────────────── Workflow timesheet (EPIC E) ────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _split_totals(cells: dict) -> tuple[float, float]:
    worked = sum(v for k, v in cells.items() if k.split(":")[0] not in _ABS_CODES)
    absence = sum(v for k, v in cells.items() if k.split(":")[0] in _ABS_CODES)
    return worked, absence


def _cells_from_entries(entries, ctx: _Ctx) -> dict:
    cells = {}
    for e in entries:
        if e.project_id:
            p = ctx.proj_by_id.get(e.project_id)
            code = p.code if p else str(e.project_id)
        elif e.absence_code:
            code = e.absence_code
        else:
            continue
        cells[f"{code}:{e.entry_date.day}"] = e.value
    return cells


def _validate_cells(cells: dict, year: int, mon: int) -> list[str]:
    """Règles de cohérence (KAI-D3) : ≤1 j/jour, pas de week-end, ≤ jours du mois."""
    errors: list[str] = []
    ndays = calendar.monthrange(year, mon)[1]
    weekend = {d for d in range(1, ndays + 1) if date(year, mon, d).weekday() >= 5}
    by_day: dict[int, float] = {}
    total = 0.0
    for key, v in cells.items():
        if not v or v <= 0:
            continue
        parts = key.split(":")
        if len(parts) != 2:
            continue
        try:
            day = int(parts[1])
        except ValueError:
            continue
        by_day[day] = by_day.get(day, 0.0) + v
        total += v
    over = sorted(d for d, t in by_day.items() if t > 1.0001)
    if over:
        errors.append(f"Plus d'1 jour saisi sur le(s) jour(s) : {', '.join(map(str, over))} (max 1 / jour).")
    we = sorted(d for d in by_day if d in weekend)
    if we:
        errors.append(f"Saisie le week-end : jour(s) {', '.join(map(str, we))} — non autorisé.")
    if total > ndays:
        errors.append(f"Total {total:g} j supérieur aux {ndays} jours du mois.")
    # Complétude : chaque jour ouvré doit totaliser exactement 1 jour.
    incomplete = [d for d in range(1, ndays + 1) if d not in weekend and by_day.get(d, 0.0) < 1.0 - 1e-6]
    if incomplete:
        shown = ", ".join(map(str, incomplete[:8]))
        errors.append(
            f"{len(incomplete)} jour(s) ouvré(s) incomplet(s) (ex. {shown}{'…' if len(incomplete) > 8 else ''}) "
            "— chaque jour ouvré doit totaliser 1 jour.")
    return errors


async def _ts_for(db, tenant_id, consultant_id, month) -> TsTimesheet | None:
    return (await db.execute(
        select(TsTimesheet).where(
            TsTimesheet.tenant_id == tenant_id, TsTimesheet.consultant_id == consultant_id, TsTimesheet.month == month)
    )).scalar_one_or_none()


async def _ts_upsert_draft(db, tenant_id, consultant_id, month, entries, ctx) -> TsTimesheet:
    """Après une sauvegarde de saisie : garantit un timesheet (draft) et met à jour les totaux.
    Un CRA rejeté repasse en draft à l'édition."""
    worked, absence = _split_totals(_cells_from_entries(entries, ctx))
    ts = await _ts_for(db, tenant_id, consultant_id, month)
    if ts is None:
        ts = TsTimesheet(tenant_id=tenant_id, consultant_id=consultant_id, month=month, status="draft")
        db.add(ts)
    elif ts.status == "rejected":
        ts.status = "draft"
        ts.reject_reason = None
    ts.worked_days = worked
    ts.absence_days = absence
    ts.updated_at = _now_utc()
    await db.commit()
    return ts


def _apply_status(grid: CraGridOut, ts: TsTimesheet | None) -> CraGridOut:
    if ts:
        grid.status = ts.status
        grid.locked = ts.status in ("submitted", "approved")
        grid.submittedAt = ts.submitted_at.isoformat() if ts.submitted_at else None
        grid.rejectReason = ts.reject_reason
        grid.reopenRequested = bool(ts.reopen_requested)
    return grid


def _ts_row(ts: TsTimesheet, ctx: _Ctx) -> TimesheetRow:
    c = ctx.cons_by_id.get(ts.consultant_id)
    year, mon = _parse_month(ts.month)
    return TimesheetRow(
        id=str(ts.id), consultantId=c.slug if c else "", consultantName=c.name if c else "—",
        initials=c.initials if c else None, month=ts.month, label=f"{_MONTHS_FR[mon - 1]} {year}",
        status=ts.status, workedDays=ts.worked_days, absenceDays=ts.absence_days,
        submittedAt=ts.submitted_at.isoformat() if ts.submitted_at else None,
        reviewedAt=ts.reviewed_at.isoformat() if ts.reviewed_at else None, rejectReason=ts.reject_reason,
        reopenRequested=bool(ts.reopen_requested),
    )


@router.post("/me/cra/submit", response_model=CraGridOut)
async def submit_my_cra(body: MonthIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    year, mon = _parse_month(body.month)
    entries = list((await db.execute(
        select(TsTimeEntry).where(TsTimeEntry.tenant_id == tenant_id, TsTimeEntry.consultant_id == c.id, TsTimeEntry.month == body.month)
    )).scalars().all())
    cells = _cells_from_entries(entries, ctx)
    errors = _validate_cells(cells, year, mon)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    ts = await _ts_for(db, tenant_id, c.id, body.month)
    if ts is None:
        ts = TsTimesheet(tenant_id=tenant_id, consultant_id=c.id, month=body.month)
        db.add(ts)
    if ts.status == "approved":
        raise HTTPException(400, "Ce CRA est déjà validé.")
    ts.worked_days, ts.absence_days = _split_totals(cells)
    ts.status = "submitted"
    ts.submitted_at = _now_utc()
    ts.reject_reason = None
    await db.commit()
    return _apply_status(_build_grid(c, body.month, ctx, entries), ts)


async def _me_grid(db, tenant_id, c, month, ts):
    entries = list((await db.execute(
        select(TsTimeEntry).where(TsTimeEntry.tenant_id == tenant_id, TsTimeEntry.consultant_id == c.id, TsTimeEntry.month == month)
    )).scalars().all())
    ctx = await _load_ctx(db, tenant_id)
    return _apply_status(_build_grid(c, month, ctx, entries), ts)


@router.post("/me/cra/revoke", response_model=CraGridOut)
async def revoke_my_cra(body: MonthIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Règle de gestion (KAI-E6) : on ne révoque librement que tant que c'est
    en attente (submitted). Si déjà traité (validé/refusé), il faut demander une
    réouverction à l'admin."""
    c = await _me_consultant(db, current_user)
    ts = await _ts_for(db, tenant_id, c.id, body.month)
    if not ts:
        raise HTTPException(400, "Aucun CRA à révoquer.")
    if ts.status in ("approved", "rejected"):
        raise HTTPException(400, "Ce CRA a déjà été traité par le management — demandez une réouverction.")
    if ts.status != "submitted":
        raise HTTPException(400, "Le CRA n'est pas en attente de validation.")
    ts.status = "draft"
    ts.submitted_at = None
    await db.commit()
    return await _me_grid(db, tenant_id, c, body.month, ts)


@router.post("/me/cra/request-reopen", response_model=CraGridOut)
async def request_reopen_my_cra(body: MonthIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ts = await _ts_for(db, tenant_id, c.id, body.month)
    if not ts or ts.status not in ("approved", "rejected"):
        raise HTTPException(400, "Une réouverction ne se demande que sur un CRA déjà traité (validé/refusé).")
    ts.reopen_requested = True
    await db.commit()
    return await _me_grid(db, tenant_id, c, body.month, ts)


@router.get("/timesheets", response_model=list[TimesheetRow])
async def list_timesheets(status: str | None = Query(None), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ctx = await _load_ctx(db, tenant_id)
    q = select(TsTimesheet).where(TsTimesheet.tenant_id == tenant_id)
    if status:
        q = q.where(TsTimesheet.status == status)
    rows = (await db.execute(q.order_by(TsTimesheet.submitted_at.desc().nullslast()))).scalars().all()
    return [_ts_row(ts, ctx) for ts in rows]


@router.post("/timesheets/{ts_id}/approve", response_model=TimesheetRow)
async def approve_timesheet(ts_id: UUID, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ts = (await db.execute(select(TsTimesheet).where(TsTimesheet.id == ts_id, TsTimesheet.tenant_id == tenant_id))).scalar_one_or_none()
    if not ts:
        raise HTTPException(404, "Timesheet introuvable")
    ts.status = "approved"
    ts.reviewed_at = _now_utc()
    ts.reviewed_by = current_user.id
    ts.reject_reason = None
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _ts_row(ts, ctx)


@router.post("/timesheets/{ts_id}/reject", response_model=TimesheetRow)
async def reject_timesheet(ts_id: UUID, body: RejectIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ts = (await db.execute(select(TsTimesheet).where(TsTimesheet.id == ts_id, TsTimesheet.tenant_id == tenant_id))).scalar_one_or_none()
    if not ts:
        raise HTTPException(404, "Timesheet introuvable")
    ts.status = "rejected"
    ts.reviewed_at = _now_utc()
    ts.reviewed_by = current_user.id
    ts.reject_reason = body.reason
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _ts_row(ts, ctx)


@router.post("/timesheets/{ts_id}/reopen", response_model=TimesheetRow)
async def reopen_timesheet(ts_id: UUID, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Admin : rouvre un CRA déjà traité (suite à une demande du consultant) → repasse en brouillon."""
    ts = (await db.execute(select(TsTimesheet).where(TsTimesheet.id == ts_id, TsTimesheet.tenant_id == tenant_id))).scalar_one_or_none()
    if not ts:
        raise HTTPException(404, "Timesheet introuvable")
    ts.status = "draft"
    ts.reopen_requested = False
    ts.submitted_at = None
    ts.reviewed_at = None
    ts.reviewed_by = None
    ts.reject_reason = None
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _ts_row(ts, ctx)


# ──────────────────────────── PDF & historique (EPIC F) ────────────────────────────

def _pdf_response(pdf: bytes, filename: str) -> Response:
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/me/cra/pdf")
async def my_cra_pdf(month: str = Query(...), tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    entries = list((await db.execute(select(TsTimeEntry).where(TsTimeEntry.tenant_id == tenant_id, TsTimeEntry.consultant_id == c.id, TsTimeEntry.month == month))).scalars().all())
    grid = _apply_status(_build_grid(c, month, ctx, entries), await _ts_for(db, tenant_id, c.id, month))
    return _pdf_response(build_timesheet_pdf(grid, c.name), f"CRA_{c.slug}_{month}.pdf")


@router.get("/me/timesheets", response_model=list[TimesheetRow])
async def my_timesheets(tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    rows = (await db.execute(
        select(TsTimesheet).where(TsTimesheet.tenant_id == tenant_id, TsTimesheet.consultant_id == c.id).order_by(TsTimesheet.month.desc())
    )).scalars().all()
    return [_ts_row(ts, ctx) for ts in rows]


@router.get("/consultants/{slug}/cra/pdf")
async def consultant_cra_pdf(slug: str, month: str = Query(...), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ctx, cons, entries = await _load_cons_and_entries(db, tenant_id, slug, month)
    grid = _apply_status(_build_grid(cons, month, ctx, entries), await _ts_for(db, tenant_id, cons.id, month))
    return _pdf_response(build_timesheet_pdf(grid, cons.name), f"CRA_{slug}_{month}.pdf")


# ──────────────────────────── Frais / notes de frais (EPIC G) ────────────────────────────

_EXPENSE_TYPES = {
    "km": "Indemnités kilométriques", "meal": "Repas", "lodging": "Hébergement",
    "transport": "Transport", "toll": "Péage", "parking": "Parking",
    "fuel": "Carburant", "supplies": "Fournitures", "other": "Autre",
}
_KM_RATE = 0.60  # €/km — barème simplifié (à ajuster sur le barème fiscal officiel)


def _expense_amount(body: ExpenseIn) -> tuple[float, float | None]:
    if body.type == "km" and body.km:
        return round(body.km * _KM_RATE, 2), _KM_RATE
    return body.amount, None


def _expense_out(e: TsExpense, ctx: _Ctx, with_consultant: bool = False) -> ExpenseOut:
    proj = ctx.proj_by_id.get(e.project_id) if e.project_id else None
    out = ExpenseOut(
        id=str(e.id), date=e.expense_date.isoformat(), month=e.month, type=e.type,
        typeLabel=_EXPENSE_TYPES.get(e.type, e.type), description=e.description, amount=e.amount,
        km=e.km, kmRate=e.km_rate, status=e.status, hasReceipt=e.receipt_document_id is not None,
        receiptId=str(e.receipt_document_id) if e.receipt_document_id else None,
        projectId=proj.code if proj else None,
        submittedAt=e.submitted_at.isoformat() if e.submitted_at else None,
        reviewedAt=e.reviewed_at.isoformat() if e.reviewed_at else None,
        reimbursedAt=e.reimbursed_at.isoformat() if e.reimbursed_at else None, rejectReason=e.reject_reason,
    )
    if with_consultant:
        c = ctx.cons_by_id.get(e.consultant_id)
        out.consultantId = c.slug if c else None
        out.consultantName = c.name if c else None
        out.initials = c.initials if c else None
    return out


async def _my_expense(db, tenant_id, consultant_id, exp_id) -> TsExpense:
    e = (await db.execute(select(TsExpense).where(
        TsExpense.id == exp_id, TsExpense.tenant_id == tenant_id, TsExpense.consultant_id == consultant_id))).scalar_one_or_none()
    if not e:
        raise HTTPException(404, "Frais introuvable")
    return e


async def _admin_expense(db, tenant_id, exp_id) -> TsExpense:
    e = (await db.execute(select(TsExpense).where(TsExpense.id == exp_id, TsExpense.tenant_id == tenant_id))).scalar_one_or_none()
    if not e:
        raise HTTPException(404, "Frais introuvable")
    return e


@router.get("/me/expenses", response_model=list[ExpenseOut])
async def my_expenses(month: str | None = Query(None), tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    q = select(TsExpense).where(TsExpense.tenant_id == tenant_id, TsExpense.consultant_id == c.id)
    if month:
        q = q.where(TsExpense.month == month)
    rows = (await db.execute(q.order_by(TsExpense.expense_date.desc()))).scalars().all()
    return [_expense_out(e, ctx) for e in rows]


@router.post("/me/expenses", response_model=ExpenseOut, status_code=201)
async def create_my_expense(body: ExpenseIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    try:
        d = date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(400, "Date invalide (AAAA-MM-JJ)")
    amount, rate = _expense_amount(body)
    proj = await _get(db, TsProject, "code", tenant_id, body.projectId) if body.projectId else None
    e = TsExpense(
        tenant_id=tenant_id, consultant_id=c.id, project_id=proj.id if proj else None,
        expense_date=d, month=f"{d.year}-{d.month:02d}", type=body.type, description=body.description,
        amount=amount, km=body.km, km_rate=rate, status="draft",
    )
    db.add(e)
    await db.commit()
    await db.refresh(e)
    return _expense_out(e, ctx)


@router.put("/me/expenses/{exp_id}", response_model=ExpenseOut)
async def update_my_expense(exp_id: UUID, body: ExpenseIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    e = await _my_expense(db, tenant_id, c.id, exp_id)
    if e.status not in ("draft", "rejected"):
        raise HTTPException(400, "Frais déjà soumis — non modifiable.")
    try:
        d = date.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(400, "Date invalide")
    amount, rate = _expense_amount(body)
    proj = await _get(db, TsProject, "code", tenant_id, body.projectId) if body.projectId else None
    e.type, e.description, e.amount, e.km, e.km_rate = body.type, body.description, amount, body.km, rate
    e.expense_date, e.month, e.project_id = d, f"{d.year}-{d.month:02d}", proj.id if proj else None
    if e.status == "rejected":
        e.status = "draft"
        e.reject_reason = None
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _expense_out(e, ctx)


@router.delete("/me/expenses/{exp_id}", status_code=204)
async def delete_my_expense(exp_id: UUID, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    e = await _my_expense(db, tenant_id, c.id, exp_id)
    await db.delete(e)
    await db.commit()


@router.post("/me/expenses/{exp_id}/submit", response_model=ExpenseOut)
async def submit_my_expense(exp_id: UUID, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    e = await _my_expense(db, tenant_id, c.id, exp_id)
    if e.status not in ("draft", "rejected"):
        raise HTTPException(400, "Frais déjà soumis.")
    e.status = "submitted"
    e.submitted_at = _now_utc()
    e.reject_reason = None
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _expense_out(e, ctx)


@router.post("/me/expenses/{exp_id}/receipt", response_model=ExpenseOut)
async def upload_my_receipt(exp_id: UUID, file: UploadFile = File(...), tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    e = await _my_expense(db, tenant_id, c.id, exp_id)
    path = await upload_file(file, "kairos-docs", prefix=f"expense/{e.id}")
    doc = TsDocument(
        tenant_id=tenant_id, entity_type="expense", entity_id=e.id, doc_type="receipt",
        title=file.filename or "Justificatif", filename=file.filename or "receipt",
        file_path=path, content_type=file.content_type, uploaded_by=current_user.id,
    )
    db.add(doc)
    await db.flush()
    e.receipt_document_id = doc.id
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _expense_out(e, ctx)


@router.get("/expenses", response_model=list[ExpenseOut])
async def list_expenses(status: str | None = Query(None), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ctx = await _load_ctx(db, tenant_id)
    q = select(TsExpense).where(TsExpense.tenant_id == tenant_id)
    if status:
        q = q.where(TsExpense.status == status)
    rows = (await db.execute(q.order_by(TsExpense.submitted_at.desc().nullslast()))).scalars().all()
    return [_expense_out(e, ctx, with_consultant=True) for e in rows]


@router.post("/expenses/{exp_id}/approve", response_model=ExpenseOut)
async def approve_expense(exp_id: UUID, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    e = await _admin_expense(db, tenant_id, exp_id)
    e.status = "approved"
    e.reviewed_at = _now_utc()
    e.reviewed_by = current_user.id
    e.reject_reason = None
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _expense_out(e, ctx, with_consultant=True)


@router.post("/expenses/{exp_id}/reject", response_model=ExpenseOut)
async def reject_expense(exp_id: UUID, body: RejectIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    e = await _admin_expense(db, tenant_id, exp_id)
    e.status = "rejected"
    e.reviewed_at = _now_utc()
    e.reviewed_by = current_user.id
    e.reject_reason = body.reason
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _expense_out(e, ctx, with_consultant=True)


@router.post("/expenses/{exp_id}/reimburse", response_model=ExpenseOut)
async def reimburse_expense(exp_id: UUID, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    e = await _admin_expense(db, tenant_id, exp_id)
    if e.status != "approved":
        raise HTTPException(400, "Le frais doit être validé avant remboursement.")
    e.status = "reimbursed"
    e.reimbursed_at = _now_utc()
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _expense_out(e, ctx, with_consultant=True)


# ──────────────────────────── Factures consultant & 360° (EPIC H) ────────────────────────────

def _cinv_out(inv: TsConsultantInvoice, ctx: _Ctx, with_consultant: bool = False) -> ConsultantInvoiceOut:
    out = ConsultantInvoiceOut(
        id=str(inv.id), number=inv.number, month=inv.month, amount=inv.amount, status=inv.status,
        issueDate=inv.issue_date.isoformat(), dueDate=inv.due_date.isoformat() if inv.due_date else None,
        paidAt=inv.paid_at.isoformat() if inv.paid_at else None,
        receivedAt=inv.received_at.isoformat() if inv.received_at else None,
        hasDocument=inv.document_id is not None, documentId=str(inv.document_id) if inv.document_id else None,
    )
    if with_consultant:
        c = ctx.cons_by_id.get(inv.consultant_id)
        out.consultantId = c.slug if c else None
        out.consultantName = c.name if c else None
        out.initials = c.initials if c else None
    return out


async def _my_cinv(db, tenant_id, consultant_id, inv_id) -> TsConsultantInvoice:
    inv = (await db.execute(select(TsConsultantInvoice).where(
        TsConsultantInvoice.id == inv_id, TsConsultantInvoice.tenant_id == tenant_id, TsConsultantInvoice.consultant_id == consultant_id))).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Facture introuvable")
    return inv


@router.get("/me/invoices", response_model=list[ConsultantInvoiceOut])
async def my_invoices(tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    rows = (await db.execute(select(TsConsultantInvoice).where(
        TsConsultantInvoice.tenant_id == tenant_id, TsConsultantInvoice.consultant_id == c.id).order_by(TsConsultantInvoice.issue_date.desc()))).scalars().all()
    return [_cinv_out(i, ctx) for i in rows]


@router.post("/me/invoices", response_model=ConsultantInvoiceOut, status_code=201)
async def create_my_invoice(body: ConsultantInvoiceIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    try:
        issue = date.fromisoformat(body.issueDate) if body.issueDate else date.today()
    except ValueError:
        raise HTTPException(400, "Date d'émission invalide")
    seq = len((await db.execute(select(TsConsultantInvoice).where(TsConsultantInvoice.tenant_id == tenant_id, TsConsultantInvoice.consultant_id == c.id))).scalars().all()) + 1
    number = body.number or f"FC-{(c.slug or 'CONS').upper()[:4]}-{body.month}-{seq:02d}"
    inv = TsConsultantInvoice(
        tenant_id=tenant_id, consultant_id=c.id, number=number, month=body.month, amount=body.amount,
        status="submitted", issue_date=issue, due_date=issue + timedelta(days=45),
    )
    db.add(inv)
    await db.commit()
    await db.refresh(inv)
    return _cinv_out(inv, ctx)


@router.post("/me/invoices/{inv_id}/document", response_model=ConsultantInvoiceOut)
async def upload_my_invoice_doc(inv_id: UUID, file: UploadFile = File(...), tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    inv = await _my_cinv(db, tenant_id, c.id, inv_id)
    path = await upload_file(file, "kairos-docs", prefix=f"cinvoice/{inv.id}")
    doc = TsDocument(
        tenant_id=tenant_id, entity_type="consultant_invoice", entity_id=inv.id, doc_type="invoice",
        title=file.filename or "Facture", filename=file.filename or "facture",
        file_path=path, content_type=file.content_type, uploaded_by=current_user.id,
    )
    db.add(doc)
    await db.flush()
    inv.document_id = doc.id
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _cinv_out(inv, ctx)


@router.get("/me/summary", response_model=Summary360)
async def my_summary(tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ts = (await db.execute(select(TsTimesheet).where(TsTimesheet.tenant_id == tenant_id, TsTimesheet.consultant_id == c.id))).scalars().all()
    worked = sum(t.worked_days for t in ts)
    rate = c.daily_cost or 0
    invs = (await db.execute(select(TsConsultantInvoice).where(TsConsultantInvoice.tenant_id == tenant_id, TsConsultantInvoice.consultant_id == c.id))).scalars().all()
    invoiced = sum(i.amount for i in invs)
    collected = sum(i.amount for i in invs if i.status == "paid")
    exps = (await db.execute(select(TsExpense).where(TsExpense.tenant_id == tenant_id, TsExpense.consultant_id == c.id))).scalars().all()
    spent = sum(e.amount for e in exps if e.status != "rejected")
    reimbursed = sum(e.amount for e in exps if e.status == "reimbursed")
    return Summary360(
        workedDays=worked, billable=round(worked * rate, 2), invoiced=invoiced, collected=collected,
        pendingPayment=invoiced - collected, spent=spent, reimbursed=reimbursed,
    )


@router.get("/consultant-invoices", response_model=list[ConsultantInvoiceOut])
async def list_consultant_invoices(status: str | None = Query(None), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ctx = await _load_ctx(db, tenant_id)
    q = select(TsConsultantInvoice).where(TsConsultantInvoice.tenant_id == tenant_id)
    if status:
        q = q.where(TsConsultantInvoice.status == status)
    rows = (await db.execute(q.order_by(TsConsultantInvoice.issue_date.desc()))).scalars().all()
    return [_cinv_out(i, ctx, with_consultant=True) for i in rows]


@router.post("/consultant-invoices/{inv_id}/receive", response_model=ConsultantInvoiceOut)
async def receive_consultant_invoice(inv_id: UUID, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    inv = (await db.execute(select(TsConsultantInvoice).where(TsConsultantInvoice.id == inv_id, TsConsultantInvoice.tenant_id == tenant_id))).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Facture introuvable")
    inv.status = "received"
    inv.received_at = _now_utc()
    inv.reviewed_by = current_user.id
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _cinv_out(inv, ctx, with_consultant=True)


@router.post("/consultant-invoices/{inv_id}/pay", response_model=ConsultantInvoiceOut)
async def pay_consultant_invoice(inv_id: UUID, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    inv = (await db.execute(select(TsConsultantInvoice).where(TsConsultantInvoice.id == inv_id, TsConsultantInvoice.tenant_id == tenant_id))).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Facture introuvable")
    inv.status = "paid"
    inv.paid_at = _now_utc()
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _cinv_out(inv, ctx, with_consultant=True)


# ──────────────────────────── Profil / dossier de compétence (EPIC J) ────────────────────────────

async def _my_cv(db, tenant_id, consultant_id) -> TsDocument | None:
    return (await db.execute(
        select(TsDocument).where(
            TsDocument.tenant_id == tenant_id, TsDocument.entity_type == "consultant",
            TsDocument.entity_id == consultant_id, TsDocument.doc_type == "cv")
        .order_by(TsDocument.created_at.desc()))).scalars().first()


def _profile_out(c: TsConsultant, email: str | None, cv: TsDocument | None) -> ProfileOut:
    pj = c.profile_json or {}
    return ProfileOut(
        name=c.name, role=c.role, type=c.type, seniority=c.seniority, location=c.location, email=email,
        headline=pj.get("headline"), summary=pj.get("summary"), skills=c.skills or [],
        experiences=pj.get("experiences", []), education=pj.get("education", []),
        certifications=pj.get("certifications", []), languages=pj.get("languages", []),
        hasCv=cv is not None, cvId=str(cv.id) if cv else None,
    )


@router.get("/me/profile", response_model=ProfileOut)
async def my_profile_sheet(tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    cv = await _my_cv(db, tenant_id, c.id)
    return _profile_out(c, current_user.email, cv)


@router.put("/me/profile", response_model=ProfileOut)
async def update_my_profile_sheet(body: ProfileIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    pj = dict(c.profile_json or {})
    for f in ("headline", "summary", "experiences", "education", "certifications", "languages"):
        v = getattr(body, f)
        if v is not None:
            pj[f] = v
    c.profile_json = pj  # réassignation → détection mutation JSONB
    if body.skills is not None:
        c.skills = body.skills
    await db.commit()
    cv = await _my_cv(db, tenant_id, c.id)
    return _profile_out(c, current_user.email, cv)


@router.post("/me/profile/parse-cv", response_model=ProfileIn)
async def parse_my_cv(file: UploadFile = File(...), tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Upload CV → extraction IA → profil pré-rempli (NON sauvegardé : revu dans le stepper).
    Le CV est aussi attaché au profil (document docType=cv)."""
    c = await _me_consultant(db, current_user)
    content = await file.read()
    text = extract_cv_text(content, file.filename or "")
    parsed = parse_cv_to_profile(text)
    # attacher le CV au profil
    try:
        await file.seek(0)
        path = await upload_file(file, "kairos-docs", prefix=f"consultant/{c.id}")
        db.add(TsDocument(
            tenant_id=tenant_id, entity_type="consultant", entity_id=c.id, doc_type="cv",
            title=file.filename or "CV", filename=file.filename or "cv",
            file_path=path, content_type=file.content_type, uploaded_by=current_user.id))
        await db.commit()
    except Exception:
        logger.warning("cv_attach_failed")
    return ProfileIn(**parsed)


@router.get("/me/profile/dossier")
async def my_dossier(format: str = Query("pdf"), tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    cv = await _my_cv(db, tenant_id, c.id)
    p = _profile_out(c, current_user.email, cv)
    if format == "docx":
        data = build_dossier_docx(p)
        return Response(content=data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": f'attachment; filename="dossier_{c.slug}.docx"'})
    data = build_dossier_pdf(p)
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="dossier_{c.slug}.pdf"'})


# ──────────────────────────── Contacts (EPIC K) ────────────────────────────

_CONTACT_STATUSES = {"open", "in_progress", "resolved"}


def _msg_out(m: TsContactMessage) -> MessageOut:
    return MessageOut(id=str(m.id), authorRole=m.author_role, authorName=m.author_name, body=m.body, createdAt=m.created_at.isoformat())


def _contact_out(r: TsContactRequest, ctx: _Ctx, msgs: list | None = None, detail: bool = False):
    c = ctx.cons_by_id.get(r.consultant_id)
    cls = ContactDetailOut if detail else ContactOut
    out = cls(
        id=str(r.id), subject=r.subject, status=r.status,
        createdAt=r.created_at.isoformat(), updatedAt=r.updated_at.isoformat(),
        consultantId=c.slug if c else None, consultantName=c.name if c else None, initials=c.initials if c else None,
        messageCount=len(msgs) if msgs is not None else 0,
        lastMessage=(msgs[-1].body[:80] if msgs else None),
    )
    if detail and msgs is not None:
        out.messages = [_msg_out(m) for m in msgs]
    return out


async def _msgs(db, request_id) -> list:
    return list((await db.execute(
        select(TsContactMessage).where(TsContactMessage.request_id == request_id).order_by(TsContactMessage.created_at))).scalars().all())


@router.get("/me/contacts", response_model=list[ContactOut])
async def my_contacts(tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    rows = (await db.execute(
        select(TsContactRequest).where(TsContactRequest.tenant_id == tenant_id, TsContactRequest.consultant_id == c.id).order_by(TsContactRequest.updated_at.desc()))).scalars().all()
    return [_contact_out(r, ctx, await _msgs(db, r.id)) for r in rows]


@router.post("/me/contacts", response_model=ContactDetailOut, status_code=201)
async def create_my_contact(body: ContactIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    ctx = await _load_ctx(db, tenant_id)
    r = TsContactRequest(tenant_id=tenant_id, consultant_id=c.id, subject=body.subject, status="open")
    db.add(r)
    await db.flush()
    m = TsContactMessage(tenant_id=tenant_id, request_id=r.id, author_user_id=current_user.id, author_role="consultant", author_name=c.name, body=body.message)
    db.add(m)
    await db.commit()
    return _contact_out(r, ctx, [m], detail=True)


async def _my_contact(db, tenant_id, consultant_id, req_id) -> TsContactRequest:
    r = (await db.execute(select(TsContactRequest).where(
        TsContactRequest.id == req_id, TsContactRequest.tenant_id == tenant_id, TsContactRequest.consultant_id == consultant_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Demande introuvable")
    return r


@router.get("/me/contacts/{req_id}", response_model=ContactDetailOut)
async def get_my_contact(req_id: UUID, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    r = await _my_contact(db, tenant_id, c.id, req_id)
    ctx = await _load_ctx(db, tenant_id)
    return _contact_out(r, ctx, await _msgs(db, r.id), detail=True)


@router.post("/me/contacts/{req_id}/messages", response_model=ContactDetailOut)
async def post_my_contact_message(req_id: UUID, body: MessageIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    r = await _my_contact(db, tenant_id, c.id, req_id)
    db.add(TsContactMessage(tenant_id=tenant_id, request_id=r.id, author_user_id=current_user.id, author_role="consultant", author_name=c.name, body=body.body))
    r.updated_at = _now_utc()
    if r.status == "resolved":
        r.status = "in_progress"
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _contact_out(r, ctx, await _msgs(db, r.id), detail=True)


# --- admin ---

async def _admin_contact(db, tenant_id, req_id) -> TsContactRequest:
    r = (await db.execute(select(TsContactRequest).where(TsContactRequest.id == req_id, TsContactRequest.tenant_id == tenant_id))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "Demande introuvable")
    return r


@router.get("/contacts", response_model=list[ContactOut])
async def list_contacts(status: str | None = Query(None), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    ctx = await _load_ctx(db, tenant_id)
    q = select(TsContactRequest).where(TsContactRequest.tenant_id == tenant_id)
    if status:
        q = q.where(TsContactRequest.status == status)
    rows = (await db.execute(q.order_by(TsContactRequest.updated_at.desc()))).scalars().all()
    return [_contact_out(r, ctx, await _msgs(db, r.id)) for r in rows]


@router.get("/contacts/{req_id}", response_model=ContactDetailOut)
async def get_contact(req_id: UUID, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await _admin_contact(db, tenant_id, req_id)
    ctx = await _load_ctx(db, tenant_id)
    return _contact_out(r, ctx, await _msgs(db, r.id), detail=True)


@router.post("/contacts/{req_id}/messages", response_model=ContactDetailOut)
async def post_contact_message(req_id: UUID, body: MessageIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    r = await _admin_contact(db, tenant_id, req_id)
    db.add(TsContactMessage(tenant_id=tenant_id, request_id=r.id, author_user_id=current_user.id, author_role="admin", author_name=getattr(current_user, "full_name", None) or "Management", body=body.body))
    r.updated_at = _now_utc()
    if r.status == "open":
        r.status = "in_progress"
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _contact_out(r, ctx, await _msgs(db, r.id), detail=True)


@router.patch("/contacts/{req_id}/status", response_model=ContactOut)
async def set_contact_status(req_id: UUID, body: ContactStatusIn, tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if body.status not in _CONTACT_STATUSES:
        raise HTTPException(400, "Statut invalide")
    r = await _admin_contact(db, tenant_id, req_id)
    r.status = body.status
    r.updated_at = _now_utc()
    await db.commit()
    ctx = await _load_ctx(db, tenant_id)
    return _contact_out(r, ctx, await _msgs(db, r.id))


# ============================ Copilot consultant (EPIC L) ============================
# Sécurité : voir app/modules/timesheet/copilot.py et CONSULTANT_COPILOT_DESIGN.md.
# Lecture seule côté modèle ; les actions proposées sont confirmées par l'utilisateur
# via les endpoints normaux (submit CRA, créer frais, contact, dossier).

def _copilot_msg_out(m: TsCopilotMessage) -> CopilotMsgOut:
    meta = m.meta or {}
    pa = meta.get("pendingAction")
    return CopilotMsgOut(
        id=str(m.id), role=m.role, content=m.content,
        createdAt=m.created_at.isoformat(), tools=meta.get("tools") or [],
        pendingAction=PendingAction(**pa) if pa else None,
    )


@router.get("/me/copilot/history", response_model=list[CopilotMsgOut])
async def copilot_history(tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    rows = (await db.execute(
        select(TsCopilotMessage).where(TsCopilotMessage.tenant_id == tenant_id, TsCopilotMessage.consultant_id == c.id).order_by(TsCopilotMessage.created_at)
    )).scalars().all()
    return [_copilot_msg_out(m) for m in rows[-50:]]


@router.delete("/me/copilot/history", status_code=204)
async def copilot_clear_history(tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    rows = (await db.execute(select(TsCopilotMessage).where(TsCopilotMessage.tenant_id == tenant_id, TsCopilotMessage.consultant_id == c.id))).scalars().all()
    for m in rows:
        await db.delete(m)
    await db.commit()


@router.post("/me/copilot/chat", response_model=CopilotChatOut)
async def copilot_chat(body: CopilotChatIn, tenant_id: UUID = Depends(get_tenant_id), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    c = await _me_consultant(db, current_user)
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="Message vide.")
    if not copilot_rate_limit(c.id):
        raise HTTPException(status_code=429, detail="Trop de messages — réessayez dans une minute.")

    hist_rows = (await db.execute(
        select(TsCopilotMessage).where(TsCopilotMessage.tenant_id == tenant_id, TsCopilotMessage.consultant_id == c.id).order_by(TsCopilotMessage.created_at)
    )).scalars().all()
    history = [{"role": m.role, "content": m.content} for m in hist_rows]

    db.add(TsCopilotMessage(tenant_id=tenant_id, consultant_id=c.id, role="user", content=msg))
    result = await copilot_run_turn(db, tenant_id, c, history, msg)
    db.add(TsCopilotMessage(
        tenant_id=tenant_id, consultant_id=c.id, role="assistant", content=result["reply"],
        meta={"tools": result.get("tools") or [], "pendingAction": result.get("pendingAction")},
    ))
    await db.commit()
    pa = result.get("pendingAction")
    return CopilotChatOut(reply=result["reply"], pendingAction=PendingAction(**pa) if pa else None, tools=result.get("tools") or [])
