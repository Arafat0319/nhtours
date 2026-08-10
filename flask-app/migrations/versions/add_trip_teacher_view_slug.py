"""Add trips.teacher_view_slug for teacher read-only roster links.

Revision ID: add_trip_teacher_view_slug
Revises: add_user_role
Create Date: 2026-08-09 20:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_trip_teacher_view_slug"
down_revision = "add_user_role"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def _index_exists(inspector, table_name, index_name):
    return any(idx["name"] == index_name for idx in inspector.get_indexes(table_name))


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "trips" not in inspector.get_table_names():
        return
    if not _column_exists(inspector, "trips", "teacher_view_slug"):
        with op.batch_alter_table("trips") as batch_op:
            batch_op.add_column(
                sa.Column("teacher_view_slug", sa.String(length=64), nullable=True)
            )
    inspector = sa.inspect(conn)
    if not _index_exists(inspector, "trips", "ix_trips_teacher_view_slug"):
        with op.batch_alter_table("trips") as batch_op:
            batch_op.create_index(
                "ix_trips_teacher_view_slug", ["teacher_view_slug"], unique=True
            )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "trips" not in inspector.get_table_names():
        return
    if _index_exists(inspector, "trips", "ix_trips_teacher_view_slug"):
        with op.batch_alter_table("trips") as batch_op:
            batch_op.drop_index("ix_trips_teacher_view_slug")
    if _column_exists(inspector, "trips", "teacher_view_slug"):
        with op.batch_alter_table("trips") as batch_op:
            batch_op.drop_column("teacher_view_slug")
