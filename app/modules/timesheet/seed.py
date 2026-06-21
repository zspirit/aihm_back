"""Seed the Kairos demo dataset (mirrors design-review/kairos/data.js).

Lets a front dev hit the real API and see exactly the maquette data.
Usage (script): python -m app.modules.timesheet.seed <tenant_id>
Or call ``await seed_kairos_demo(db, tenant_id)``.
"""
from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.entitlement import TenantEntitlement
from app.modules.timesheet.models import (
    TsClient,
    TsConsultant,
    TsConsultantInvoice,
    TsContactMessage,
    TsContactRequest,
    TsCraMonth,
    TsDocument,
    TsExpense,
    TsInvoice,
    TsMission,
    TsProject,
    TsTimeEntry,
    TsTimesheet,
)

CLIENTS = [
    dict(slug="acme", name="Acme Corp", initials="AC", sector="Industrie · ETI", since="2022", health="good", location="Paris", siret="812 345 678 00021", contact={"name": "Claire Fontaine", "role": "DSI", "email": "c.fontaine@acme.fr"}),
    dict(slug="helios", name="Helios", initials="HE", sector="Scale-up · Mobilité", since="2024", health="good", location="Lyon", siret="901 234 567 00013", contact={"name": "Marc Oliveira", "role": "CTO", "email": "marc@helios.io"}),
    dict(slug="dataflow", name="Dataflow SAS", initials="DF", sector="Éditeur SaaS", since="2023", health="watch", location="Nantes", siret="784 512 369 00045", contact={"name": "Léa Bonnet", "role": "Head of Data", "email": "lea@dataflow.io"}),
    dict(slug="nexa", name="Nexa Retail", initials="NX", sector="Retail · Grand compte", since="2021", health="good", location="Paris", siret="653 214 789 00078", contact={"name": "Idir Ait", "role": "Cloud Lead", "email": "i.ait@nexa.com"}),
    dict(slug="zenith", name="Zenith Bank", initials="ZB", sector="Banque · Grand compte", since="2025", health="good", location="Paris", siret="552 678 134 00099", contact={"name": "Sofia Rahmani", "role": "RSSI", "email": "s.rahmani@zenith.bank"}),
]

PROJECTS = [
    dict(code="ACM-2024", name="Refonte SI", client="acme", billing="Régie", tjm=560, status="En cours", progress=72, margin=19, margin_flag="warning", budget_flag=True, start="02/01/2026", end="30/09/2026", ends_in=92, days_sold=240, days_consumed=173, contract={"type": "Régie / Assistance technique", "signed": "18/12/2025", "tjmAvg": 560, "ceiling": None, "renewal": "Tacite, 3 mois", "po": "BC-ACM-2026-014"}, description="Refonte complète du SI métier : migration ERP, socle API, et reprise de données."),
    dict(code="ACM-2021", name="Audit sécurité (clôturé)", client="acme", billing="Forfait", amount=65000, status="Clôturé", progress=100, margin=34, margin_flag="good", budget_flag=False, start="04/2021", end="09/2021", ends_in=None, days_sold=110, days_consumed=104, contract={"type": "Forfait", "signed": "15/03/2021", "tjmAvg": None, "ceiling": 65000, "renewal": "—", "po": "BC-ACM-2021-002"}, description="Audit de sécurité du SI historique, livré au forfait."),
    dict(code="HEL-0088", name="App mobile", client="helios", billing="Forfait", amount=180000, status="En cours", progress=88, margin=31, margin_flag="good", budget_flag=False, start="01/03/2026", end="30/06/2026", ends_in=14, days_sold=300, days_consumed=264, contract={"type": "Forfait · 3 jalons", "signed": "10/02/2026", "tjmAvg": None, "ceiling": 180000, "renewal": "—", "po": "BC-HEL-2026-007"}, description="Application mobile cross-platform (React Native). Forfait à 3 jalons."),
    dict(code="DTF-0312", name="Pipeline data", client="dataflow", billing="Régie", tjm=490, status="En cours", progress=45, margin=26, margin_flag="good", budget_flag=False, start="15/04/2026", end="31/12/2026", ends_in=140, days_sold=180, days_consumed=81, contract={"type": "Régie / Assistance technique", "signed": "02/04/2026", "tjmAvg": 490, "ceiling": None, "renewal": "Tacite, 1 mois", "po": "BC-DTF-2026-019"}, description="Pipeline data temps réel (Kafka, dbt, Snowflake)."),
    dict(code="NEX-1102", name="Audit cloud", client="nexa", billing="Régie plafonnée", tjm=600, status="En cours", progress=60, margin=22, margin_flag="good", budget_flag=False, start="05/05/2026", end="05/07/2026", ends_in=19, days_sold=60, days_consumed=36, contract={"type": "Régie plafonnée", "signed": "28/04/2026", "tjmAvg": 600, "ceiling": 36000, "renewal": "—", "po": "BC-NEX-2026-031"}, description="Audit architecture cloud AWS + plan FinOps. Régie plafonnée à 60 jours."),
    dict(code="ZEN-0455", name="Conformité ISO 27001", client="zenith", billing="Forfait", amount=240000, status="En cours", progress=34, margin=28, margin_flag="good", budget_flag=False, start="01/05/2026", end="31/01/2027", ends_in=210, days_sold=400, days_consumed=136, contract={"type": "Forfait · 5 jalons", "signed": "20/04/2026", "tjmAvg": None, "ceiling": 240000, "renewal": "—", "po": "BC-ZEN-2026-003"}, description="Mise en conformité ISO 27001 du SI bancaire. Forfait à 5 jalons."),
]

