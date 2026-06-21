"""timesheet_reopen

Revision ID: c8e0f2a4b6d9
Revises: b7d9f1a3c5e8
Create Date: 2026-06-18 14:00:00.000000

Demande de réouverction d'un CRA déjà traité (KAI-E6).
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'c8e0f2a4b6d9'
down_revision: Union[str, None] = 'b7d9f1a3c5e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ts_timesheets', sa.Column('reopen_requested', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('ts_timesheets', sa.Column('reopen_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('ts_timesheets', 'reopen_reason')
    op.drop_column('ts_timesheets', 'reopen_requested')
