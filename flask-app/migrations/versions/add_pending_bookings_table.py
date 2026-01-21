"""add pending_bookings table

Revision ID: add_pending_bookings
Revises: 
Create Date: 2026-01-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = 'add_pending_bookings'
down_revision = 'add_messages_table'  # 基于最新的迁移
branch_labels = None
depends_on = None


def upgrade():
    # 创建 pending_bookings 表
    op.create_table(
        'pending_bookings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trip_id', sa.Integer(), nullable=False),
        sa.Column('payment_intent_id', sa.String(length=128), nullable=False),
        sa.Column('booking_data', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('payment_intent_id')
    )
    op.create_index(op.f('ix_pending_bookings_payment_intent_id'), 'pending_bookings', ['payment_intent_id'], unique=True)


def downgrade():
    op.drop_index(op.f('ix_pending_bookings_payment_intent_id'), table_name='pending_bookings')
    op.drop_table('pending_bookings')
