"""add modules_config JSONB to tenants"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'c1d2e3f4a5b6'
down_revision = 'b3c4d5e6f7a8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tenants',
        sa.Column('modules_config', postgresql.JSONB(), nullable=True, server_default="'{}'"))


def downgrade():
    op.drop_column('tenants', 'modules_config')
