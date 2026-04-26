"""add_user_integrations

Revision ID: c9d0e1f2a4b5
Revises: b8c9d0e1f2a4
Create Date: 2026-04-26 23:00:00.000000

Phase 2.3 — table user_integrations pour OAuth tokens (Google + MS Calendar).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'c9d0e1f2a4b5'
down_revision: Union[str, None] = 'b8c9d0e1f2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_integrations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('access_token_encrypted', sa.Text(), nullable=True),
        sa.Column('refresh_token_encrypted', sa.Text(), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('account_email', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.UniqueConstraint('user_id', 'provider', name='uq_user_provider'),
    )
    op.create_index('ix_user_integrations_tenant_id', 'user_integrations', ['tenant_id'])
    op.create_index('ix_user_integrations_user_id', 'user_integrations', ['user_id'])
    op.create_index('ix_user_integrations_status', 'user_integrations', ['status'])


def downgrade() -> None:
    op.drop_index('ix_user_integrations_status', table_name='user_integrations')
    op.drop_index('ix_user_integrations_user_id', table_name='user_integrations')
    op.drop_index('ix_user_integrations_tenant_id', table_name='user_integrations')
    op.drop_table('user_integrations')
