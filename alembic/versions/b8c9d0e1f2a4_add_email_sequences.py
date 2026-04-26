"""add_email_sequences

Revision ID: b8c9d0e1f2a4
Revises: a7e8f9b1c2d3
Create Date: 2026-04-26 22:30:00.000000

Phase 2.2 — sequences + steps + enrollments.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'b8c9d0e1f2a4'
down_revision: Union[str, None] = 'a7e8f9b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'email_sequences',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('trigger', sa.String(length=50), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
    )
    op.create_index('ix_email_sequences_tenant_id', 'email_sequences', ['tenant_id'])
    op.create_index('ix_email_sequences_trigger', 'email_sequences', ['trigger'])

    op.create_table(
        'sequence_steps',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('sequence_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('delay_hours', sa.Integer(), nullable=False, server_default='24'),
        sa.ForeignKeyConstraint(['sequence_id'], ['email_sequences.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['template_id'], ['email_templates.id'], ondelete='RESTRICT'),
    )
    op.create_index('ix_sequence_steps_sequence_id', 'sequence_steps', ['sequence_id'])

    op.create_table(
        'sequence_enrollments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('sequence_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('current_step_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='active'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['sequence_id'], ['email_sequences.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_sequence_enrollments_tenant_id', 'sequence_enrollments', ['tenant_id'])
    op.create_index('ix_sequence_enrollments_candidate_id', 'sequence_enrollments', ['candidate_id'])
    op.create_index('ix_sequence_enrollments_next_run_at', 'sequence_enrollments', ['next_run_at'])
    op.create_index('ix_sequence_enrollments_status', 'sequence_enrollments', ['status'])


def downgrade() -> None:
    for name in ['ix_sequence_enrollments_status', 'ix_sequence_enrollments_next_run_at',
                 'ix_sequence_enrollments_candidate_id', 'ix_sequence_enrollments_tenant_id']:
        op.drop_index(name, table_name='sequence_enrollments')
    op.drop_table('sequence_enrollments')
    op.drop_index('ix_sequence_steps_sequence_id', table_name='sequence_steps')
    op.drop_table('sequence_steps')
    op.drop_index('ix_email_sequences_trigger', table_name='email_sequences')
    op.drop_index('ix_email_sequences_tenant_id', table_name='email_sequences')
    op.drop_table('email_sequences')
