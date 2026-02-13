from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import cast, Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_tenant_id
from app.models.analysis import Analysis
from app.models.candidate import Candidate
from app.models.interview import Interview
from app.models.position import Position
from app.models.report import Report
from app.schemas.interview import ReportResponse
from app.schemas.report import PaginatedReports, ReportListItem

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_model=PaginatedReports)
async def list_reports(
    position_id: UUID | None = Query(None),
    candidate_name: str | None = Query(None),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    min_score: float | None = Query(None, ge=0, le=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    List all reports with optional filters.

    Tenant isolation is enforced through Interview.tenant_id join.
    Reports are paginated and ordered by generation date (newest first).
    """
    # Base query with all necessary joins
    base_query = (
        select(
            Report.id,
            Report.candidate_id,
            Report.interview_id,
            Report.content,
            Report.pdf_file_path,
            Report.generated_at,
            Candidate.name.label("candidate_name"),
            Interview.position_id,
            Position.title.label("position_title"),
            Analysis.scores,
        )
        .join(Interview, Report.interview_id == Interview.id)
        .join(Candidate, Report.candidate_id == Candidate.id)
        .join(Position, Interview.position_id == Position.id)
        .outerjoin(Analysis, Analysis.interview_id == Interview.id)
        .where(Interview.tenant_id == tenant_id)
    )

    # Apply optional filters
    if position_id:
        base_query = base_query.where(Interview.position_id == position_id)

    if candidate_name:
        base_query = base_query.where(Candidate.name.ilike(f"%{candidate_name}%"))

    if date_from:
        base_query = base_query.where(Report.generated_at >= date_from)

    if date_to:
        base_query = base_query.where(Report.generated_at <= date_to)

    if min_score is not None:
        # Filter where Analysis.scores is not null and scores['global'] >= min_score
        base_query = base_query.where(
            Analysis.scores.isnot(None),
            cast(Analysis.scores["global"].astext, Float) >= min_score,
        )

    # Count total matching records
    count_query = select(func.count()).select_from(base_query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Apply ordering and pagination
    offset = (page - 1) * page_size
    query = base_query.order_by(Report.generated_at.desc()).offset(offset).limit(page_size)

    result = await db.execute(query)
    rows = result.all()

    # Build response items
    items = []
    for row in rows:
        # Extract global_score from Analysis.scores JSONB
        global_score = None
        if row.scores is not None and "global" in row.scores:
            global_score = float(row.scores["global"])

        # Extract summary from Report.content JSONB and truncate to 200 chars
        summary = None
        if row.content is not None and "summary" in row.content:
            raw_summary = row.content["summary"]
            if isinstance(raw_summary, str):
                summary = raw_summary[:200]

        has_pdf = bool(row.pdf_file_path)

        items.append(
            ReportListItem(
                id=str(row.id),
                candidate_id=str(row.candidate_id),
                candidate_name=row.candidate_name,
                interview_id=str(row.interview_id),
                position_id=str(row.position_id),
                position_title=row.position_title,
                global_score=global_score,
                summary=summary,
                generated_at=row.generated_at,
                has_pdf=has_pdf,
            )
        )

    return PaginatedReports(items=items, total=total, page=page, page_size=page_size)


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report_by_id(
    report_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a single report by ID.

    Tenant isolation is enforced through Interview.tenant_id join.
    Returns full report content including all fields.
    """
    query = (
        select(Report)
        .join(Interview, Report.interview_id == Interview.id)
        .where(Report.id == report_id, Interview.tenant_id == tenant_id)
    )

    result = await db.execute(query)
    report = result.scalar_one_or_none()

    if not report:
        raise HTTPException(status_code=404, detail="Rapport introuvable")

    return ReportResponse(
        id=str(report.id),
        candidate_id=str(report.candidate_id),
        interview_id=str(report.interview_id),
        content=report.content,
        pdf_file_path=report.pdf_file_path,
        generated_at=report.generated_at,
    )
