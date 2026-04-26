"""add_shortlists

Revision ID: d2a4c5e6f8b1
Revises: c1f3e2d40a11
Create Date: 2026-04-26 19:00:00.000000

Phase 1.2 du V1_ROADMAP — tables `shortlists` et `shortlist_candidates`.

Permet aux equipes de creer des selections nommees de candidats partagees
au sein d'un tenant (ex: "Top 5 backend Python" pour un poste donne).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'd2a4c5e6f8b1'
down_revision: Union[str, None] = 'c1f3e2d40a11'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'shortlists',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['owner_id'], ['users.id']),
        sa.ForeignKeyConstraint(['position_id'], ['positions.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_shortlists_tenant_id', 'shortlists', ['tenant_id'])
    op.create_index('ix_shortlists_owner_id', 'shortlists', ['owner_id'])
    op.create_index('ix_shortlists_position_id', 'shortlists', ['position_id'])

    op.create_table(
        'shortlist_candidates',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('shortlist_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('added_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['shortlist_id'], ['shortlists.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['added_by'], ['users.id']),
        sa.UniqueConstraint('shortlist_id', 'candidate_id', name='uq_shortlist_candidate'),
    )
    op.create_index('ix_shortlist_candidates_shortlist_id', 'shortlist_candidates', ['shortlist_id'])
    op.create_index('ix_shortlist_candidates_candidate_id', 'shortlist_candidates', ['candidate_id'])


def downgrade() -> None:
    op.drop_index('ix_shortlist_candidates_candidate_id', table_name='shortlist_candidates')
    op.drop_index('ix_shortlist_candidates_shortlist_id', table_name='shortlist_candidates')
    op.drop_table('shortlist_candidates')
    op.drop_index('ix_shortlists_position_id', table_name='shortlists')
    op.drop_index('ix_shortlists_owner_id', table_name='shortlists')
    op.drop_index('ix_shortlists_tenant_id', table_name='shortlists')
    op.drop_table('shortlists')
