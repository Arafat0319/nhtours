"""Add booking_participants.status + withdrawn_at for soft withdraw.

Revision ID: add_participant_withdrawn_status
Revises: add_payment_receipt_email_sent_at
Create Date: 2026-08-11 03:20:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_participant_withdrawn_status"
down_revision = "add_payment_receipt_email_sent_at"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "booking_participants" not in inspector.get_table_names():
        return
    with op.batch_alter_table("booking_participants") as batch_op:
        if not _column_exists(inspector, "booking_participants", "status"):
            batch_op.add_column(
                sa.Column("status", sa.String(length=20), nullable=False, server_default="active")
            )
        if not _column_exists(inspector, "booking_participants", "withdrawn_at"):
            batch_op.add_column(sa.Column("withdrawn_at", sa.DateTime(), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "booking_participants" not in inspector.get_table_names():
        return
    with op.batch_alter_table("booking_participants") as batch_op:
        if _column_exists(inspector, "booking_participants", "withdrawn_at"):
            batch_op.drop_column("withdrawn_at")
        if _column_exists(inspector, "booking_participants", "status"):
            batch_op.drop_column("status")
