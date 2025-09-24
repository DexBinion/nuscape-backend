"""Add unique index to usage_logs to deduplicate session inserts

Revision ID: e9f8d7c6b5a4
Revises: d1c3b89f3b2e
Create Date: 2025-09-24 20:54:13.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "e9f8d7c6b5a4"
down_revision = "d1c3b89f3b2e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create a unique index to prevent double-counting identical sessions.
    # Use IF NOT EXISTS for safety on Postgres/Neon.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_usage_session
        ON usage_logs (device_id, app_package, start, "end");
        """
    )


def downgrade() -> None:
    # Drop the unique index if present.
    op.execute(
        """
        DROP INDEX IF EXISTS uq_usage_session;
        """
    )