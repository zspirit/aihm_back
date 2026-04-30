"""add_psychometrics

Revision ID: a7c9e1b3d5f8
Revises: f5d7e9c1a2b3
Create Date: 2026-04-29 22:00:00.000000

Phase 4.1 du V1_ROADMAP — table psychometric_assessments.

5-question post-interview assessment, one row per interview. Raw 1–5
scores filled at submission, traits_json + turnover_risk filled async
by Claude analysis.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'a7c9e1b3d5f8'
down_revision: Union[str, None] = 'f5d7e9c1a2b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'psychometric_assessments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('interview_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('submitted_by', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('score_communication', sa.Integer(), nullable=False),
        sa.Column('score_problem_solving', sa.Integer(), nullable=False),
        sa.Column('score_team_fit', sa.Integer(), nullable=False),
        sa.Column('score_stress_handling', sa.Integer(), nullable=False),
        sa.Column('score_leadership', sa.Integer(), nullable=False),
        sa.Column('traits_json', postgresql.JSONB(), nullable=True),
        sa.Column('turnover_risk', sa.String(10), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('now()')),
        sa.Column('analyzed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['interview_id'], ['interviews.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submitted_by'], ['users.id']),
        sa.UniqueConstraint('interview_id', name='uq_psycho_interview'),
    )
    op.create_index('ix_psychometric_assessments_tenant_id', 'psychometric_assessments', ['tenant_id'])
    op.create_index('ix_psychometric_assessments_interview_id', 'psychometric_assessments', ['interview_id'])
    op.create_index('ix_psychometric_assessments_candidate_id', 'psychometric_assessments', ['candidate_id'])


def downgrade() -> None:
    op.drop_index('ix_psychometric_assessments_candidate_id', table_name='psychometric_assessments')
    op.drop_index('ix_psychometric_assessments_interview_id', table_name='psychometric_assessments')
    op.drop_index('ix_psychometric_assessments_tenant_id', table_name='psychometric_assessments')
    op.drop_table('psychometric_assessments')
