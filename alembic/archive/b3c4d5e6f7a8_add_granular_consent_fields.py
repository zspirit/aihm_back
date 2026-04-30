"""Add granular consent fields (expires_at, revoked_at) and merge heads

Revision ID: b3c4d5e6f7a8
Revises: df94ff1eb5d1, a1b2c3d4e6f7
Create Date: 2026-04-10 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str]] = ('df94ff1eb5d1', 'a2c3d4e5f6g7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('consents', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('consents', sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('consents', 'revoked_at')
    op.drop_column('consents', 'expires_at')
