"""add_candidate_comments

Revision ID: c1f3e2d40a11
Revises: 5b4019cbbf6e
Create Date: 2026-04-26 18:30:00.000000

Phase 1.1 du V1_ROADMAP — table `candidate_comments` pour permettre
aux equipes de discuter autour d'une fiche candidat (threads, mentions).

Schema :
- id (UUID PK)
- tenant_id (FK tenants, indexe pour RLS)
- candidate_id (FK candidates ON DELETE CASCADE, indexe)
- author_id (FK users)
- parent_id (UUID nullable, self-FK ON DELETE CASCADE pour threads)
- content (TEXT, markdown libre)
- mentioned_user_ids (JSONB, liste UUID stockee comme strings)
- created_at, edited_at, deleted_at (soft delete)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'c1f3e2d40a11'
down_revision: Union[str, None] = '5b4019cbbf6e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'candidate_comments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('author_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('mentioned_user_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('edited_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.ForeignKeyConstraint(['parent_id'], ['candidate_comments.id'], ondelete='CASCADE'),
    )

    op.create_index(
        'ix_candidate_comments_tenant_id',
        'candidate_comments',
        ['tenant_id'],
    )
    op.create_index(
        'ix_candidate_comments_candidate_id',
        'candidate_comments',
        ['candidate_id'],
    )
    op.create_index(
        'ix_candidate_comments_parent_id',
        'candidate_comments',
        ['parent_id'],
    )
    op.create_index(
        'ix_candidate_comments_deleted_at',
        'candidate_comments',
        ['deleted_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_candidate_comments_deleted_at', table_name='candidate_comments')
    op.drop_index('ix_candidate_comments_parent_id', table_name='candidate_comments')
    op.drop_index('ix_candidate_comments_candidate_id', table_name='candidate_comments')
    op.drop_index('ix_candidate_comments_tenant_id', table_name='candidate_comments')
    op.drop_table('candidate_comments')
