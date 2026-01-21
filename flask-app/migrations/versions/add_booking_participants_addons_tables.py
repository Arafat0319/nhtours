"""add booking participants and addons tables

Revision ID: add_booking_participants_addons_tables
Revises: add_trip_package_columns
Create Date: 2026-01-20 05:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_booking_participants_addons_tables'
down_revision = 'add_trip_package_columns'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'booking_participants' not in tables:
        op.create_table(
            'booking_participants',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('booking_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=128), nullable=True),
            sa.Column('email', sa.String(length=120), nullable=True),
            sa.Column('phone', sa.String(length=20), nullable=True),
            sa.ForeignKeyConstraint(['booking_id'], ['bookings.id']),
            sa.PrimaryKeyConstraint('id'),
        )

    if 'booking_addons' not in tables:
        op.create_table(
            'booking_addons',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('booking_id', sa.Integer(), nullable=False),
            sa.Column('participant_id', sa.Integer(), nullable=True),
            sa.Column('addon_id', sa.Integer(), nullable=False),
            sa.Column('quantity', sa.Integer(), nullable=True),
            sa.Column('price_at_booking', sa.Float(), nullable=True),
            sa.ForeignKeyConstraint(['booking_id'], ['bookings.id']),
            sa.ForeignKeyConstraint(['participant_id'], ['booking_participants.id']),
            sa.ForeignKeyConstraint(['addon_id'], ['trip_addons.id']),
            sa.PrimaryKeyConstraint('id'),
        )


def downgrade():
    op.drop_table('booking_addons')
    op.drop_table('booking_participants')
