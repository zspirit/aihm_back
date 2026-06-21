"""consultant_user_link

Revision ID: e4f6b8d0c2a5
Revises: d3e5a7c9b1f4
Create Date: 2026-06-17 17:00:00.000000

Lien consultant ↔ user (compte de connexion) pour l'espace consultant
self-service (profil, contrats, saisie de son timesheet). Phase C.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'e4f6b8d0c2a5'
down_revision: Union[str, None] = 'd3e5a7c9b1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ts_consultants', sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key('fk_ts_consultants_user', 'ts_consultants', 'users', ['user_id'], ['id'])
    op.create_index('ix_ts_consultants_user_id', 'ts_consultants', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_ts_consultants_user_id', table_name='ts_consultants')
    op.drop_constraint('fk_ts_consultants_user', 'ts_consultants', type_='foreignkey')
    op.drop_column('ts_consultants', 'user_id')
