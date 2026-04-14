"""add_enterprise_and_offer_tables

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-04-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Create enterprises table ---
    op.create_table(
        'enterprises',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('industry', sa.String(100), nullable=True),
        sa.Column('domain', sa.String(255), nullable=True),
        sa.Column('contact_email', sa.String(255), nullable=True),
        sa.Column('contact_phone', sa.String(20), nullable=True),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='active'),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # --- Index on enterprises ---
    op.create_index('ix_enterprises_tenant_id', 'enterprises', ['tenant_id'])
    op.create_index('ix_enterprises_created_by', 'enterprises', ['created_by'])

    # --- RLS on enterprises ---
    op.execute("ALTER TABLE enterprises ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY enterprises_tenant_isolation ON enterprises
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)

    # --- Add enterprise_id to positions ---
    op.add_column('positions', sa.Column('enterprise_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_positions_enterprise_id', 'positions', 'enterprises', ['enterprise_id'], ['id'])
    op.create_index('ix_positions_enterprise_id', 'positions', ['enterprise_id'])

    # --- Create offers table ---
    op.create_table(
        'offers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('enterprise_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('enterprises.id'), nullable=False),
        sa.Column('application_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('applications.id'), nullable=False),
        sa.Column('salary_min', sa.Float(), nullable=True),
        sa.Column('salary_max', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(3), nullable=False, server_default='EUR'),
        sa.Column('contract_type', sa.String(50), nullable=False, server_default='permanent'),
        sa.Column('start_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('benefits', sa.Text(), nullable=True),
        sa.Column('additional_info', sa.Text(), nullable=True),
        sa.Column('signature_token', sa.String(255), nullable=True),
        sa.Column('signature_link', sa.String(500), nullable=True),
        sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('signed_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='draft'),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # --- Index on offers ---
    op.create_index('ix_offers_tenant_id', 'offers', ['tenant_id'])
    op.create_index('ix_offers_enterprise_id', 'offers', ['enterprise_id'])
    op.create_index('ix_offers_application_id', 'offers', ['application_id'], unique=True)
    op.create_index('ix_offers_status', 'offers', ['status'])

    # --- RLS on offers ---
    op.execute("ALTER TABLE offers ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY offers_tenant_isolation ON offers
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)


def downgrade() -> None:
    # --- Drop RLS on offers ---
    op.execute("DROP POLICY IF EXISTS offers_tenant_isolation ON offers")

    # --- Drop indexes on offers ---
    op.drop_index('ix_offers_status', table_name='offers')
    op.drop_index('ix_offers_application_id', table_name='offers')
    op.drop_index('ix_offers_enterprise_id', table_name='offers')
    op.drop_index('ix_offers_tenant_id', table_name='offers')

    # --- Drop offers table ---
    op.drop_table('offers')

    # --- Drop enterprise_id from positions ---
    op.drop_index('ix_positions_enterprise_id', table_name='positions')
    op.drop_constraint('fk_positions_enterprise_id', 'positions', type_='foreignkey')
    op.drop_column('positions', 'enterprise_id')

    # --- Drop RLS on enterprises ---
    op.execute("DROP POLICY IF EXISTS enterprises_tenant_isolation ON enterprises")

    # --- Drop indexes on enterprises ---
    op.drop_index('ix_enterprises_created_by', table_name='enterprises')
    op.drop_index('ix_enterprises_tenant_id', table_name='enterprises')

    # --- Drop enterprises table ---
    op.drop_table('enterprises')
