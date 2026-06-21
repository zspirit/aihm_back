"""kairos_consultant_invoices

Revision ID: b7d9f1a3c5e8
Revises: a6c8e0b2d4f7
Create Date: 2026-06-18 13:00:00.000000

Factures émises par les consultants vers l'ESN (EPIC H) :
ts_consultant_invoices, workflow submitted→received→paid + échéance 45j.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'b7d9f1a3c5e8'
down_revision: Union[str, None] = 'a6c8e0b2d4f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ts_consultant_invoices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('consultant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('number', sa.String(40), nullable=False),
        sa.Column('month', sa.String(7), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='submitted'),
        sa.Column('issue_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('reviewed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['consultant_id'], ['ts_consultants.id']),
    )
    op.create_index('ix_ts_cinv_tenant_status', 'ts_consultant_invoices', ['tenant_id', 'status'])
    op.create_index('ix_ts_cinv_consultant', 'ts_consultant_invoices', ['consultant_id'])


def downgrade() -> None:
    op.drop_index('ix_ts_cinv_consultant', table_name='ts_consultant_invoices')
    op.drop_index('ix_ts_cinv_tenant_status', table_name='ts_consultant_invoices')
    op.drop_table('ts_consultant_invoices')
