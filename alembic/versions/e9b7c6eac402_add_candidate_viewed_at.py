"""add_candidate_viewed_at

Revision ID: e9b7c6eac402
Revises: 86a6daed18d1
Create Date: 2026-03-25 14:57:58.375631
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e9b7c6eac402'
down_revision: Union[str, None] = '86a6daed18d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidates', sa.Column('viewed_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('candidates', 'viewed_at')
