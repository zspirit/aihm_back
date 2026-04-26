"""add_approval_requests

Revision ID: e3b5d7f912a8
Revises: d2a4c5e6f8b1
Create Date: 2026-04-26 19:30:00.000000

Phase 1.3 du V1_ROADMAP — table approval_requests.

Workflow generique de validation entre coequipiers, applicable a toute
entite (offer, application, position, candidate, ...) via entity_type
+ entity_id.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'e3b5d7f912a8'
down_revision: Union[str, None] = 'd2a4c5e6f8b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'approval_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('requester_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('approver_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('decision_reason', sa.Text(), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['requester_id'], ['users.id']),
        sa.ForeignKeyConstraint(['approver_id'], ['users.id']),
    )
    op.create_index('ix_approval_requests_tenant_id', 'approval_requests', ['tenant_id'])
    op.create_index('ix_approval_requests_requester_id', 'approval_requests', ['requester_id'])
    op.create_index('ix_approval_requests_approver_id', 'approval_requests', ['approver_id'])
    op.create_index('ix_approval_requests_entity_id', 'approval_requests', ['entity_id'])
    op.create_index('ix_approval_requests_status', 'approval_requests', ['status'])


def downgrade() -> None:
    op.drop_index('ix_approval_requests_status', table_name='approval_requests')
    op.drop_index('ix_approval_requests_entity_id', table_name='approval_requests')
    op.drop_index('ix_approval_requests_approver_id', table_name='approval_requests')
    op.drop_index('ix_approval_requests_requester_id', table_name='approval_requests')
    op.drop_index('ix_approval_requests_tenant_id', table_name='approval_requests')
    op.drop_table('approval_requests')
