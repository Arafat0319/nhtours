"""Add BookingAddOn manual post-purchase payment fields.

Revision ID: add_booking_addon_manual
Revises: add_booking_auto_pay
Create Date: 2026-08-29 21:30:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_booking_addon_manual"
down_revision = "add_booking_auto_pay"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table = "booking_addons"
    cols = [
        ("source", sa.Column("source", sa.String(length=32), nullable=True)),
        ("payment_status", sa.Column("payment_status", sa.String(length=20), nullable=True)),
        ("payment_id", sa.Column("payment_id", sa.Integer(), nullable=True)),
        (
            "stripe_payment_intent_id",
            sa.Column("stripe_payment_intent_id", sa.String(length=128), nullable=True),
        ),
    ]
    for name, col in cols:
        if not _column_exists(inspector, table, name):
            op.add_column(table, col)

    # Existing rows = selected at booking and already collected with the order
    op.execute(
        sa.text(
            "UPDATE booking_addons SET source = 'booking' "
            "WHERE source IS NULL"
        )
    )
    op.execute(
        sa.text(
            "UPDATE booking_addons SET payment_status = 'paid' "
            "WHERE payment_status IS NULL"
        )
    )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table = "booking_addons"
    for name in ("stripe_payment_intent_id", "payment_id", "payment_status", "source"):
        if _column_exists(inspector, table, name):
            op.drop_column(table, name)
