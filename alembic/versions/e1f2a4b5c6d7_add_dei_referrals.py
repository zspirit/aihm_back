"""add_dei_referrals

Revision ID: e1f2a4b5c6d7
Revises: d0e1f2a4b5c6
Create Date: 2026-04-27 00:00:00.000000

Phase 4.2 + 4.3 — Champs DEI optionnels sur candidate + tokens referral sur user.
"""
from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'e1f2a4b5c6d7'
down_revision: Union[str, None] = 'd0e1f2a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Phase 4.2 — DEI optionnel (candidat opt-in)
    op.add_column('candidates', sa.Column('dei_consent', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('candidates', sa.Column('gender', sa.String(length=30), nullable=True))
    op.add_column('candidates', sa.Column('age_range', sa.String(length=20), nullable=True))  # 18-25, 26-35, ...
    op.add_column('candidates', sa.Column('nationality', sa.String(length=50), nullable=True))
    op.add_column('candidates', sa.Column('disability_status', sa.String(length=20), nullable=True))

    # Phase 4.3 — Referral token sur user (lien a partager)
    op.add_column('users', sa.Column('referral_token', sa.String(length=64), nullable=True))
    op.create_unique_constraint('uq_users_referral_token', 'users', ['referral_token'])
    op.create_index('ix_users_referral_token', 'users', ['referral_token'])


def downgrade() -> None:
    op.drop_index('ix_users_referral_token', table_name='users')
    op.drop_constraint('uq_users_referral_token', 'users', type_='unique')
    op.drop_column('users', 'referral_token')
    op.drop_column('candidates', 'disability_status')
    op.drop_column('candidates', 'nationality')
    op.drop_column('candidates', 'age_range')
    op.drop_column('candidates', 'gender')
    op.drop_column('candidates', 'dei_consent')
