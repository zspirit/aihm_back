"""Kairos module tests.

- Serializer unit tests : pure mapping ORM -> contrat front (AUCUNE DB).
- Integration : seed + endpoints (skip si Postgres indispo, comme le POC).
"""
import uuid
from datetime import date

import pytest

from app.modules.timesheet.api import (
    _Ctx,
    _build_grid,
    _consultant_row,
    _invoice_out,
    _mission_out,
    _project_row,
)
from app.modules.timesheet.models import (
    TsClient,
    TsConsultant,
    TsInvoice,
    TsMission,
    TsProject,
    TsTimeEntry,
)

TID = uuid.uuid4()


def _ctx():
    cid, pid, conid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    client = TsClient(id=cid, tenant_id=TID, slug="acme", name="Acme Corp", initials="AC", health="good")
    project = TsProject(
        id=pid, tenant_id=TID, code="ACM-2024", name="Refonte SI", client_id=cid,
        billing="Régie", tjm=560, progress=72, margin=19, margin_flag="warning",
        budget_flag=True, ends_in=92, status="En cours",
    )
    cons = TsConsultant(
        id=conid, tenant_id=TID, slug="sarah", name="Sarah Benali", initials="SB",
        role="Front-end", type="Salarié", current_project_id=pid, occupation=80,
        status="active", ex_candidate_id=None,
    )
    inv = TsInvoice(
        id=uuid.uuid4(), tenant_id=TID, number="F-2026-058", client_id=cid, project_id=pid,
        period="Mai 2026", amount=47040, status="payée", issued="02/06/2026",
    )
    m_internal = TsMission(tenant_id=TID, consultant_id=conid, project_id=pid, client_id=cid,
                           role="Front-end", period="Jan 2026 → …", days=72, current=True)
    m_external = TsMission(tenant_id=TID, consultant_id=conid, project_id=None, client_id=None,
                           label="Doctolib — Portail patient", role="Front-end", period="2023 → 2025", days=320)
    ctx = _Ctx([client], [project], [cons], [m_internal, m_external], [], [inv])
    return ctx, project, cons, inv, m_internal, m_external


def test_project_row_resolves_client_and_counts_staff():
    ctx, project, *_ = _ctx()
    row = _project_row(project, ctx)
    assert row.code == "ACM-2024"
    assert row.client == "Acme Corp"
    assert row.clientId == "acme"
    assert row.staffed == 1            # Sarah is current on this project
    assert row.marginFlag == "warning"
    assert row.budgetFlag is True
    assert row.endsIn == 92


def test_consultant_row_uses_current_project_client():
    ctx, _, cons, *_ = _ctx()
    row = _consultant_row(cons, ctx)
    assert row.id == "sarah"
    assert row.project == "Acme Corp"   # current project's client display name
    assert row.occupation == 80
    assert row.endsIn == 92
    assert row.exCandidate is False


def test_invoice_out_maps_slugs_and_codes():
    ctx, _, _, inv, *_ = _ctx()
    out = _invoice_out(inv, ctx)
    assert out.id == "F-2026-058"
    assert out.clientId == "acme"
    assert out.projectId == "ACM-2024"
    assert out.status == "payée"


def test_mission_out_internal_vs_external():
    ctx, _, _, _, m_internal, m_external = _ctx()
    internal = _mission_out(m_internal, ctx)
    assert internal.projectId == "ACM-2024" and internal.clientId == "acme"
    external = _mission_out(m_external, ctx)
    assert external.projectId is None and external.clientId is None
    assert external.label == "Doctolib — Portail patient"


def test_cra_grid_builds_cells_days_and_totals():
    ctx, project, cons, *_ = _ctx()
    entries = [
        TsTimeEntry(tenant_id=TID, consultant_id=cons.id, project_id=project.id,
                    entry_date=date(2026, 6, 12), month="2026-06", value=1.0),
        TsTimeEntry(tenant_id=TID, consultant_id=cons.id, absence_code="CP",
                    entry_date=date(2026, 6, 18), month="2026-06", value=0.5),
    ]
    grid = _build_grid(cons, "2026-06", ctx, entries)
    assert grid.label == "Juin 2026"
    assert len(grid.days) == 30                     # June
    assert grid.cells["ACM-2024:12"] == 1.0
    assert grid.cells["CP:18"] == 0.5
    assert any(r.code == "ACM-2024" for r in grid.missions)
    assert len(grid.absences) == 6                  # CP/RTT/MAL/INT/FOR/SS
    assert grid.totals["worked"] == 1.0
    assert grid.totals["absence"] == 0.5
    assert grid.totals["billable"] == 560.0         # 1 day × tjm 560


# ──────────────────────── integration (needs Postgres) ────────────────────────

@pytest.mark.asyncio
async def test_seed_and_hub(db_session):
    from app.models.tenant import Tenant
    from app.modules.timesheet.api import get_hub
    from app.modules.timesheet.seed import seed_kairos_demo

    tenant = Tenant(name="ESN Demo")
    db_session.add(tenant)
    await db_session.flush()

    await seed_kairos_demo(db_session, tenant.id)

    hub = await get_hub(period="Juin 2026", tenant_id=tenant.id, _=None, db=db_session)
    assert hub.period["label"] == "Juin 2026"
    assert len(hub.kpis) == 4
    assert {k["key"] for k in hub.kpis} == {"tace", "inter", "tobill", "margin"}
    # 5 active projects (ACM-2021 is 'Clôturé' -> excluded)
    assert len(hub.projects) == 5
    assert len(hub.consultants) == 6
    # 2 consultants in intercontrat (Karim, Thomas)
    inter = next(k for k in hub.kpis if k["key"] == "inter")
    assert inter["value"] == "2"
    # there is at least one CRA 'à facturer' -> toInvoice non-empty
    assert len(hub.toInvoice) >= 1
