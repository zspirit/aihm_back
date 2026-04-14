"""add scorecards table

Revision ID: a2c3d4e5f6g7
Revises: e9b7c6eac402
Create Date: 2026-04-10 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a2c3d4e5f6g7"
down_revision = "e9b7c6eac402"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scorecards",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("interview_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("interviews.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("evaluator_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("technical", sa.Integer(), nullable=False),
        sa.Column("problem_solving", sa.Integer(), nullable=False),
        sa.Column("communication", sa.Integer(), nullable=False),
        sa.Column("behavioral", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("interview_id", "evaluator_id", name="uq_scorecard_interview_evaluator"),
    )
    op.create_index("ix_scorecards_interview_id", "scorecards", ["interview_id"])
    op.create_index("ix_scorecards_evaluator_id", "scorecards", ["evaluator_id"])


def downgrade() -> None:
    op.drop_index("ix_scorecards_evaluator_id", table_name="scorecards")
    op.drop_index("ix_scorecards_interview_id", table_name="scorecards")
    op.drop_table("scorecards")
