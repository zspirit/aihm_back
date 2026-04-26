"""add_email_templates_logs

Revision ID: a7e8f9b1c2d3
Revises: f4c6e8a019b2
Create Date: 2026-04-26 22:00:00.000000

Phase 2.1 — tables email_templates + email_logs.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'a7e8f9b1c2d3'
down_revision: Union[str, None] = 'f4c6e8a019b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_templates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False, server_default='generic'),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('body_markdown', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
    )
    op.create_index('ix_email_templates_tenant_id', 'email_templates', ['tenant_id'])
    op.create_index('ix_email_templates_type', 'email_templates', ['type'])

    op.create_table(
        'email_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('sent_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('to_email', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('body_rendered', sa.Text(), nullable=False),
        sa.Column('variables', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='queued'),
        sa.Column('provider', sa.String(length=50), nullable=True),
        sa.Column('provider_message_id', sa.String(length=255), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['template_id'], ['email_templates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['sent_by'], ['users.id']),
    )
    op.create_index('ix_email_logs_tenant_id', 'email_logs', ['tenant_id'])
    op.create_index('ix_email_logs_candidate_id', 'email_logs', ['candidate_id'])
    op.create_index('ix_email_logs_status', 'email_logs', ['status'])


def downgrade() -> None:
    op.drop_index('ix_email_logs_status', table_name='email_logs')
    op.drop_index('ix_email_logs_candidate_id', table_name='email_logs')
    op.drop_index('ix_email_logs_tenant_id', table_name='email_logs')
    op.drop_table('email_logs')
    op.drop_index('ix_email_templates_type', table_name='email_templates')
    op.drop_index('ix_email_templates_tenant_id', table_name='email_templates')
    op.drop_table('email_templates')
