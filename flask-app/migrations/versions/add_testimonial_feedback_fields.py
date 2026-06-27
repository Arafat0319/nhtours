"""Add feedback fields to testimonials

Revision ID: add_testimonial_feedback_fields
Revises: restore_testimonial_sort_order
Create Date: 2026-06-25 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_testimonial_feedback_fields"
down_revision = "restore_testimonial_sort_order"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("testimonials")]

    if "source" not in columns:
        op.add_column(
            "testimonials",
            sa.Column("source", sa.String(length=20), nullable=False, server_default="homepage"),
        )
        op.create_index(op.f("ix_testimonials_source"), "testimonials", ["source"], unique=False)

    if "email" not in columns:
        op.add_column("testimonials", sa.Column("email", sa.String(length=255), nullable=True))

    if "phone" not in columns:
        op.add_column("testimonials", sa.Column("phone", sa.String(length=50), nullable=True))

    if "rating" not in columns:
        op.add_column("testimonials", sa.Column("rating", sa.String(length=30), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("testimonials")]
    indexes = [i["name"] for i in inspector.get_indexes("testimonials")]

    if "ix_testimonials_source" in indexes:
        op.drop_index(op.f("ix_testimonials_source"), table_name="testimonials")
    if "source" in columns:
        op.drop_column("testimonials", "source")
    if "email" in columns:
        op.drop_column("testimonials", "email")
    if "phone" in columns:
        op.drop_column("testimonials", "phone")
    if "rating" in columns:
        op.drop_column("testimonials", "rating")
