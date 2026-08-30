"""Add Booking Auto Pay fields (Stripe Customer + default PM).

Revision ID: add_booking_auto_pay
Revises: add_inst_admin_overdue_notified
Create Date: 2026-08-29 20:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_booking_auto_pay"
down_revision = "add_inst_admin_overdue_notified"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


_COLUMNS = [
    ("stripe_customer_id", sa.Column("stripe_customer_id", sa.String(length=128), nullable=True)),
    ("auto_pay_opt_in", sa.Column("auto_pay_opt_in", sa.Boolean(), nullable=True)),
    ("auto_pay_enabled", sa.Column("auto_pay_enabled", sa.Boolean(), nullable=True)),
    ("auto_pay_payment_method_id", sa.Column("auto_pay_payment_method_id", sa.String(length=128), nullable=True)),
    ("auto_pay_enabled_at", sa.Column("auto_pay_enabled_at", sa.DateTime(), nullable=True)),
    ("auto_pay_disabled_at", sa.Column("auto_pay_disabled_at", sa.DateTime(), nullable=True)),
    ("auto_pay_last_charge_at", sa.Column("auto_pay_last_charge_at", sa.DateTime(), nullable=True)),
    ("auto_pay_last_error", sa.Column("auto_pay_last_error", sa.String(length=500), nullable=True)),
]


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "bookings" not in inspector.get_table_names():
        return
    with op.batch_alter_table("bookings") as batch_op:
        for name, col in _COLUMNS:
            if not _column_exists(inspector, "bookings", name):
                batch_op.add_column(col)


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "bookings" not in inspector.get_table_names():
        return
    with op.batch_alter_table("bookings") as batch_op:
        for name, _col in reversed(_COLUMNS):
            if _column_exists(inspector, "bookings", name):
                batch_op.drop_column(name)
