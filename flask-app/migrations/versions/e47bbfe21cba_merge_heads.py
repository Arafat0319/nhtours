"""merge heads

Revision ID: e47bbfe21cba
Revises: add_trip_cities_table, add_pending_bookings
Create Date: 2026-01-20 18:43:43.652798

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e47bbfe21cba'
down_revision = ('add_trip_cities_table', 'add_pending_bookings')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
