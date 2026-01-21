"""
数据库模型定义
"""

from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, login_manager

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    """管理员用户模型"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, index=True)
    password_hash = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'


class City(db.Model):
    """城市信息模型"""
    __tablename__ = 'cities'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), index=True)
    country = db.Column(db.String(64))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(256))  # 存储图片路径
    
    # 关系: 这里的行程是指该城市包含的行程，或者该城市是行程的一部分
    # 目前简单设计：一个行程主要属于一个区域，但可能包含多个城市描述
    # 暂时不建立强外键关联，仅作为信息管理
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<City {self.name}>'



# 关联表：行程与城市
trip_cities = db.Table('trip_cities',
    db.Column('trip_id', db.Integer, db.ForeignKey('trips.id'), primary_key=True),
    db.Column('city_id', db.Integer, db.ForeignKey('cities.id'), primary_key=True)
)


class Trip(db.Model):
    """行程模型"""
    __tablename__ = 'trips'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(128), index=True)
    slug = db.Column(db.String(128), unique=True, index=True)  # URL 友好的标识符
    price = db.Column(db.Float)
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    is_published = db.Column(db.Boolean, default=False)
    
    # 详情内容
    description = db.Column(db.Text) # 简短描述
    highlight_image = db.Column(db.String(256)) # 亮点图片
    hero_image = db.Column(db.String(256)) # 顶部大图
    
    # 关联
    itinerary_items = db.relationship('ItineraryItem', backref='trip', lazy='dynamic', cascade='all, delete-orphan')
    cities = db.relationship('City', secondary=trip_cities, lazy='subquery',
        backref=db.backref('trips', lazy=True))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # WeTravel 风格字段
    status = db.Column(db.String(20), default='draft') # draft, published, archived
    capacity = db.Column(db.Integer) # 最大名额 (Total Capacity)
    min_capacity = db.Column(db.Integer, default=0) # 最小成团人数
    spots_sold = db.Column(db.Integer, default=0) # 已售名额
    color = db.Column(db.String(20), default='#00D1C1') # Calendar color
    
    # Text Destination (Replciing City ID)
    destination_text = db.Column(db.String(128)) 
    
    # JSON Fields for Lists
    trip_includes = db.Column(db.JSON) # List of {title, description}
    trip_excludes = db.Column(db.JSON) # List of {title, description}
    
    # Relationships
    packages = db.relationship('TripPackage', backref='trip', lazy='dynamic', cascade='all, delete-orphan')
    add_ons = db.relationship('TripAddOn', backref='trip', lazy='dynamic', cascade='all, delete-orphan')
    questions = db.relationship('CustomQuestion', backref='trip', lazy='dynamic', cascade='all, delete-orphan')
    discount_codes = db.relationship('DiscountCode', backref='trip', lazy='dynamic', cascade='all, delete-orphan')

    # Step 5: Participant Info Logic
    participants_request_lock_date = db.Column(db.DateTime) # Info collected at checkout lock date

    @property
    def duration_days(self):
        if self.start_date and self.end_date:
            delta = self.end_date - self.start_date
            return delta.days + 1
        return 0

    def __repr__(self):
        return f'<Trip {self.title}>'

class TripPackage(db.Model):
    """行程套餐 (Pricing Packages)"""
    __tablename__ = 'trip_packages'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    name = db.Column(db.String(128), nullable=False) # e.g. "Standard Room"
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    capacity = db.Column(db.Integer) # Package specific capacity (Optional)
    status = db.Column(db.String(20), default='available') # available, sold_out, unavailable
    
    # Payment Plan Configuration
    # JSON Structure: 
    # {
    #   "deposit": 500,
    #   "installments": [
    #       {"date": "2025-09-03", "amount": 625},
    #       {"date": "2025-10-03", "amount": 625}
    #   ],
    #   "auto_billing": true,
    #   "allow_partial": false
    # }
    payment_plan_config = db.Column(db.JSON)
    
    # New WeTravel Fields
    booking_deadline = db.Column(db.DateTime)
    # Removed min_per_booking and max_per_booking - customers can add any number of packages
    currency = db.Column(db.String(3), default='USD')
    
    def __repr__(self):
        return f'<TripPackage {self.name}>'

class TripAddOn(db.Model):
    """附加选项 (Add-ons)"""
    __tablename__ = 'trip_addons'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    name = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    # Simple add-on, no complex logic requested
    
    def __repr__(self):
        return f'<TripAddOn {self.name}>'

class CustomQuestion(db.Model):
    """报名表单自定义问题"""
    __tablename__ = 'custom_questions'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    label = db.Column(db.String(256), nullable=False) # Question Text
    type = db.Column(db.String(50), nullable=False) # text, choice, file, etc.
    options = db.Column(db.JSON) # For choice types: ["Option A", "Option B"]
    required = db.Column(db.Boolean, default=False)
    
    def __repr__(self):
        return f'<CustomQuestion {self.label}>'

class BuyerInfoField(db.Model):
    """购买者信息字段配置模型（类似 CustomQuestion，但用于 Buyer Info）"""
    __tablename__ = 'buyer_info_fields'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    field_name = db.Column(db.String(100), nullable=False)  # 字段名称（如 "Address", "Emergency Contact"）
    field_type = db.Column(db.String(20), nullable=False)  # 'text', 'email', 'phone', 'address', 'date', 'select', 'textarea'
    is_required = db.Column(db.Boolean, default=False)  # 是否必填
    display_order = db.Column(db.Integer, default=0)  # 显示顺序
    options = db.Column(db.JSON)  # 对于 select 类型，存储选项（如 ["Option 1", "Option 2"]）
    
    # 关联
    trip = db.relationship('Trip', backref=db.backref('buyer_info_fields', lazy='dynamic', cascade='all, delete-orphan'))
    
    def __repr__(self):
        return f'<BuyerInfoField {self.field_name} (Trip {self.trip_id})>'

class DiscountCode(db.Model):
    """优惠码"""
    __tablename__ = 'discount_codes'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=True) # If null, Global code? User said "Global and Trip Specific"
    code = db.Column(db.String(64), unique=True, index=True, nullable=False)
    type = db.Column(db.String(20), default='fixed') # fixed ($) or percent (%)
    amount = db.Column(db.Float, nullable=False)
    used_count = db.Column(db.Integer, default=0)  # 使用次数
    
    # 注意：trip 关系已在 Trip 模型中通过 backref='trip' 定义
    
    def calculate_discount(self, order_amount):
        """计算折扣金额"""
        if self.type == 'fixed':
            return min(self.amount, order_amount)  # 折扣不超过订单金额
        elif self.type == 'percent':
            return round(order_amount * (self.amount / 100), 2)
        return 0.0
    
    def __repr__(self):
        return f'<DiscountCode {self.code}>'


# Legacy ItineraryItem (Kept for safe migration, but feature removed in UI)
class ItineraryItem(db.Model):
    """行程单项（具体某一天的安排）"""
    __tablename__ = 'itinerary_items'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'))
    day_number = db.Column(db.Integer) # 第几天
    title = db.Column(db.String(128))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(256))
    accommodation = db.Column(db.String(128)) # 住宿信息
    meals = db.Column(db.String(64)) # 当日餐饮 (e.g. "B/L/D")
    
    def __repr__(self):
        return f'<ItineraryItem Day {self.day_number} of Trip {self.trip_id}>'


class Client(db.Model):
    """客户模型"""
    __tablename__ = 'clients'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), index=True)  # 保留用于兼容性
    email = db.Column(db.String(120), index=True)
    phone = db.Column(db.String(20))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 新增字段（用于默认值，不是强制要求）
    first_name = db.Column(db.String(64))
    last_name = db.Column(db.String(64))
    address = db.Column(db.String(200))
    city = db.Column(db.String(100))
    state = db.Column(db.String(100))
    zip_code = db.Column(db.String(20))
    country = db.Column(db.String(100))
    
    # 简单的订单关联（反向关系由 Payment.client 定义）
    payments = db.relationship('Payment', lazy='dynamic', cascade='all, delete-orphan')
    
    @property
    def full_name(self):
        """返回完整姓名"""
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.name:
            return self.name
        return ""
    
    def __repr__(self):
        return f'<Client {self.name or self.full_name}>'


class Payment(db.Model):
    """支付记录模型 - 重构版：支持 Booking 关联和分期付款"""
    __tablename__ = 'payments'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # 关联关系（重要：必须关联 Booking）
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=True)  # 新增：关联 Booking
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'), nullable=True)  # 保留（向后兼容）
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=True)  # 保留（向后兼容）
    
    # 支付信息
    amount = db.Column(db.Float, nullable=False)  # 支付金额
    currency = db.Column(db.String(3), default='usd')  # 货币类型
    
    # Stripe 相关字段
    stripe_payment_intent_id = db.Column(db.String(128), unique=True)  # Payment Intent ID（新增）
    stripe_checkout_session_id = db.Column(db.String(128), unique=True)  # Checkout Session ID（新增）
    stripe_charge_id = db.Column(db.String(64), unique=True)  # Charge ID（保留）
    stripe_customer_id = db.Column(db.String(128))  # Customer ID（新增）
    
    # 支付方式
    payment_method_type = db.Column(db.String(20))  # 'card', 'bank_transfer', etc.
    payment_method_id = db.Column(db.String(128))  # Stripe Payment Method ID
    funding = db.Column(db.String(20))  # card funding: debit/credit/prepaid/unknown
    brand = db.Column(db.String(32))  # card brand: visa/mastercard/amex/unknown

    # 金额明细（最小货币单位）
    base_amount_cents = db.Column(db.Integer)
    fee_cents = db.Column(db.Integer)
    tax_amount_cents = db.Column(db.Integer)
    final_amount_cents = db.Column(db.Integer)
    
    # 状态
    status = db.Column(db.String(20), default='pending')  # 'pending', 'succeeded', 'failed', 'refunded', 'partially_refunded'
    
    # 分期付款关联（如果是分期付款）
    installment_payment_id = db.Column(db.Integer, db.ForeignKey('installment_payments.id'), nullable=True)  # 新增
    
    # 退款信息
    refunded_amount = db.Column(db.Float, default=0.0)  # 已退款金额
    refund_reason = db.Column(db.String(200))  # 退款原因
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime)  # 支付完成时间
    refunded_at = db.Column(db.DateTime)  # 退款时间
    
    # 元数据（JSON 格式，存储额外信息）
    payment_metadata = db.Column(db.JSON)  # 存储 Stripe metadata 等（注意：不能使用 metadata，这是 SQLAlchemy 保留字段）
    
    # 关联关系
    booking = db.relationship('Booking', backref=db.backref('payments', lazy='dynamic'))  # 新增
    client = db.relationship('Client')  # 反向关系由 Client.payments 定义
    trip = db.relationship('Trip', backref=db.backref('payments', lazy='dynamic'))
    installment_payment = db.relationship('InstallmentPayment', backref=db.backref('payments', lazy='dynamic'))

    def __repr__(self):
        return f'<Payment {self.id} - {self.status} - Booking {self.booking_id}>'


class Lead(db.Model):
    """潜在客户/线索模型 (来自 Contact 表单)"""
    __tablename__ = 'leads'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128)) # First + Last Name
    email = db.Column(db.String(120), index=True)
    phone = db.Column(db.String(20))
    organization = db.Column(db.String(200))
    interest = db.Column(db.Text) # JSON or Comma-separated string
    message = db.Column(db.Text)
    status = db.Column(db.String(20), default='new') # new, replied, archived, converted
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Lead {self.email}>'


class Booking(db.Model):
    """预订模型"""
    __tablename__ = 'bookings'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'))
    client_id = db.Column(db.Integer, db.ForeignKey('clients.id'))
    
    status = db.Column(db.String(20), default='pending') # pending, deposit_paid, fully_paid, cancelled
    passenger_count = db.Column(db.Integer, default=1)  # Total participants (calculated from BookingPackage quantities)
    amount_paid = db.Column(db.Float, default=0.0)  # Total amount paid (sum of all BookingPackage amounts)
    special_requests = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    today = datetime.utcnow()
    
    # Buyer Info 字段（必填的基础字段）
    buyer_first_name = db.Column(db.String(64))
    buyer_last_name = db.Column(db.String(64))
    buyer_email = db.Column(db.String(120))
    buyer_phone = db.Column(db.String(20))
    
    # 地址信息
    buyer_address = db.Column(db.String(200))
    buyer_city = db.Column(db.String(100))
    buyer_state = db.Column(db.String(100))
    buyer_zip_code = db.Column(db.String(20))
    buyer_country = db.Column(db.String(100))
    
    # 紧急联系人
    buyer_emergency_contact_name = db.Column(db.String(128))
    buyer_emergency_contact_phone = db.Column(db.String(20))
    buyer_emergency_contact_email = db.Column(db.String(120))
    buyer_emergency_contact_relationship = db.Column(db.String(50))
    
    # 其他联系方式
    buyer_home_phone = db.Column(db.String(20))
    buyer_work_phone = db.Column(db.String(20))
    
    # 自定义字段答案（JSON 格式）
    # 格式：{"field_id_1": "answer1", "field_id_2": "answer2"}
    buyer_custom_info = db.Column(db.JSON)
    
    # 折扣码相关字段
    discount_code_id = db.Column(db.Integer, db.ForeignKey('discount_codes.id'), nullable=True)
    discount_amount = db.Column(db.Float, default=0.0)  # 实际折扣金额
    
    # 关联
    trip = db.relationship('Trip', backref=db.backref('bookings', lazy='dynamic'))
    client = db.relationship('Client', backref=db.backref('bookings', lazy='dynamic'))
    discount_code = db.relationship('DiscountCode', backref=db.backref('bookings', lazy='dynamic'))
    # Removed package_id - now using BookingPackage for many-to-many relationship

    @property
    def buyer_name(self):
        """兼容属性：返回完整的购买者姓名"""
        if self.buyer_first_name and self.buyer_last_name:
            return f"{self.buyer_first_name} {self.buyer_last_name}"
        elif self.buyer_first_name:
            return self.buyer_first_name
        elif self.client:  # 向后兼容：如果没有 buyer 信息，从 client 获取
            return self.client.name or self.client.full_name
        return ""
    
    def get_buyer_email(self):
        """兼容方法：优先返回 buyer_email，否则返回 client.email"""
        return self.buyer_email or (self.client.email if self.client else None)
    
    def get_buyer_phone(self):
        """兼容方法：优先返回 buyer_phone，否则返回 client.phone"""
        return self.buyer_phone or (self.client.phone if self.client else None)

    def __repr__(self):
        return f'<Booking {self.id} - {self.status}>'

class BookingParticipant(db.Model):
    """预订参与者模型 (Per-person details)"""
    __tablename__ = 'booking_participants'
    
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=False)
    name = db.Column(db.String(128))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    
    # In case we want to override package per person, or just track it
    # For now, let's assume it inherits from Booking but good to have link if needed later
    # package_id = db.Column(db.Integer, db.ForeignKey('trip_packages.id'), nullable=True) 
    
    # Add-ons selected by this participant
    addons = db.relationship('BookingAddOn', backref='participant', lazy='dynamic')
    
    booking = db.relationship('Booking', backref=db.backref('participants', lazy='dynamic'))

class BookingPackage(db.Model):
    """预订套餐关联模型 (Linking Booking to Package with quantity and payment plan)"""
    __tablename__ = 'booking_packages'
    
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=False)
    package_id = db.Column(db.Integer, db.ForeignKey('trip_packages.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)  # Number of this package in the booking
    payment_plan_type = db.Column(db.String(20), default='full')  # 'full' or 'deposit_installment'
    amount_paid = db.Column(db.Float, default=0.0)  # Amount paid for this specific package
    status = db.Column(db.String(20), default='pending')  # 'pending', 'deposit_paid', 'fully_paid'
    
    booking = db.relationship('Booking', backref=db.backref('booking_packages', lazy='dynamic', cascade='all, delete-orphan'))
    package = db.relationship('TripPackage', backref='booking_packages')
    
    def __repr__(self):
        return f'<BookingPackage {self.id} - Qty: {self.quantity}>'

class BookingAddOn(db.Model):
    """预订附加项关联模型 (Linking Participant/Booking to AddOn)"""
    __tablename__ = 'booking_addons'
    
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=False) # Link to main booking
    participant_id = db.Column(db.Integer, db.ForeignKey('booking_participants.id'), nullable=True) # Optional link to specific person
    addon_id = db.Column(db.Integer, db.ForeignKey('trip_addons.id'), nullable=False)
    
    quantity = db.Column(db.Integer, default=1)
    price_at_booking = db.Column(db.Float) # Price snapshot
    
    addon = db.relationship('TripAddOn')
    # booking relationship is already defined implicitly via booking.addons if we added it, 
    # but let's just use query or backref from here if needed.
    booking = db.relationship('Booking', backref=db.backref('addons', lazy='dynamic'))


class PendingBooking(db.Model):
    """待支付报名数据临时存储模型（支付成功前存储完整报名数据）"""
    __tablename__ = 'pending_bookings'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    payment_intent_id = db.Column(db.String(128), unique=True, nullable=False)  # Stripe Payment Intent ID
    
    # 完整的报名数据（JSON格式）
    booking_data = db.Column(db.JSON, nullable=False)
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime)  # 可选：设置过期时间（例如24小时后自动清理）
    
    # 状态
    status = db.Column(db.String(20), default='pending')  # 'pending', 'completed', 'expired', 'cancelled'
    
    # 关联
    trip = db.relationship('Trip', backref=db.backref('pending_bookings', lazy='dynamic'))
    
    def __repr__(self):
        return f'<PendingBooking {self.id} - PI: {self.payment_intent_id}>'


class InstallmentPayment(db.Model):
    """分期付款记录模型"""
    __tablename__ = 'installment_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('bookings.id'), nullable=False)
    
    # 分期信息
    installment_number = db.Column(db.Integer)  # 第几期（0=定金，1-N=分期）
    amount = db.Column(db.Float, nullable=False)  # 本期金额
    due_date = db.Column(db.Date, nullable=False)  # 到期日期
    
    # 状态
    status = db.Column(db.String(20), default='pending')  # 'pending', 'paid', 'overdue', 'cancelled'
    
    # Stripe Payment Intent
    payment_intent_id = db.Column(db.String(128), unique=True)  # Stripe Payment Intent ID
    payment_link = db.Column(db.String(500))  # 支付链接（可选）
    
    # 提醒邮件
    reminder_sent = db.Column(db.Boolean, default=False)  # 是否已发送提醒
    reminder_sent_at = db.Column(db.DateTime)  # 提醒发送时间
    reminder_count = db.Column(db.Integer, default=0)  # 提醒次数
    
    # 支付完成时间
    paid_at = db.Column(db.DateTime)
    
    # 关联关系
    booking = db.relationship('Booking', backref=db.backref('installments', lazy='dynamic'))
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<InstallmentPayment {self.id} - Booking {self.booking_id} - #{self.installment_number} - {self.status}>'


class Message(db.Model):
    """消息模型（用于行程消息管理）"""
    __tablename__ = 'messages'
    
    id = db.Column(db.Integer, primary_key=True)
    trip_id = db.Column(db.Integer, db.ForeignKey('trips.id'), nullable=False)
    sender_name = db.Column(db.String(128), nullable=False)  # 发送者姓名
    reply_to_email = db.Column(db.String(120), nullable=False)  # 回复邮箱
    
    # 收件人信息（JSON格式存储收件人列表和筛选条件）
    # 格式: {
    #   "type": "all" | "specific" | "package" | "payment_due" | "incomplete_questions" | "missing_signatures",
    #   "recipients": [{"email": "...", "name": "..."}, ...],  # 当type为specific时使用
    #   "package_id": 123,  # 当type为package时使用
    #   "addon_id": 456  # 当type为addon时使用
    # }
    recipient_config = db.Column(db.JSON, nullable=False)
    
    subject = db.Column(db.String(256), nullable=False)
    body_html = db.Column(db.Text, nullable=False)  # HTML格式的消息内容
    body_text = db.Column(db.Text)  # 纯文本格式（可选）
    
    # 附件（JSON格式存储附件列表）
    # 格式: [{"filename": "...", "path": "..."}, ...]
    attachments = db.Column(db.JSON, default=list)
    
    # 状态和类型
    status = db.Column(db.String(20), default='draft')  # draft, sent, scheduled
    message_type = db.Column(db.String(20), default='email')  # email, notification
    
    # 发送时间
    scheduled_at = db.Column(db.DateTime, nullable=True)  # 定时发送时间
    sent_at = db.Column(db.DateTime, nullable=True)  # 实际发送时间
    
    # 发送统计
    total_recipients = db.Column(db.Integer, default=0)  # 总收件人数
    sent_count = db.Column(db.Integer, default=0)  # 成功发送数
    failed_count = db.Column(db.Integer, default=0)  # 失败数
    
    # 创建者和时间戳
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关系
    trip = db.relationship('Trip', backref=db.backref('messages', lazy='dynamic'))
    created_by = db.relationship('User', backref=db.backref('messages', lazy='dynamic'))
    
    def __repr__(self):
        return f'<Message {self.id} - {self.subject}>'