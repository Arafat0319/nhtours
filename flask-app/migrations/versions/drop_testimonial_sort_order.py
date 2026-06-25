"""Drop sort_order from testimonials

Revision ID: drop_testimonial_sort_order
Revises: add_testimonial_sort_order
Create Date: 2026-06-24 21:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "drop_testimonial_sort_order"
down_revision = "add_testimonial_sort_order"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("testimonials")]
    indexes = [i["name"] for i in inspector.get_indexes("testimonials")]

    if "ix_testimonials_sort_order" in indexes:
        op.drop_index(op.f("ix_testimonials_sort_order"), table_name="testimonials")
    if "sort_order" in columns:
        op.drop_column("testimonials", "sort_order")


def downgrade():
    op.add_column(
        "testimonials",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(op.f("ix_testimonials_sort_order"), "testimonials", ["sort_order"], unique=False)
