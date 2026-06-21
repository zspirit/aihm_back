"""kairos_contacts

Revision ID: e0b2d4f6a8c1
Revises: d9f1b3c5e7a0
Create Date: 2026-06-18 16:00:00.000000

Demandes de contact consultant → management (EPIC K) : ts_contact_requests
(statut open/in_progress/resolved) + ts_contact_messages (fil de conversation).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'e0b2d4f6a8c1'
down_revision: Union[str, None] = 'd9f1b3c5e7a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ts_contact_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('consultant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('subject', sa.String(200), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['consultant_id'], ['ts_consultants.id']),
    )
    op.create_index('ix_ts_contacts_tenant_status', 'ts_contact_requests', ['tenant_id', 'status'])
    op.create_index('ix_ts_contacts_consultant', 'ts_contact_requests', ['consultant_id'])

    op.create_table(
        'ts_contact_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('request_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('author_user_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('author_role', sa.String(20), nullable=False),
        sa.Column('author_name', sa.String(120), nullable=True),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['request_id'], ['ts_contact_requests.id']),
    )
    op.create_index('ix_ts_contact_msgs_request', 'ts_contact_messages', ['request_id'])


def downgrade() -> None:
    op.drop_index('ix_ts_contact_msgs_request', table_name='ts_contact_messages')
    op.drop_table('ts_contact_messages')
    op.drop_index('ix_ts_contacts_consultant', table_name='ts_contact_requests')
    op.drop_index('ix_ts_contacts_tenant_status', table_name='ts_contact_requests')
    op.drop_table('ts_contact_requests')
