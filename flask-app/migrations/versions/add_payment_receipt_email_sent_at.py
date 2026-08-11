"""Add payments.receipt_email_sent_at for receipt email idempotency.

Revision ID: add_payment_receipt_email_sent_at
Revises: add_booking_package_unit_price
Create Date: 2026-08-11 02:10:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_payment_receipt_email_sent_at"
down_revision = "add_booking_package_unit_price"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "payments" not in inspector.get_table_names():
        return
    if not _column_exists(inspector, "payments", "receipt_email_sent_at"):
        with op.batch_alter_table("payments") as batch_op:
            batch_op.add_column(
                sa.Column("receipt_email_sent_at", sa.DateTime(), nullable=True)
            )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "payments" not in inspector.get_table_names():
        return
    if _column_exists(inspector, "payments", "receipt_email_sent_at"):
        with op.batch_alter_table("payments") as batch_op:
            batch_op.drop_column("receipt_email_sent_at")
