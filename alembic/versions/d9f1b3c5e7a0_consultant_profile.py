"""consultant_profile

Revision ID: d9f1b3c5e7a0
Revises: c8e0f2a4b6d9
Create Date: 2026-06-18 15:00:00.000000

Dossier de compétence / profil consultant (EPIC J) — profile_json sur ts_consultants.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'd9f1b3c5e7a0'
down_revision: Union[str, None] = 'c8e0f2a4b6d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ts_consultants', sa.Column('profile_json', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('ts_consultants', 'profile_json')
