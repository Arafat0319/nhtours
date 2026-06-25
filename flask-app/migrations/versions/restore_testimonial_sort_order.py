"""Restore sort_order for drag-and-drop carousel ordering

Revision ID: restore_testimonial_sort_order
Revises: drop_testimonial_sort_order
Create Date: 2026-06-24 22:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "restore_testimonial_sort_order"
down_revision = "drop_testimonial_sort_order"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("testimonials")]

    if "sort_order" not in columns:
        op.add_column(
            "testimonials",
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        )
        rows = conn.execute(
            sa.text("SELECT id FROM testimonials ORDER BY id ASC")
        ).fetchall()
        for idx, row in enumerate(rows):
            conn.execute(
                sa.text("UPDATE testimonials SET sort_order = :sort_order WHERE id = :id"),
                {"sort_order": idx, "id": row[0]},
            )
        op.create_index(
            op.f("ix_testimonials_sort_order"), "testimonials", ["sort_order"], unique=False
        )


def downgrade():
    op.drop_index(op.f("ix_testimonials_sort_order"), table_name="testimonials")
    op.drop_column("testimonials", "sort_order")
