"""extend user password hash length

Revision ID: extend_user_password_hash
Revises: merge_payment_heads
Create Date: 2026-01-19 20:28:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'extend_user_password_hash'
down_revision = 'merge_payment_heads'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'users',
        'password_hash',
        existing_type=sa.String(length=128),
        type_=sa.String(length=255),
        existing_nullable=True
    )


def downgrade():
    op.alter_column(
        'users',
        'password_hash',
        existing_type=sa.String(length=255),
        type_=sa.String(length=128),
        existing_nullable=True
    )
