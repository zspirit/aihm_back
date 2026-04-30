"""Tasks endpoints — Phase 4.5 CRM.

Tasks are the recruiter's lightweight to-do queue. They can be free-floating
or attached to any entity (candidate, position, interview, offer).

POST   /tasks                          create
GET    /tasks                          list with filters
GET    /tasks/{id}                     get
PATCH  /tasks/{id}                     update (incl. mark done/cancelled)
DELETE /tasks/{id}                     hard delete

Filters: status, assignee_id (or 'me'), entity_type, entity_id, overdue
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.task import Task
from app.models.user import User

router = APIRouter(tags=["tasks"])


# ─── Schemas ──────────────────────────────────────────────────────────────────


class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    entity_type: Optional[str] = Field(None, max_length=50)
    entity_id: Optional[UUID] = None
    assignee_id: Optional[UUID] = None
    due_date: Optional[datetime] = None


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    assignee_id: Optional[UUID] = None
    due_date: Optional[datetime] = None
    status: Optional[str] = Field(None, pattern="^(pending|done|cancelled)$")


class TaskResponse(BaseModel):
    id: UUID
    title: str
    description: Optional[str]
    entity_type: Optional[str]
    entity_id: Optional[UUID]
    assignee_id: Optional[UUID]
    created_by: UUID
    status: str
    due_date: Optional[datetime]
    created_at: datetime
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


# ─── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # If assignee specified, validate same-tenant.
    if payload.assignee_id:
        assignee = await db.get(User, payload.assignee_id)
        if assignee is None or assignee.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=400, detail="invalid assignee")

    task = Task(
        tenant_id=current_user.tenant_id,
        created_by=current_user.id,
        title=payload.title,
        description=payload.description,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        assignee_id=payload.assignee_id,
        due_date=payload.due_date,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    status: Optional[str] = Query(None, pattern="^(pending|done|cancelled)$"),
    assignee_id: Optional[str] = Query(None, description="UUID, or 'me' for current user"),
    entity_type: Optional[str] = Query(None, max_length=50),
    entity_id: Optional[UUID] = None,
    overdue: bool = Query(False, description="Only pending tasks past due_date"),
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Task).where(Task.tenant_id == current_user.tenant_id)

    if status:
        stmt = stmt.where(Task.status == status)
    if assignee_id:
        if assignee_id == "me":
            stmt = stmt.where(Task.assignee_id == current_user.id)
        else:
            try:
                stmt = stmt.where(Task.assignee_id == UUID(assignee_id))
            except ValueError:
                raise HTTPException(status_code=400, detail="assignee_id must be a UUID or 'me'")
    if entity_type:
        stmt = stmt.where(Task.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(Task.entity_id == entity_id)
    if overdue:
        now = datetime.now(timezone.utc)
        stmt = stmt.where(
            Task.status == "pending",
            Task.due_date.isnot(None),
            Task.due_date < now,
        )

    stmt = stmt.order_by(desc(Task.created_at)).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return rows


@router.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if task is None or task.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="task not found")
    return task


@router.patch("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: UUID,
    payload: TaskUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if task is None or task.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="task not found")

    if payload.assignee_id is not None:
        assignee = await db.get(User, payload.assignee_id)
        if assignee is None or assignee.tenant_id != current_user.tenant_id:
            raise HTTPException(status_code=400, detail="invalid assignee")
        task.assignee_id = payload.assignee_id

    if payload.title is not None:
        task.title = payload.title
    if payload.description is not None:
        task.description = payload.description
    if payload.due_date is not None:
        task.due_date = payload.due_date

    if payload.status is not None and payload.status != task.status:
        task.status = payload.status
        if payload.status in ("done", "cancelled"):
            task.completed_at = datetime.now(timezone.utc)
        else:
            task.completed_at = None

    await db.commit()
    await db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if task is None or task.tenant_id != current_user.tenant_id:
        raise HTTPException(status_code=404, detail="task not found")
    await db.delete(task)
    await db.commit()
