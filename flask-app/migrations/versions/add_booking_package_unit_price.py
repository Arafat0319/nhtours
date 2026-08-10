"""Add booking_packages.unit_price (price snapshot at booking time).

Revision ID: add_booking_package_unit_price
Revises: add_trip_teacher_view_slug
Create Date: 2026-08-09 20:30:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_booking_package_unit_price"
down_revision = "add_trip_teacher_view_slug"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "booking_packages" not in inspector.get_table_names():
        return
    if not _column_exists(inspector, "booking_packages", "unit_price"):
        with op.batch_alter_table("booking_packages") as batch_op:
            batch_op.add_column(sa.Column("unit_price", sa.Float(), nullable=True))

    # Backfill from current TripPackage.price (best-effort freeze going forward)
    dialect = conn.dialect.name
    if dialect == "mysql":
        conn.execute(
            sa.text(
                """
                UPDATE booking_packages bp
                INNER JOIN trip_packages tp ON bp.package_id = tp.id
                SET bp.unit_price = tp.price
                WHERE bp.unit_price IS NULL AND tp.price IS NOT NULL
                """
            )
        )
    else:
        conn.execute(
            sa.text(
                """
                UPDATE booking_packages
                SET unit_price = (
                    SELECT price FROM trip_packages
                    WHERE trip_packages.id = booking_packages.package_id
                )
                WHERE unit_price IS NULL
                """
            )
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "booking_packages" not in inspector.get_table_names():
        return
    if _column_exists(inspector, "booking_packages", "unit_price"):
        with op.batch_alter_table("booking_packages") as batch_op:
            batch_op.drop_column("unit_price")
