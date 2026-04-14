"""merge_heads

Revision ID: 8e237fedbbd9
Revises: a1b2c3d4e6f7, b3c4d5e6f7a8
Create Date: 2026-04-13 16:18:00.786441
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '8e237fedbbd9'
down_revision: Union[str, None] = ('a1b2c3d4e6f7', 'b3c4d5e6f7a8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
