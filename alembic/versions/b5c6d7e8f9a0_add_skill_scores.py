"""add skill_scores column to analyses

Revision ID: b5c6d7e8f9a0
Revises: a3b7c9d1e5f2
Create Date: 2026-02-13 18:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a3b7c9d1e5f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("skill_scores", postgresql.JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "skill_scores")
