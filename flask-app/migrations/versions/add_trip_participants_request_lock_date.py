"""add trip participants request lock date

Revision ID: add_trip_participants_request_lock_date
Revises: extend_user_password_hash
Create Date: 2026-01-19 20:34:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_trip_participants_request_lock_date'
down_revision = 'extend_user_password_hash'
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'trips' not in inspector.get_table_names():
        return
    if not _column_exists(inspector, 'trips', 'participants_request_lock_date'):
        op.add_column(
            'trips',
            sa.Column('participants_request_lock_date', sa.DateTime(), nullable=True)
        )


def downgrade():
    op.drop_column('trips', 'participants_request_lock_date')
