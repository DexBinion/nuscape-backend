"""Create app_aliases_package table for package->label/icon mapping

Revision ID: f1a2b3c4
Revises: e9f8d7c6b5a4
Create Date: 2025-09-24 21:42:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f1a2b3c4"
down_revision = "e9f8d7c6b5a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_aliases_package",
        sa.Column("package_name", sa.Text(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("version_name", sa.Text(), nullable=True),
        sa.Column("version_code", sa.BigInteger(), nullable=True),
        sa.Column("icon_hash", sa.Text(), nullable=True),
        sa.Column("icon_png", sa.LargeBinary(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_app_aliases_package_label", "app_aliases_package", ["label"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_app_aliases_package_label", table_name="app_aliases_package")
    op.drop_table("app_aliases_package")