"""add_tenant_career_page

Revision ID: d0e1f2a4b5c6
Revises: c9d0e1f2a4b5
Create Date: 2026-04-26 23:30:00.000000

Phase 3.1 — flag career_page + slug + branding sur Tenant.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'd0e1f2a4b5c6'
down_revision: Union[str, None] = 'c9d0e1f2a4b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenants', sa.Column('public_career_page', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('tenants', sa.Column('public_slug', sa.String(length=100), nullable=True))
    op.add_column('tenants', sa.Column('public_branding', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.create_unique_constraint('uq_tenants_public_slug', 'tenants', ['public_slug'])

    op.add_column('positions', sa.Column('public_slug', sa.String(length=200), nullable=True))

    op.add_column('applications', sa.Column('source', sa.String(length=50), nullable=True))
    op.add_column('applications', sa.Column('referrer_user_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        'fk_applications_referrer_user_id', 'applications', 'users',
        ['referrer_user_id'], ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_applications_referrer_user_id', 'applications', type_='foreignkey')
    op.drop_column('applications', 'referrer_user_id')
    op.drop_column('applications', 'source')
    op.drop_column('positions', 'public_slug')
    op.drop_constraint('uq_tenants_public_slug', 'tenants', type_='unique')
    op.drop_column('tenants', 'public_branding')
    op.drop_column('tenants', 'public_slug')
    op.drop_column('tenants', 'public_career_page')
