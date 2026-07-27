"""Add users.role for admin/staff MVP.

Revision ID: add_user_role
Revises: add_booking_order_numbers
Create Date: 2026-07-27 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_user_role"
down_revision = "add_booking_order_numbers"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("role", sa.String(length=20), nullable=False, server_default="admin")
        )
    # Drop server_default after backfill so app default remains the source of truth
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("role", server_default=None)


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("role")
