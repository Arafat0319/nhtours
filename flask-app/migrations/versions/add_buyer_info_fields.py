"""Add Buyer Info fields and migrate existing data

Revision ID: add_buyer_info_fields
Revises: add_messages_table
Create Date: 2026-01-XX 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = 'add_buyer_info_fields'
down_revision = 'add_messages_table'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    
    # ========== Step 1: 创建 BuyerInfoField 表 ==========
    tables = inspector.get_table_names()
    if 'buyer_info_fields' not in tables:
        op.create_table('buyer_info_fields',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('trip_id', sa.Integer(), nullable=False),
            sa.Column('field_name', sa.String(length=100), nullable=True),
            sa.Column('field_type', sa.String(length=20), nullable=True),
            sa.Column('is_required', sa.Boolean(), default=False),
            sa.Column('display_order', sa.Integer(), default=0),
            sa.Column('options', sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
    
    # ========== Step 2: 扩展 Client 表（添加新字段，允许 NULL）==========
    columns = [col['name'] for col in inspector.get_columns('clients')]
    
    with op.batch_alter_table('clients', schema=None) as batch_op:
        if 'first_name' not in columns:
            batch_op.add_column(sa.Column('first_name', sa.String(length=64), nullable=True))
        if 'last_name' not in columns:
            batch_op.add_column(sa.Column('last_name', sa.String(length=64), nullable=True))
        if 'address' not in columns:
            batch_op.add_column(sa.Column('address', sa.String(length=200), nullable=True))
        if 'city' not in columns:
            batch_op.add_column(sa.Column('city', sa.String(length=100), nullable=True))
        if 'state' not in columns:
            batch_op.add_column(sa.Column('state', sa.String(length=100), nullable=True))
        if 'zip_code' not in columns:
            batch_op.add_column(sa.Column('zip_code', sa.String(length=20), nullable=True))
        if 'country' not in columns:
            batch_op.add_column(sa.Column('country', sa.String(length=100), nullable=True))
    
    # ========== Step 3: 扩展 Booking 表（添加 Buyer Info 字段，允许 NULL）==========
    booking_columns = [col['name'] for col in inspector.get_columns('bookings')]
    
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        # 必填的基础字段
        if 'buyer_first_name' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_first_name', sa.String(length=64), nullable=True))
        if 'buyer_last_name' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_last_name', sa.String(length=64), nullable=True))
        if 'buyer_email' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_email', sa.String(length=120), nullable=True))
        if 'buyer_phone' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_phone', sa.String(length=20), nullable=True))
        
        # 地址信息
        if 'buyer_address' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_address', sa.String(length=200), nullable=True))
        if 'buyer_city' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_city', sa.String(length=100), nullable=True))
        if 'buyer_state' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_state', sa.String(length=100), nullable=True))
        if 'buyer_zip_code' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_zip_code', sa.String(length=20), nullable=True))
        if 'buyer_country' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_country', sa.String(length=100), nullable=True))
        
        # 紧急联系人
        if 'buyer_emergency_contact_name' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_emergency_contact_name', sa.String(length=128), nullable=True))
        if 'buyer_emergency_contact_phone' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_emergency_contact_phone', sa.String(length=20), nullable=True))
        if 'buyer_emergency_contact_email' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_emergency_contact_email', sa.String(length=120), nullable=True))
        if 'buyer_emergency_contact_relationship' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_emergency_contact_relationship', sa.String(length=50), nullable=True))
        
        # 其他联系方式
        if 'buyer_home_phone' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_home_phone', sa.String(length=20), nullable=True))
        if 'buyer_work_phone' not in booking_columns:
            batch_op.add_column(sa.Column('buyer_work_phone', sa.String(length=20), nullable=True))
        
        # 自定义字段答案（JSON）
        if 'buyer_custom_info' not in booking_columns:
            # SQLite 使用 TEXT 类型存储 JSON
            batch_op.add_column(sa.Column('buyer_custom_info', sa.Text(), nullable=True))
    
    # ========== Step 4: 数据迁移（从 Client 复制到 Booking）==========
    # 注意：SQLite 的字符串处理函数有限，使用 Python 逻辑处理
    
    # 4.1 迁移 Client 表的 name 字段拆分
    # 获取所有 clients
    clients_result = conn.execute(text("SELECT id, name FROM clients WHERE name IS NOT NULL AND name != ''"))
    clients_data = clients_result.fetchall()
    
    for client_id, name in clients_data:
        # 简单的名字拆分：第一个空格前是 first_name，后面是 last_name
        name_parts = name.strip().split(' ', 1)
        first_name = name_parts[0] if name_parts else ''
        last_name = name_parts[1] if len(name_parts) > 1 else ''
        
        # 更新 Client 表
        conn.execute(text("""
            UPDATE clients 
            SET first_name = :first_name, last_name = :last_name
            WHERE id = :client_id
        """), {'first_name': first_name, 'last_name': last_name, 'client_id': client_id})
    
    # 4.2 迁移 Booking 表的 Buyer Info（从关联的 Client 复制）
    bookings_result = conn.execute(text("""
        SELECT b.id, b.client_id, c.email, c.phone, c.first_name, c.last_name
        FROM bookings b
        LEFT JOIN clients c ON b.client_id = c.id
        WHERE b.client_id IS NOT NULL
    """))
    bookings_data = bookings_result.fetchall()
    
    for booking_id, client_id, email, phone, first_name, last_name in bookings_data:
        conn.execute(text("""
            UPDATE bookings
            SET buyer_email = :email,
                buyer_phone = :phone,
                buyer_first_name = :first_name,
                buyer_last_name = :last_name
            WHERE id = :booking_id
        """), {
            'email': email or '',
            'phone': phone or '',
            'first_name': first_name or '',
            'last_name': last_name or '',
            'booking_id': booking_id
        })
    
    # ========== Step 5: 验证数据完整性 ==========
    result = conn.execute(text("SELECT COUNT(*) FROM bookings WHERE buyer_email IS NULL AND client_id IS NOT NULL"))
    null_count = result.scalar()
    if null_count > 0:
        print(f"警告：有 {null_count} 条 Booking 记录的 buyer_email 为 NULL")
    
    print("数据迁移完成！")


def downgrade():
    # ========== 回滚：删除新字段和新表 ==========
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    booking_columns = [col['name'] for col in inspector.get_columns('bookings')]
    client_columns = [col['name'] for col in inspector.get_columns('clients')]
    
    # 删除 Booking 表的新字段
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        if 'buyer_custom_info' in booking_columns:
            batch_op.drop_column('buyer_custom_info')
        if 'buyer_work_phone' in booking_columns:
            batch_op.drop_column('buyer_work_phone')
        if 'buyer_home_phone' in booking_columns:
            batch_op.drop_column('buyer_home_phone')
        if 'buyer_emergency_contact_relationship' in booking_columns:
            batch_op.drop_column('buyer_emergency_contact_relationship')
        if 'buyer_emergency_contact_email' in booking_columns:
            batch_op.drop_column('buyer_emergency_contact_email')
        if 'buyer_emergency_contact_phone' in booking_columns:
            batch_op.drop_column('buyer_emergency_contact_phone')
        if 'buyer_emergency_contact_name' in booking_columns:
            batch_op.drop_column('buyer_emergency_contact_name')
        if 'buyer_country' in booking_columns:
            batch_op.drop_column('buyer_country')
        if 'buyer_zip_code' in booking_columns:
            batch_op.drop_column('buyer_zip_code')
        if 'buyer_state' in booking_columns:
            batch_op.drop_column('buyer_state')
        if 'buyer_city' in booking_columns:
            batch_op.drop_column('buyer_city')
        if 'buyer_address' in booking_columns:
            batch_op.drop_column('buyer_address')
        if 'buyer_phone' in booking_columns:
            batch_op.drop_column('buyer_phone')
        if 'buyer_email' in booking_columns:
            batch_op.drop_column('buyer_email')
        if 'buyer_last_name' in booking_columns:
            batch_op.drop_column('buyer_last_name')
        if 'buyer_first_name' in booking_columns:
            batch_op.drop_column('buyer_first_name')
    
    # 删除 Client 表的新字段
    with op.batch_alter_table('clients', schema=None) as batch_op:
        if 'country' in client_columns:
            batch_op.drop_column('country')
        if 'zip_code' in client_columns:
            batch_op.drop_column('zip_code')
        if 'state' in client_columns:
            batch_op.drop_column('state')
        if 'city' in client_columns:
            batch_op.drop_column('city')
        if 'address' in client_columns:
            batch_op.drop_column('address')
        if 'last_name' in client_columns:
            batch_op.drop_column('last_name')
        if 'first_name' in client_columns:
            batch_op.drop_column('first_name')
    
    # 删除 BuyerInfoField 表
    tables = inspector.get_table_names()
    if 'buyer_info_fields' in tables:
        op.drop_table('buyer_info_fields')
