"""kairos_copilot

Revision ID: a1c3e5f7b9d2
Revises: e0b2d4f6a8c1
Create Date: 2026-06-21 10:00:00.000000

Historique de conversation du copilot consultant (EPIC L) : ts_copilot_messages
(scopé tenant + consultant, role user/assistant, meta = outils/action proposée).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'a1c3e5f7b9d2'
down_revision: Union[str, None] = 'e0b2d4f6a8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ts_copilot_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('consultant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
        sa.ForeignKeyConstraint(['consultant_id'], ['ts_consultants.id']),
    )
    op.create_index('ix_ts_copilot_consultant', 'ts_copilot_messages', ['consultant_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_ts_copilot_consultant', table_name='ts_copilot_messages')
    op.drop_table('ts_copilot_messages')
