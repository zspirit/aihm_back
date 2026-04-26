"""add_position_workflow_status

Revision ID: f4c6e8a019b2
Revises: e3b5d7f912a8
Create Date: 2026-04-26 21:00:00.000000

Phase 1.5 — Workflow de validation poste.

Le champ `status` (String) existe deja sur positions (libre : draft/active/closed).
On ajoute un workflow_status optionnel pour les tenants qui veulent un cycle
formel : draft -> pending_approval -> approved -> active -> closed.

Le champ reste nullable pour ne pas casser les positions existantes.
Une `submitted_for_approval_at` permet d'auditer la demande.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'f4c6e8a019b2'
down_revision: Union[str, None] = 'e3b5d7f912a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'positions',
        sa.Column('workflow_status', sa.String(length=30), nullable=True),
    )
    op.add_column(
        'positions',
        sa.Column('submitted_for_approval_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'positions',
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('positions', 'approved_at')
    op.drop_column('positions', 'submitted_for_approval_at')
    op.drop_column('positions', 'workflow_status')
