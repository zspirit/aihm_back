"""add_position_sla_and_level

Revision ID: 5b4019cbbf6e
Revises: 09607bb8eb7d
Create Date: 2026-04-23 21:30:00.000000

Ajoute les colonnes Postes v2 (Chantier 11):
- positions.level (enum position_level) : niveau hiérarchique
  (junior/mid/senior/lead/manager/executive)
- positions.sla_days (Integer) : durée SLA cible en jours (1-365,
  validation côté Pydantic)
- positions.sla_deadline (TIMESTAMPTZ) : deadline calculée
  = created_at + sla_days jours

Les trois colonnes sont nullables pour rester backward-compatible avec
les positions existantes. L'enum `position_level` est créé en premier
via sa.Enum(..., create_type=True) implicite.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = '5b4019cbbf6e'
down_revision: Union[str, None] = '09607bb8eb7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Définition explicite de l'enum pour maîtriser create_type
# (évite la double création si déjà présent).
position_level_enum = sa.Enum(
    'junior', 'mid', 'senior', 'lead', 'manager', 'executive',
    name='position_level',
)


def upgrade() -> None:
    # 1. Crée le type enum PG explicitement
    position_level_enum.create(op.get_bind(), checkfirst=True)

    # 2. Ajoute les trois colonnes à la table positions
    op.add_column(
        'positions',
        sa.Column('level', position_level_enum, nullable=True),
    )
    op.add_column(
        'positions',
        sa.Column('sla_days', sa.Integer(), nullable=True),
    )
    op.add_column(
        'positions',
        sa.Column('sla_deadline', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    # Ordre inverse: drop des colonnes, puis du type enum
    op.drop_column('positions', 'sla_deadline')
    op.drop_column('positions', 'sla_days')
    op.drop_column('positions', 'level')
    position_level_enum.drop(op.get_bind(), checkfirst=True)
