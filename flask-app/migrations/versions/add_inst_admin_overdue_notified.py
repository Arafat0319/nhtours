"""Add installment_payments.admin_overdue_notified_at for ≥3-day admin alerts.

Revision ID: add_inst_admin_overdue_notified
Revises: add_booking_parental_waiver
Create Date: 2026-08-29 19:40:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = "add_inst_admin_overdue_notified"
down_revision = "add_booking_parental_waiver"
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "installment_payments" not in inspector.get_table_names():
        return
    with op.batch_alter_table("installment_payments") as batch_op:
        if not _column_exists(inspector, "installment_payments", "admin_overdue_notified_at"):
            batch_op.add_column(sa.Column("admin_overdue_notified_at", sa.DateTime(), nullable=True))

    # 上线存量：已逾期 ≥3 天的期次标记为「已通知」，避免 Deploy 当天刷爆管理员邮箱。
    # 之后只会对「新越过 3 天」且尚未标记的期次发信。
    conn.execute(
        sa.text(
            """
            UPDATE installment_payments
            SET admin_overdue_notified_at = UTC_TIMESTAMP()
            WHERE admin_overdue_notified_at IS NULL
              AND status IN ('pending', 'overdue')
              AND due_date IS NOT NULL
              AND due_date <= (CURRENT_DATE - INTERVAL 3 DAY)
            """
        )
    )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "installment_payments" not in inspector.get_table_names():
        return
    with op.batch_alter_table("installment_payments") as batch_op:
        if _column_exists(inspector, "installment_payments", "admin_overdue_notified_at"):
            batch_op.drop_column("admin_overdue_notified_at")