# cra months: (project_code, month, days, amount, status)
CRA = [
    ("ACM-2024", "Mai 2026", 84, 47040, "facturé"), ("ACM-2024", "Avr 2026", 80, 44800, "facturé"), ("ACM-2024", "Mar 2026", 88, 49280, "facturé"),
    ("HEL-0088", "Jalon 2", None, 50780, "à facturer"), ("HEL-0088", "Jalon 1", None, 72000, "facturé"),
    ("DTF-0312", "Mai 2026", 42, 20580, "à facturer"), ("DTF-0312", "Avr 2026", 21, 10290, "facturé"),
    ("NEX-1102", "Mai 2026", 40, 24000, "à facturer"),
    ("ZEN-0455", "Jalon 1", None, 48000, "facturé"),
]

CONSULTANTS = [
    dict(slug="yassine", name="Yassine El Amrani", initials="YE", role="Lead Mobile", type="Salarié", seniority="8 ans", location="Lyon", daily_cost=380, ex_candidate=True, current="HEL-0088", occupation=100, status="ending", available_on="30/06/2026", skills=["React Native", "Swift", "Kotlin", "CI/CD mobile", "Team lead"], cra_totals={"booked": 66, "billable": 25080}),
    dict(slug="ines", name="Inès Nardi", initials="IN", role="Data Engineer", type="Sous-traitant", seniority="6 ans", location="Remote", daily_cost=420, ex_candidate=False, current="DTF-0312", occupation=100, status="ending", available_on="05/07/2026", skills=["Python", "Spark", "dbt", "Snowflake", "Kafka", "Airflow"], cra_totals={"booked": 50, "billable": 24500}),
    dict(slug="mohammed", name="Mohammed Hachimi", initials="MH", role="Cyber Security", type="Salarié", seniority="7 ans", location="Casablanca", daily_cost=410, ex_candidate=True, current="ZEN-0455", occupation=100, status="active", available_on="31/01/2027", skills=["ISO 27001", "SIEM (Splunk)", "CISSP", "AWS Security", "Audit"], cra_totals={"booked": 68, "billable": 30760}),
    dict(slug="sarah", name="Sarah Benali", initials="SB", role="Front-end", type="Salarié", seniority="4 ans", location="Paris", daily_cost=300, ex_candidate=False, current="ACM-2024", occupation=80, status="active", available_on="30/09/2026", skills=["React", "TypeScript", "Design system", "Accessibilité"], cra_totals={"booked": 58, "billable": 32480}),
    dict(slug="karim", name="Karim Lahlou", initials="KL", role="DevOps", type="Sous-traitant", seniority="5 ans", location="Remote", daily_cost=400, ex_candidate=False, current=None, occupation=0, status="intercontrat", available_on=None, skills=["Kubernetes", "Terraform", "AWS", "GitLab CI", "Observabilité"], cra_totals={"booked": 18, "billable": 0}),
    dict(slug="thomas", name="Thomas Mercier", initials="TM", role="Product Owner", type="Salarié", seniority="9 ans", location="Paris", daily_cost=350, ex_candidate=False, current=None, occupation=0, status="intercontrat", available_on=None, skills=["Product", "Agile", "Roadmap", "Discovery", "Stakeholders"], cra_totals={"booked": 38, "billable": 0}),
]

