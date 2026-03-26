"""bulk_import_nullable_position_source_type

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-03-25 10:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make position_id nullable (vivier de talents support)
    op.alter_column(
        "bulk_imports",
        "position_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=True,
    )
    # Add source_type column
    op.add_column(
        "bulk_imports",
        sa.Column("source_type", sa.String(50), nullable=False, server_default="csv"),
    )
    # Add import_metadata column
    op.add_column(
        "bulk_imports",
        sa.Column("import_metadata", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("bulk_imports", "import_metadata")
    op.drop_column("bulk_imports", "source_type")
    op.alter_column(
        "bulk_imports",
        "position_id",
        existing_type=sa.UUID(as_uuid=True),
        nullable=False,
    )
