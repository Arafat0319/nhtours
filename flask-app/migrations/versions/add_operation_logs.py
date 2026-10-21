"""Customer-sensitive operation log (emails, blocked notices, job runs).

Revision ID: add_operation_logs
Revises: add_booking_addon_manual
Create Date: 2026-10-20 21:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_operation_logs"
down_revision = "add_booking_addon_manual"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "operation_logs" in inspector.get_table_names():
        return
    op.create_table(
        "operation_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("result", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=True),
        sa.Column("booking_id", sa.Integer(), nullable=True),
        sa.Column("order_number", sa.String(length=64), nullable=True),
        sa.Column("related_id", sa.String(length=64), nullable=True),
        sa.Column("related_type", sa.String(length=40), nullable=True),
        sa.Column("recipient", sa.String(length=190), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("message_id", sa.String(length=128), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
    )
    op.create_index("ix_operation_logs_created_at", "operation_logs", ["created_at"])
    op.create_index("ix_operation_logs_order_number", "operation_logs", ["order_number"])
    op.create_index("ix_operation_logs_action_result", "operation_logs", ["action", "result"])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "operation_logs" not in inspector.get_table_names():
        return
    op.drop_index("ix_operation_logs_action_result", table_name="operation_logs")
    op.drop_index("ix_operation_logs_order_number", table_name="operation_logs")
    op.drop_index("ix_operation_logs_created_at", table_name="operation_logs")
    op.drop_table("operation_logs")
