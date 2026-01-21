"""add trip_cities table

Revision ID: add_trip_cities_table
Revises: add_booking_participants_addons_tables
Create Date: 2026-01-20 05:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_trip_cities_table'
down_revision = 'add_booking_participants_addons_tables'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'trip_cities' not in tables:
        op.create_table(
            'trip_cities',
            sa.Column('trip_id', sa.Integer(), nullable=False),
            sa.Column('city_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(['trip_id'], ['trips.id']),
            sa.ForeignKeyConstraint(['city_id'], ['cities.id']),
            sa.PrimaryKeyConstraint('trip_id', 'city_id'),
        )


def downgrade():
    op.drop_table('trip_cities')
