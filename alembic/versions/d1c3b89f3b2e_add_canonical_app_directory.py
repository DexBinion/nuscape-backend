"""Add canonical app directory tables and app_id references

Revision ID: d1c3b89f3b2e
Revises: 6419baa08b6c
Create Date: 2025-09-19 02:05:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = 'd1c3b89f3b2e'
down_revision = '6419baa08b6c'
branch_labels = None
depends_on = None


def _ensure_column(table_name: str, column: sa.Column):
    """Add a column only if it does not already exist."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col['name'] for col in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def upgrade() -> None:
    # Apps directory table
    op.create_table(
        'apps',
        sa.Column('app_id', sa.String(length=128), primary_key=True),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=64), nullable=True),
        sa.Column('icon_url', sa.Text(), nullable=True),
        sa.Column('icon_b64', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )

    # Alias table for namespace-specific identifiers
    op.create_table(
        'app_aliases',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('app_id', sa.String(length=128), nullable=False),
        sa.Column('namespace', sa.String(length=50), nullable=False),
        sa.Column('ident', sa.String(length=255), nullable=False),
        sa.Column('match_kind', sa.String(length=32), nullable=False, server_default='equals'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['app_id'], ['apps.app_id'], ondelete='CASCADE'),
        sa.UniqueConstraint('namespace', 'ident', name='uq_app_alias_namespace_ident'),
    )
    op.create_index('ix_app_aliases_app_id', 'app_aliases', ['app_id'])
    op.create_index('ix_app_aliases_namespace', 'app_aliases', ['namespace'])

    # usage_logs columns
    _ensure_column('usage_logs', sa.Column('app_id', sa.String(length=128), nullable=True))
    _ensure_column('usage_logs', sa.Column('app_package', sa.String(length=255), nullable=True))
    _ensure_column('usage_logs', sa.Column('app_label', sa.String(length=255), nullable=True))
    _ensure_column('usage_logs', sa.Column('alias_namespace', sa.String(length=50), nullable=True))
    _ensure_column('usage_logs', sa.Column('alias_ident', sa.String(length=255), nullable=True))
    op.create_index('ix_usage_logs_app_id', 'usage_logs', ['app_id'])
    op.create_index('ix_usage_logs_app_package', 'usage_logs', ['app_package'])
    op.create_index('ix_usage_logs_alias_namespace', 'usage_logs', ['alias_namespace'])
    op.create_index('ix_usage_logs_alias_ident', 'usage_logs', ['alias_ident'])
    op.create_foreign_key('fk_usage_logs_app_id', 'usage_logs', 'apps', ['app_id'], ['app_id'], ondelete='SET NULL')

    # usage_events columns
    _ensure_column('usage_events', sa.Column('app_id', sa.String(length=128), nullable=True))
    _ensure_column('usage_events', sa.Column('alias_namespace', sa.String(length=50), nullable=True))
    _ensure_column('usage_events', sa.Column('alias_ident', sa.String(length=255), nullable=True))
    op.create_index('ix_usage_events_app_id', 'usage_events', ['app_id'])
    op.create_index('ix_usage_events_alias_namespace', 'usage_events', ['alias_namespace'])
    op.create_index('ix_usage_events_alias_ident', 'usage_events', ['alias_ident'])
    op.create_foreign_key('fk_usage_events_app_id', 'usage_events', 'apps', ['app_id'], ['app_id'], ondelete='SET NULL')

    # hourly_aggregates columns
    _ensure_column('hourly_aggregates', sa.Column('app_id', sa.String(length=128), nullable=True))
    op.create_index('ix_hourly_aggregates_app_id', 'hourly_aggregates', ['app_id'])
    op.create_foreign_key('fk_hourly_aggregates_app_id', 'hourly_aggregates', 'apps', ['app_id'], ['app_id'], ondelete='SET NULL')

    # policy_violations columns
    _ensure_column('policy_violations', sa.Column('app_id', sa.String(length=128), nullable=True))
    op.create_index('ix_policy_violations_app_id', 'policy_violations', ['app_id'])
    op.create_foreign_key('fk_policy_violations_app_id', 'policy_violations', 'apps', ['app_id'], ['app_id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_policy_violations_app_id', 'policy_violations', type_='foreignkey')
    op.drop_index('ix_policy_violations_app_id', table_name='policy_violations')
    op.drop_column('policy_violations', 'app_id')

    op.drop_constraint('fk_hourly_aggregates_app_id', 'hourly_aggregates', type_='foreignkey')
    op.drop_index('ix_hourly_aggregates_app_id', table_name='hourly_aggregates')
    op.drop_column('hourly_aggregates', 'app_id')

    op.drop_constraint('fk_usage_events_app_id', 'usage_events', type_='foreignkey')
    op.drop_index('ix_usage_events_alias_ident', table_name='usage_events')
    op.drop_index('ix_usage_events_alias_namespace', table_name='usage_events')
    op.drop_index('ix_usage_events_app_id', table_name='usage_events')
    op.drop_column('usage_events', 'alias_ident')
    op.drop_column('usage_events', 'alias_namespace')
    op.drop_column('usage_events', 'app_id')

    op.drop_constraint('fk_usage_logs_app_id', 'usage_logs', type_='foreignkey')
    op.drop_index('ix_usage_logs_alias_ident', table_name='usage_logs')
    op.drop_index('ix_usage_logs_alias_namespace', table_name='usage_logs')
    op.drop_index('ix_usage_logs_app_package', table_name='usage_logs')
    op.drop_index('ix_usage_logs_app_id', table_name='usage_logs')
    op.drop_column('usage_logs', 'alias_ident')
    op.drop_column('usage_logs', 'alias_namespace')
    op.drop_column('usage_logs', 'app_label')
    op.drop_column('usage_logs', 'app_package')
    op.drop_column('usage_logs', 'app_id')

    op.drop_index('ix_app_aliases_namespace', table_name='app_aliases')
    op.drop_index('ix_app_aliases_app_id', table_name='app_aliases')
    op.drop_table('app_aliases')

    op.drop_table('apps')
