"""add payment fee fields

Revision ID: add_payment_fee_fields
Revises: add_messages_table
Create Date: 2026-01-17 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'add_payment_fee_fields'
down_revision = 'add_messages_table'
branch_labels = None
depends_on = None


def _column_exists(inspector, table_name, column_name):
    columns = [col["name"] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'payments' not in inspector.get_table_names():
        return

    columns_to_add = [
        ('funding', sa.String(length=20)),
        ('brand', sa.String(length=32)),
        ('base_amount_cents', sa.Integer()),
        ('fee_cents', sa.Integer()),
        ('tax_amount_cents', sa.Integer()),
        ('final_amount_cents', sa.Integer()),
    ]
    for column_name, column_type in columns_to_add:
        if not _column_exists(inspector, 'payments', column_name):
            op.add_column('payments', sa.Column(column_name, column_type, nullable=True))


def downgrade():
    columns = [
        'funding',
        'brand',
        'base_amount_cents',
        'fee_cents',
        'tax_amount_cents',
        'final_amount_cents',
    ]
    for column_name in columns:
        op.drop_column('payments', column_name)
