"""candidate_position_id_nullable

Revision ID: 86a6daed18d1
Revises: e8f9a0b1c2d3
Create Date: 2026-03-25 04:40:34.636740
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '86a6daed18d1'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('candidates', 'position_id',
               existing_type=sa.UUID(),
               nullable=True)


def downgrade() -> None:
    op.alter_column('candidates', 'position_id',
               existing_type=sa.UUID(),
               nullable=False)
