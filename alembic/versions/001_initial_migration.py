"""Initial migration for devices and usage_logs tables

Revision ID: 001
Revises: 
Create Date: 2025-08-29 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create devices table
    op.create_table('devices',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('platform', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('device_key', sa.String(length=255), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_key')
    )
    op.create_index(op.f('ix_devices_device_key'), 'devices', ['device_key'], unique=False)

    # Create usage_logs table
    op.create_table('usage_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('app_name', sa.String(length=255), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=True),
        sa.Column('start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('duration', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_usage_logs_device_id'), 'usage_logs', ['device_id'], unique=False)
    op.create_index(op.f('ix_usage_logs_start'), 'usage_logs', ['start'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_usage_logs_start'), table_name='usage_logs')
    op.drop_index(op.f('ix_usage_logs_device_id'), table_name='usage_logs')
    op.drop_table('usage_logs')
    op.drop_index(op.f('ix_devices_device_key'), table_name='devices')
    op.drop_table('devices')
