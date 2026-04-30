"""add_tasks

Revision ID: f5d7e9c1a2b3
Revises: e1f2a4b5c6d7
Create Date: 2026-04-29 21:00:00.000000

Phase 4.5 du V1_ROADMAP — table tasks.

Lightweight to-do system attached to any entity (candidate, position,
interview, offer). Used by recruiters to track follow-ups, reference
checks, hiring-manager pings, etc.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'f5d7e9c1a2b3'
down_revision: Union[str, None] = 'e1f2a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tasks',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('entity_type', sa.String(50), nullable=True),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('assignee_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['assignee_id'], ['users.id']),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
    )
    op.create_index('ix_tasks_tenant_id', 'tasks', ['tenant_id'])
    op.create_index('ix_tasks_status', 'tasks', ['status'])
    op.create_index(
        'ix_tasks_tenant_assignee_status',
        'tasks',
        ['tenant_id', 'assignee_id', 'status'],
    )
    op.create_index('ix_tasks_entity', 'tasks', ['entity_type', 'entity_id'])


def downgrade() -> None:
    op.drop_index('ix_tasks_entity', table_name='tasks')
    op.drop_index('ix_tasks_tenant_assignee_status', table_name='tasks')
    op.drop_index('ix_tasks_status', table_name='tasks')
    op.drop_index('ix_tasks_tenant_id', table_name='tasks')
    op.drop_table('tasks')
