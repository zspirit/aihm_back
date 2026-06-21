"""platform_poc_parties

Revision ID: b1f3c5d7e9a2
Revises: a7c9e1b3d5f8
Create Date: 2026-06-16 12:00:00.000000

POC plateforme modulaire (ADR-01/ADR-05) — coutures du socle :
- parties / party_facets : modèle People unifié (candidat → consultant →
  salarié = une personne, plusieurs facettes contribuées par les modules).
- tenant_entitlements : quel module un tenant a activé (feature-flags + billing).
- domain_events : log append-only des événements inter-modules (+ futurs webhooks).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'b1f3c5d7e9a2'
down_revision: Union[str, None] = 'a7c9e1b3d5f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'parties',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False, server_default='person'),
        sa.Column('display_name', sa.String(255), nullable=False),
        sa.Column('emails', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
    )
    op.create_index('ix_parties_tenant_id', 'parties', ['tenant_id'])

    op.create_table(
        'party_facets',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('party_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('facet', sa.String(40), nullable=False),
        sa.Column('module_key', sa.String(40), nullable=False),
        sa.Column('data', postgresql.JSONB(), nullable=True),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['party_id'], ['parties.id']),
    )
    op.create_index('ix_party_facets_party_id', 'party_facets', ['party_id'])
    op.create_index('ix_party_facets_party_facet', 'party_facets', ['party_id', 'facet'])

    op.create_table(
        'tenant_entitlements',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('module_key', sa.String(40), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='active'),
        sa.Column('plan', sa.String(40), nullable=True),
        sa.Column('seats', sa.Integer(), nullable=True),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.UniqueConstraint('tenant_id', 'module_key', name='uq_tenant_entitlement'),
    )
    op.create_index('ix_tenant_entitlements_tenant_id', 'tenant_entitlements', ['tenant_id'])

    op.create_table(
        'domain_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.String(80), nullable=False),
        sa.Column('source_module', sa.String(40), nullable=False),
        sa.Column('payload', postgresql.JSONB(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
    )
    op.create_index('ix_domain_events_tenant_id', 'domain_events', ['tenant_id'])
    op.create_index('ix_domain_events_type', 'domain_events', ['type'])


def downgrade() -> None:
    op.drop_index('ix_domain_events_type', table_name='domain_events')
    op.drop_index('ix_domain_events_tenant_id', table_name='domain_events')
    op.drop_table('domain_events')
    op.drop_index('ix_tenant_entitlements_tenant_id', table_name='tenant_entitlements')
    op.drop_table('tenant_entitlements')
    op.drop_index('ix_party_facets_party_facet', table_name='party_facets')
    op.drop_index('ix_party_facets_party_id', table_name='party_facets')
    op.drop_table('party_facets')
    op.drop_index('ix_parties_tenant_id', table_name='parties')
    op.drop_table('parties')
