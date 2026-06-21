"""kairos_documents

Revision ID: d3e5a7c9b1f4
Revises: c2d4f6a8b0e1
Create Date: 2026-06-17 16:00:00.000000

Documents attachés (PDF/DOCX) aux entités Kairos — contrats, avenants, etc.
Fichier dans MinIO/S3, métadonnée en base. Voir Phase B.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'd3e5a7c9b1f4'
down_revision: Union[str, None] = 'c2d4f6a8b0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ts_documents',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('entity_type', sa.String(20), nullable=False),
        sa.Column('entity_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('doc_type', sa.String(30), nullable=False, server_default='other'),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('file_path', sa.String(500), nullable=False),
        sa.Column('content_type', sa.String(120), nullable=True),
        sa.Column('size', sa.Integer(), nullable=True),
        sa.Column('uploaded_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id']),
    )
    op.create_index('ix_ts_documents_entity', 'ts_documents', ['entity_type', 'entity_id'])
    op.create_index('ix_ts_documents_tenant_id', 'ts_documents', ['tenant_id'])


def downgrade() -> None:
    op.drop_index('ix_ts_documents_tenant_id', table_name='ts_documents')
    op.drop_index('ix_ts_documents_entity', table_name='ts_documents')
    op.drop_table('ts_documents')
