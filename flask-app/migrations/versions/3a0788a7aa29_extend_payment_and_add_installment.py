"""extend_payment_and_add_installment

Revision ID: 3a0788a7aa29
Revises: add_buyer_info_fields
Create Date: 2026-01-07 21:34:17.346046

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import sqlite


# revision identifiers, used by Alembic.
revision = '3a0788a7aa29'
down_revision = 'add_buyer_info_fields'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # 1. 创建 installment_payments 表
    tables = inspector.get_table_names()
    if 'installment_payments' not in tables:
        op.create_table('installment_payments',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('booking_id', sa.Integer(), nullable=False),
            sa.Column('installment_number', sa.Integer(), nullable=True),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('due_date', sa.Date(), nullable=False),
            sa.Column('status', sa.String(length=20), nullable=True),
            sa.Column('payment_intent_id', sa.String(length=128), nullable=True),
            sa.Column('payment_link', sa.String(length=500), nullable=True),
            sa.Column('reminder_sent', sa.Boolean(), nullable=True),
            sa.Column('reminder_sent_at', sa.DateTime(), nullable=True),
            sa.Column('reminder_count', sa.Integer(), nullable=True),
            sa.Column('paid_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['booking_id'], ['bookings.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_installment_payments_payment_intent_id'), 'installment_payments', ['payment_intent_id'], unique=True)
    
    # 2. 扩展 payments 表（使用 batch_alter_table 以支持 SQLite）
    payments_columns = [col['name'] for col in inspector.get_columns('payments')]
    
    with op.batch_alter_table('payments', schema=None) as batch_op:
        # 添加 booking_id（允许 NULL，因为现有记录可能没有关联的 Booking）
        if 'booking_id' not in payments_columns:
            batch_op.add_column(sa.Column('booking_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_payments_booking_id', 'bookings', ['booking_id'], ['id'])
        
        # 添加 Stripe 相关字段
        if 'stripe_payment_intent_id' not in payments_columns:
            batch_op.add_column(sa.Column('stripe_payment_intent_id', sa.String(length=128), nullable=True))
        if 'stripe_checkout_session_id' not in payments_columns:
            batch_op.add_column(sa.Column('stripe_checkout_session_id', sa.String(length=128), nullable=True))
        if 'stripe_customer_id' not in payments_columns:
            batch_op.add_column(sa.Column('stripe_customer_id', sa.String(length=128), nullable=True))
        
        # 添加支付方式字段
        if 'payment_method_type' not in payments_columns:
            batch_op.add_column(sa.Column('payment_method_type', sa.String(length=20), nullable=True))
        if 'payment_method_id' not in payments_columns:
            batch_op.add_column(sa.Column('payment_method_id', sa.String(length=128), nullable=True))
        
        # 添加分期付款关联
        if 'installment_payment_id' not in payments_columns:
            batch_op.add_column(sa.Column('installment_payment_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_payments_installment_payment_id', 'installment_payments', ['installment_payment_id'], ['id'])
        
        # 添加退款相关字段
        if 'refunded_amount' not in payments_columns:
            batch_op.add_column(sa.Column('refunded_amount', sa.Float(), nullable=True))
        if 'refund_reason' not in payments_columns:
            batch_op.add_column(sa.Column('refund_reason', sa.String(length=200), nullable=True))
        
        # 添加时间戳字段
        if 'paid_at' not in payments_columns:
            batch_op.add_column(sa.Column('paid_at', sa.DateTime(), nullable=True))
        if 'refunded_at' not in payments_columns:
            batch_op.add_column(sa.Column('refunded_at', sa.DateTime(), nullable=True))
        
        # 添加元数据字段（注意：不能使用 metadata，这是 SQLAlchemy 保留字段）
        if 'payment_metadata' not in payments_columns:
            batch_op.add_column(sa.Column('payment_metadata', sa.JSON(), nullable=True))
        
        # 添加货币字段
        if 'currency' not in payments_columns:
            batch_op.add_column(sa.Column('currency', sa.String(length=3), nullable=True))
    
    # 创建唯一索引（在 batch_alter_table 外部）
    try:
        op.create_index(op.f('ix_payments_stripe_payment_intent_id'), 'payments', ['stripe_payment_intent_id'], unique=True)
    except:
        pass  # 索引可能已存在
    try:
        op.create_index(op.f('ix_payments_stripe_checkout_session_id'), 'payments', ['stripe_checkout_session_id'], unique=True)
    except:
        pass  # 索引可能已存在
    
    # 3. 数据迁移：将现有 Payment 记录关联到对应的 Booking
    # 根据 client_id 和 trip_id 查找最近的 Booking
    connection = op.get_bind()
    
    # 查找所有没有 booking_id 的 Payment 记录
    payments_without_booking = connection.execute(text("""
        SELECT id, client_id, trip_id 
        FROM payments 
        WHERE booking_id IS NULL
    """)).fetchall()
    
    for payment in payments_without_booking:
        payment_id, client_id, trip_id = payment
        
        # 查找对应的 Booking（选择最近创建的）
        booking = connection.execute(text("""
            SELECT id 
            FROM bookings 
            WHERE client_id = :client_id 
            AND trip_id = :trip_id 
            ORDER BY created_at DESC 
            LIMIT 1
        """), {'client_id': client_id, 'trip_id': trip_id}).fetchone()
        
        if booking:
            booking_id = booking[0]
            # 更新 Payment 的 booking_id
            connection.execute(text("""
                UPDATE payments 
                SET booking_id = :booking_id 
                WHERE id = :payment_id
            """), {'booking_id': booking_id, 'payment_id': payment_id})
    
    # 设置默认货币为 'usd'
    connection.execute(text("""
        UPDATE payments 
        SET currency = 'usd' 
        WHERE currency IS NULL
    """))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # 删除索引
    try:
        op.drop_index(op.f('ix_payments_stripe_checkout_session_id'), table_name='payments')
    except:
        pass
    try:
        op.drop_index(op.f('ix_payments_stripe_payment_intent_id'), table_name='payments')
    except:
        pass
    try:
        op.drop_index(op.f('ix_installment_payments_payment_intent_id'), table_name='installment_payments')
    except:
        pass
    
    # 删除 payments 表的新字段（使用 batch_alter_table 以支持 SQLite）
    payments_columns = [col['name'] for col in inspector.get_columns('payments')]
    
    with op.batch_alter_table('payments', schema=None) as batch_op:
        if 'currency' in payments_columns:
            batch_op.drop_column('currency')
        if 'payment_metadata' in payments_columns:
            batch_op.drop_column('payment_metadata')
        if 'refunded_at' in payments_columns:
            batch_op.drop_column('refunded_at')
        if 'paid_at' in payments_columns:
            batch_op.drop_column('paid_at')
        if 'refund_reason' in payments_columns:
            batch_op.drop_column('refund_reason')
        if 'refunded_amount' in payments_columns:
            batch_op.drop_column('refunded_amount')
        if 'installment_payment_id' in payments_columns:
            batch_op.drop_constraint('fk_payments_installment_payment_id', type_='foreignkey')
            batch_op.drop_column('installment_payment_id')
        if 'payment_method_id' in payments_columns:
            batch_op.drop_column('payment_method_id')
        if 'payment_method_type' in payments_columns:
            batch_op.drop_column('payment_method_type')
        if 'stripe_customer_id' in payments_columns:
            batch_op.drop_column('stripe_customer_id')
        if 'stripe_checkout_session_id' in payments_columns:
            batch_op.drop_column('stripe_checkout_session_id')
        if 'stripe_payment_intent_id' in payments_columns:
            batch_op.drop_column('stripe_payment_intent_id')
        if 'booking_id' in payments_columns:
            batch_op.drop_constraint('fk_payments_booking_id', type_='foreignkey')
            batch_op.drop_column('booking_id')
    
    # 删除 installment_payments 表
    tables = inspector.get_table_names()
    if 'installment_payments' in tables:
        op.drop_table('installment_payments')
