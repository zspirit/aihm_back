"""kairos_expenses

Revision ID: a6c8e0b2d4f7
Revises: f5a7c9e1b3d6
Create Date: 2026-06-18 12:00:00.000000

Notes de frais consultant (EPIC G) : ts_expenses (Km/repas/transport…),
workflow draft→submitted→approved|rejected→reimbursed + justificatif.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'a6c8e0b2d4f7'
down_revision: Union[str, None] = 'f5a7c9e1b3d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ts_expenses',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('consultant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('expense_date', sa.Date(), nullable=False),
        sa.Column('month', sa.String(7), nullable=False),
        sa.Column('type', sa.String(30), nullable=False),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False, server_default='0'),
        sa.Column('km', sa.Float(), nullable=True),
        sa.Column('km_rate', sa.Float(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('receipt_document_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reimbursed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reject_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['consultant_id'], ['ts_consultants.id']),
        sa.ForeignKeyConstraint(['project_id'], ['ts_projects.id']),
    )
    op.create_index('ix_ts_expenses_tenant_status', 'ts_expenses', ['tenant_id', 'status'])
    op.create_index('ix_ts_expenses_consultant', 'ts_expenses', ['consultant_id'])


def downgrade() -> None:
    op.drop_index('ix_ts_expenses_consultant', table_name='ts_expenses')
    op.drop_index('ix_ts_expenses_tenant_status', table_name='ts_expenses')
    op.drop_table('ts_expenses')
