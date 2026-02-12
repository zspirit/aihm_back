"""add row level security policies

Revision ID: b2f4e8a1c3d5
Revises: 96aab1dc0bfa
Create Date: 2026-02-12
"""
from alembic import op

revision = "b2f4e8a1c3d5"
down_revision = "96aab1dc0bfa"
branch_labels = None
depends_on = None

# Tables with tenant_id that need RLS
RLS_TABLES = ["users", "positions", "candidates", "interviews", "audit_logs"]


def upgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"""CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"""
        )
        op.execute(
            f"""CREATE POLICY tenant_insert_{table} ON {table}
            FOR INSERT WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid)"""
        )

    # Create application role (subject to RLS)
    op.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'aihm_app') THEN CREATE ROLE aihm_app LOGIN; END IF; END $$")
    for table in RLS_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO aihm_app")
    # Grant on non-RLS tables too
    for table in ["tenants", "consents", "transcriptions", "analyses", "reports"]:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO aihm_app")


def downgrade() -> None:
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation_{table} ON {table}")
        op.execute(f"DROP POLICY IF EXISTS tenant_insert_{table} ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
