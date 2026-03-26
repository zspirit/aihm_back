"""add_match_scores_sessions

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-03-25 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "match_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("candidate_id", UUID(as_uuid=True), sa.ForeignKey("candidates.id"), nullable=False),
        sa.Column("position_id", UUID(as_uuid=True), sa.ForeignKey("positions.id"), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("reasons", JSONB, nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", "position_id", name="uq_match_candidate_position"),
    )
    op.create_index("ix_match_scores_tenant_id", "match_scores", ["tenant_id"])
    op.create_index("ix_match_scores_position_id", "match_scores", ["position_id"])
    op.create_index("ix_match_scores_candidate_id", "match_scores", ["candidate_id"])
    op.create_index("ix_match_scores_score", "match_scores", ["score"])

    op.create_table(
        "match_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("position_ids", JSONB, nullable=True),
        sa.Column("candidate_ids", JSONB, nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("total_pairs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_pairs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_match_sessions_tenant_id", "match_sessions", ["tenant_id"])
    op.create_index("ix_match_sessions_status", "match_sessions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_match_sessions_status", "match_sessions")
    op.drop_index("ix_match_sessions_tenant_id", "match_sessions")
    op.drop_table("match_sessions")
    op.drop_index("ix_match_scores_score", "match_scores")
    op.drop_index("ix_match_scores_candidate_id", "match_scores")
    op.drop_index("ix_match_scores_position_id", "match_scores")
    op.drop_index("ix_match_scores_tenant_id", "match_scores")
    op.drop_table("match_scores")
