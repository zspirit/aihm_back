"""add_summary_json

Revision ID: df94ff1eb5d1
Revises: a1b2c3d4e5f6
Create Date: 2026-04-04 08:54:32.250609
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'df94ff1eb5d1'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('candidates', sa.Column('summary_json', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('candidates', 'summary_json')
