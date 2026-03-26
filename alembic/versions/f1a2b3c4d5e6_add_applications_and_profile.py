"""add_applications_and_profile

Revision ID: f1a2b3c4d5e6
Revises: e9b7c6eac402
Create Date: 2026-03-25 16:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e9b7c6eac402'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Ajouter les colonnes profil sur candidates ---
    op.add_column('candidates', sa.Column('profile_score', sa.Float(), nullable=True))
    op.add_column('candidates', sa.Column('profile_score_explanation', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('candidates', sa.Column('profile_competencies', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('candidates', sa.Column('profile_suggestions', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('candidates', sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='[]'))
    op.add_column('candidates', sa.Column('notes', sa.Text(), nullable=True))

    # --- Creer la table applications ---
    op.create_table(
        'applications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('tenants.id'), nullable=False),
        sa.Column('candidate_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('candidates.id', ondelete='CASCADE'), nullable=False),
        sa.Column('position_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('positions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('match_score', sa.Float(), nullable=True),
        sa.Column('match_score_explanation', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('pipeline_status', sa.String(50), nullable=False, server_default='new'),
        sa.Column('decision', sa.String(50), nullable=True),
        sa.Column('decision_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    )

    # --- Index sur applications ---
    op.create_index('ix_applications_candidate_position', 'applications', ['candidate_id', 'position_id'])
    op.create_index('ix_applications_tenant_id', 'applications', ['tenant_id'])
    op.create_index('ix_applications_position_id', 'applications', ['position_id'])

    # --- RLS sur applications ---
    op.execute("ALTER TABLE applications ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY applications_tenant_isolation ON applications
        USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    """)


def downgrade() -> None:
    # --- Supprimer RLS ---
    op.execute("DROP POLICY IF EXISTS applications_tenant_isolation ON applications")

    # --- Supprimer index ---
    op.drop_index('ix_applications_position_id', table_name='applications')
    op.drop_index('ix_applications_tenant_id', table_name='applications')
    op.drop_index('ix_applications_candidate_position', table_name='applications')

    # --- Supprimer table applications ---
    op.drop_table('applications')

    # --- Supprimer colonnes profil sur candidates ---
    op.drop_column('candidates', 'notes')
    op.drop_column('candidates', 'tags')
    op.drop_column('candidates', 'profile_suggestions')
    op.drop_column('candidates', 'profile_competencies')
    op.drop_column('candidates', 'profile_score_explanation')
    op.drop_column('candidates', 'profile_score')
