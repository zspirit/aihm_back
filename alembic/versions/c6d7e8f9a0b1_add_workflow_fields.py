"""add workflow automation fields to positions

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-02-13 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c6d7e8f9a0b1"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("positions", sa.Column("auto_advance_threshold", sa.Integer(), nullable=True))
    op.add_column("positions", sa.Column("auto_reject_threshold", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("positions", "auto_reject_threshold")
    op.drop_column("positions", "auto_advance_threshold")
