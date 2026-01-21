"""add trip package and addon columns

Revision ID: add_trip_package_columns
Revises: add_trip_participants_request_lock_date
Create Date: 2026-01-20 05:25:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_trip_package_columns'
down_revision = 'add_trip_participants_request_lock_date'
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if 'trip_packages' in inspector.get_table_names():
        if not _column_exists(inspector, 'trip_packages', 'booking_deadline'):
            op.add_column('trip_packages', sa.Column('booking_deadline', sa.DateTime(), nullable=True))
        if not _column_exists(inspector, 'trip_packages', 'currency'):
            op.add_column('trip_packages', sa.Column('currency', sa.String(length=3), nullable=True))

    if 'trip_addons' in inspector.get_table_names():
        if not _column_exists(inspector, 'trip_addons', 'description'):
            op.add_column('trip_addons', sa.Column('description', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('trip_addons', 'description')
    op.drop_column('trip_packages', 'currency')
    op.drop_column('trip_packages', 'booking_deadline')
