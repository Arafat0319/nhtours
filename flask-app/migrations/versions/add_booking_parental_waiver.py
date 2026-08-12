"""Add parental waiver acceptance fields on bookings.

Revision ID: add_booking_parental_waiver
Revises: add_participant_withdrawn_status
Create Date: 2026-08-12 16:50:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_booking_parental_waiver"
down_revision = "add_participant_withdrawn_status"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "bookings" not in inspector.get_table_names():
        return
    with op.batch_alter_table("bookings") as batch_op:
        if not _column_exists(inspector, "bookings", "parental_waiver_accepted_at"):
            batch_op.add_column(sa.Column("parental_waiver_accepted_at", sa.DateTime(), nullable=True))
        if not _column_exists(inspector, "bookings", "parental_waiver_version"):
            batch_op.add_column(sa.Column("parental_waiver_version", sa.String(length=64), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "bookings" not in inspector.get_table_names():
        return
    with op.batch_alter_table("bookings") as batch_op:
        if _column_exists(inspector, "bookings", "parental_waiver_version"):
            batch_op.drop_column("parental_waiver_version")
        if _column_exists(inspector, "bookings", "parental_waiver_accepted_at"):
            batch_op.drop_column("parental_waiver_accepted_at")