# missions: (consultant_slug, project_code|None, client_slug|None, label|None, role, period, days, current)
MISSIONS = [
    ("yassine", "HEL-0088", "helios", None, "Lead Mobile", "Mar 2026 → Juin 2026", 66, True),
    ("yassine", None, None, "MobiBank — App bancaire", "Dev mobile senior", "2024 → 2025", 280, False),
    ("yassine", None, None, "Carrefour — Refonte app", "Dev mobile", "2022 → 2024", 410, False),
    ("ines", "DTF-0312", "dataflow", None, "Data Engineer", "Avr 2026 → …", 42, True),
    ("ines", "NEX-1102", "nexa", None, "Renfort FinOps", "Mai 2026", 8, True),
    ("ines", None, None, "BNP — Datalake", "Data Engineer", "2023 → 2025", 380, False),
    ("mohammed", "ZEN-0455", "zenith", None, "Lead Cyber", "Mai 2026 → …", 28, True),
    ("mohammed", "ACM-2024", "acme", None, "Renfort sécurité", "Jan 2026 → Avr 2026", 40, False),
    ("mohammed", "ACM-2021", "acme", None, "Auditeur", "2021", 104, False),
    ("sarah", "ACM-2024", "acme", None, "Front-end", "Jan 2026 → …", 72, True),
    ("sarah", None, None, "Doctolib — Portail patient", "Front-end", "2023 → 2025", 320, False),
    ("karim", "HEL-0088", "helios", None, "DevOps (renfort)", "Avr 2026 → Juin 2026", 28, False),
    ("karim", None, None, "OVHcloud — Plateforme interne", "SRE", "2022 → 2024", 360, False),
    ("thomas", "ACM-2024", "acme", None, "PO (mi-temps)", "Fév 2026 → Mai 2026", 38, False),
    ("thomas", None, None, "La Poste — Refonte tournée", "PO", "2023 → 2025", 300, False),
]

# invoices: (number, client, project, period, amount, status, issued)
INVOICES = [
    ("F-2026-058", "acme", "ACM-2024", "Mai 2026", 47040, "payée", "02/06/2026"),
    ("F-2026-061", "dataflow", "DTF-0312", "Avr 2026", 10290, "payée", "03/05/2026"),
    ("F-2026-067", "helios", "HEL-0088", "Jalon 1", 72000, "envoyée", "12/05/2026"),
    ("F-2026-072", "zenith", "ZEN-0455", "Jalon 1", 48000, "envoyée", "28/05/2026"),
    ("DRAFT-1", "acme", "ACM-2024", "Mai 2026", 47040, "à émettre", None),
]


async def seed_kairos_demo(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Wipe + reseed the Kairos demo dataset for one tenant. Activates the module."""
    # clean (children first)
    for model in (TsContactMessage, TsContactRequest, TsTimeEntry, TsTimesheet, TsExpense, TsConsultantInvoice, TsDocument, TsMission, TsInvoice, TsCraMonth, TsConsultant, TsProject, TsClient):
        await db.execute(delete(model).where(model.tenant_id == tenant_id))

    clients = {}
    for c in CLIENTS:
        row = TsClient(tenant_id=tenant_id, **c)
        db.add(row)
        clients[c["slug"]] = row
    await db.flush()

    projects = {}
    for p in PROJECTS:
        slug = p.pop("client")
        code = p["code"]
        row = TsProject(tenant_id=tenant_id, client_id=clients[slug].id, **p)
        db.add(row)
        projects[code] = row
        p["client"] = slug  # restore for idempotency if re-run
    await db.flush()

    for code, month, days, amount, status in CRA:
        db.add(TsCraMonth(tenant_id=tenant_id, project_id=projects[code].id, month=month, days=days, amount=amount, status=status))

    consultants = {}
    for c in CONSULTANTS:
        cur = projects[c["current"]].id if c["current"] else None
        row = TsConsultant(
            tenant_id=tenant_id, slug=c["slug"], name=c["name"], initials=c["initials"],
            role=c["role"], type=c["type"], seniority=c["seniority"], location=c["location"],
            daily_cost=c["daily_cost"], ex_candidate_id=(uuid.uuid4() if c["ex_candidate"] else None),
            current_project_id=cur, occupation=c["occupation"], status=c["status"],
            available_on=c["available_on"], skills=c["skills"], cra_totals=c["cra_totals"],
        )
        db.add(row)
        consultants[c["slug"]] = row
    await db.flush()

    for cslug, pcode, clslug, label, role, period, days, current in MISSIONS:
        db.add(TsMission(
            tenant_id=tenant_id, consultant_id=consultants[cslug].id,
            project_id=projects[pcode].id if pcode else None,
            client_id=clients[clslug].id if clslug else None,
            label=label, role=role, period=period, days=days, current=current,
        ))

    for number, clslug, pcode, period, amount, status, issued in INVOICES:
        db.add(TsInvoice(
            tenant_id=tenant_id, number=number, client_id=clients[clslug].id,
            project_id=projects[pcode].id, period=period, amount=amount, status=status, issued=issued,
        ))

    # activate the timesheet module for this tenant
    await db.execute(delete(TenantEntitlement).where(
        TenantEntitlement.tenant_id == tenant_id, TenantEntitlement.module_key == "timesheet"))
    db.add(TenantEntitlement(tenant_id=tenant_id, module_key="timesheet", status="active", plan="kairos"))

    await db.commit()


async def _main(tenant_id: str) -> None:
    async with async_session() as db:
        await seed_kairos_demo(db, uuid.UUID(tenant_id))
    print(f"Kairos demo seeded for tenant {tenant_id}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m app.modules.timesheet.seed <tenant_id>")
        sys.exit(1)
    asyncio.run(_main(sys.argv[1]))
