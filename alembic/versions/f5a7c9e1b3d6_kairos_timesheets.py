"""kairos_timesheets

Revision ID: f5a7c9e1b3d6
Revises: e4f6b8d0c2a5
Create Date: 2026-06-18 10:00:00.000000

Workflow de validation du timesheet mensuel (EPIC E) : ts_timesheets
(consultant × mois × statut draft|submitted|approved|rejected).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'f5a7c9e1b3d6'
down_revision: Union[str, None] = 'e4f6b8d0c2a5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ts_timesheets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('consultant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('month', sa.String(7), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('worked_days', sa.Float(), nullable=False, server_default='0'),
        sa.Column('absence_days', sa.Float(), nullable=False, server_default='0'),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reject_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['consultant_id'], ['ts_consultants.id']),
        sa.UniqueConstraint('tenant_id', 'consultant_id', 'month', name='uq_ts_timesheet'),
    )
    op.create_index('ix_ts_timesheets_tenant_status', 'ts_timesheets', ['tenant_id', 'status'])
    op.create_index('ix_ts_timesheets_consultant', 'ts_timesheets', ['consultant_id'])


def downgrade() -> None:
    op.drop_index('ix_ts_timesheets_consultant', table_name='ts_timesheets')
    op.drop_index('ix_ts_timesheets_tenant_status', table_name='ts_timesheets')
    op.drop_table('ts_timesheets')
