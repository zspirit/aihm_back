"""kairos_timesheet

Revision ID: c2d4f6a8b0e1
Revises: b1f3c5d7e9a2
Create Date: 2026-06-16 14:00:00.000000

Module Kairos / Timesheet (delivery ESN) — tables ts_*.
Sert les écrans du handoff Claude Design (Hub, Projet, Client, Consultant).
Voir .claude/specs/KAIROS_INTEGRATION_PLAN.md.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'c2d4f6a8b0e1'
down_revision: Union[str, None] = 'b1f3c5d7e9a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ts_clients',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('slug', sa.String(80), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('initials', sa.String(8), nullable=True),
        sa.Column('sector', sa.String(120), nullable=True),
        sa.Column('since', sa.String(20), nullable=True),
        sa.Column('health', sa.String(20), nullable=False, server_default='good'),
        sa.Column('location', sa.String(120), nullable=True),
        sa.Column('siret', sa.String(40), nullable=True),
        sa.Column('contact', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.UniqueConstraint('tenant_id', 'slug', name='uq_ts_client_slug'),
    )
    op.create_index('ix_ts_clients_tenant_id', 'ts_clients', ['tenant_id'])

    op.create_table(
        'ts_projects',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(40), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('billing', sa.String(40), nullable=False),
        sa.Column('tjm', sa.Float(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=True),
        sa.Column('status', sa.String(40), nullable=False, server_default='En cours'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('margin', sa.Integer(), nullable=True),
        sa.Column('margin_flag', sa.String(20), nullable=True),
        sa.Column('budget_flag', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('start', sa.String(20), nullable=True),
        sa.Column('end', sa.String(20), nullable=True),
        sa.Column('ends_in', sa.Integer(), nullable=True),
        sa.Column('days_sold', sa.Integer(), nullable=True),
        sa.Column('days_consumed', sa.Integer(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('contract', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['client_id'], ['ts_clients.id']),
        sa.UniqueConstraint('tenant_id', 'code', name='uq_ts_project_code'),
    )
    op.create_index('ix_ts_projects_tenant_id', 'ts_projects', ['tenant_id'])
    op.create_index('ix_ts_projects_client_id', 'ts_projects', ['client_id'])

    op.create_table(
        'ts_consultants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('slug', sa.String(80), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('initials', sa.String(8), nullable=True),
        sa.Column('role', sa.String(120), nullable=True),
        sa.Column('type', sa.String(40), nullable=False, server_default='Salarié'),
        sa.Column('seniority', sa.String(40), nullable=True),
        sa.Column('location', sa.String(120), nullable=True),
        sa.Column('daily_cost', sa.Float(), nullable=True),
        sa.Column('ex_candidate_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('party_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('current_project_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('occupation', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('available_on', sa.String(20), nullable=True),
        sa.Column('skills', postgresql.JSONB(), nullable=True),
        sa.Column('cra_totals', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['party_id'], ['parties.id']),
        sa.ForeignKeyConstraint(['current_project_id'], ['ts_projects.id']),
        sa.UniqueConstraint('tenant_id', 'slug', name='uq_ts_consultant_slug'),
    )
    op.create_index('ix_ts_consultants_tenant_id', 'ts_consultants', ['tenant_id'])

    op.create_table(
        'ts_missions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('consultant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('label', sa.String(255), nullable=True),
        sa.Column('role', sa.String(120), nullable=True),
        sa.Column('period', sa.String(60), nullable=True),
        sa.Column('days', sa.Integer(), nullable=True),
        sa.Column('current', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['consultant_id'], ['ts_consultants.id']),
        sa.ForeignKeyConstraint(['project_id'], ['ts_projects.id']),
        sa.ForeignKeyConstraint(['client_id'], ['ts_clients.id']),
    )
    op.create_index('ix_ts_missions_consultant_id', 'ts_missions', ['consultant_id'])
    op.create_index('ix_ts_missions_client_id', 'ts_missions', ['client_id'])

    op.create_table(
        'ts_cra_months',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('month', sa.String(40), nullable=False),
        sa.Column('days', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='à facturer'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['project_id'], ['ts_projects.id']),
    )
    op.create_index('ix_ts_cra_months_project_id', 'ts_cra_months', ['project_id'])

    op.create_table(
        'ts_invoices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('number', sa.String(40), nullable=False),
        sa.Column('client_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('period', sa.String(40), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='à émettre'),
        sa.Column('issued', sa.String(20), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['client_id'], ['ts_clients.id']),
        sa.ForeignKeyConstraint(['project_id'], ['ts_projects.id']),
        sa.UniqueConstraint('tenant_id', 'number', name='uq_ts_invoice_number'),
    )
    op.create_index('ix_ts_invoices_tenant_id', 'ts_invoices', ['tenant_id'])

    op.create_table(
        'ts_time_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('consultant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('project_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('absence_code', sa.String(8), nullable=True),
        sa.Column('entry_date', sa.Date(), nullable=False),
        sa.Column('month', sa.String(40), nullable=False),
        sa.Column('value', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('source', sa.String(20), nullable=False, server_default='manual'),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['consultant_id'], ['ts_consultants.id']),
        sa.ForeignKeyConstraint(['project_id'], ['ts_projects.id']),
    )
    op.create_index('ix_ts_time_entries_consultant_id', 'ts_time_entries', ['consultant_id'])


def downgrade() -> None:
    op.drop_table('ts_time_entries')
    op.drop_index('ix_ts_invoices_tenant_id', table_name='ts_invoices')
    op.drop_table('ts_invoices')
    op.drop_index('ix_ts_cra_months_project_id', table_name='ts_cra_months')
    op.drop_table('ts_cra_months')
    op.drop_index('ix_ts_missions_client_id', table_name='ts_missions')
    op.drop_index('ix_ts_missions_consultant_id', table_name='ts_missions')
    op.drop_table('ts_missions')
    op.drop_index('ix_ts_consultants_tenant_id', table_name='ts_consultants')
    op.drop_table('ts_consultants')
    op.drop_index('ix_ts_projects_client_id', table_name='ts_projects')
    op.drop_index('ix_ts_projects_tenant_id', table_name='ts_projects')
    op.drop_table('ts_projects')
    op.drop_index('ix_ts_clients_tenant_id', table_name='ts_clients')
    op.drop_table('ts_clients')
