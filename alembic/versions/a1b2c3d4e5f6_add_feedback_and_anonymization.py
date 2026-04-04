"""add_feedback_and_anonymization

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-04-03 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Feedback candidat
    op.add_column('candidates', sa.Column('feedback_json', JSONB, nullable=True))
    op.add_column('candidates', sa.Column('feedback_sent_at', sa.DateTime(timezone=True), nullable=True))
    # Anonymisation
    op.add_column('candidates', sa.Column('is_anonymized', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    op.drop_column('candidates', 'is_anonymized')
    op.drop_column('candidates', 'feedback_sent_at')
    op.drop_column('candidates', 'feedback_json')
