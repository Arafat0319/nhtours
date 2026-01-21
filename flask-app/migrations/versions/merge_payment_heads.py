"""merge payment heads

Revision ID: merge_payment_heads
Revises: 3a0788a7aa29, add_payment_fee_fields
Create Date: 2026-01-19 19:40:00.000000

"""
from alembic import op


revision = 'merge_payment_heads'
down_revision = ('3a0788a7aa29', 'add_payment_fee_fields')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
