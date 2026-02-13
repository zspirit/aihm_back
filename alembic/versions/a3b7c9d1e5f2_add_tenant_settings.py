"""add tenant settings fields

Revision ID: a3b7c9d1e5f2
Revises: c4d5e6f7a8b9
Create Date: 2026-02-13 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a3b7c9d1e5f2"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("logo_url", sa.String(500), nullable=True))
    op.add_column("tenants", sa.Column("website", sa.String(255), nullable=True))
    op.add_column(
        "tenants",
        sa.Column(
            "primary_color", sa.String(7), server_default="#4F46E5", nullable=False
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "timezone", sa.String(50), server_default="Africa/Casablanca", nullable=False
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "data_retention_days", sa.Integer(), server_default="180", nullable=False
        ),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "max_interview_duration", sa.Integer(), server_default="600", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "max_interview_duration")
    op.drop_column("tenants", "data_retention_days")
    op.drop_column("tenants", "timezone")
    op.drop_column("tenants", "primary_color")
    op.drop_column("tenants", "website")
    op.drop_column("tenants", "logo_url")
