import json
import math
import stripe
from flask import current_app
from datetime import datetime, date


def _normalize_metadata(metadata):
    """
    Stripe metadata only accepts string values.
    """
    if not metadata:
        return {}
    normalized = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (dict, list, tuple)):
            normalized[key] = json.dumps(value, ensure_ascii=True)
        else:
            normalized[key] = str(value)
    return normalized


def build_booking_metadata(booking, extra=None):
    """
    Build a consistent metadata payload for Stripe objects.
    """
    base = {
        'booking_id': booking.id,
        'trip_id': booking.trip_id,
        'trip_title': booking.trip.title if booking.trip else '',
        'trip_slug': booking.trip.slug if booking.trip else '',
        'client_id': booking.client_id,
        'buyer_email': booking.buyer_email,
        'buyer_name': f"{booking.buyer_first_name or ''} {booking.buyer_last_name or ''}".strip(),
    }
    if extra:
        base.update(extra)
    return _normalize_metadata(base)


def create_checkout_session(booking, line_items, success_url, cancel_url, mode='payment', metadata=None):
    """
    创建一个 Stripe Checkout 会话（重构版：支持 Booking 和复杂订单）
    
    Args:
        booking: Booking 对象
        line_items: 订单项列表，格式：[{'name': '...', 'amount': 100.00, 'quantity': 1}, ...]
        success_url: 支付成功后的重定向 URL
        cancel_url: 取消支付后的重定向 URL
        mode: 'payment' (一次性支付) 或 'subscription' (订阅，不常用)
        
    Returns:
        session: Stripe Session 对象
    """
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    
    if not stripe.api_key:
        current_app.logger.error("STRIPE_SECRET_KEY not configured")
        return None
    
    try:
        # 构建 line_items（Stripe 格式）
        stripe_line_items = []
        for item in line_items:
            stripe_line_items.append({
                'price_data': {
                    'currency': item.get('currency', 'usd'),
                    'product_data': {
                        'name': item.get('name', 'Trip Booking'),
                        'description': item.get('description', ''),
                    },
                    'unit_amount': int(item['amount'] * 100),  # Stripe 使用最小货币单位（美分）
                },
                'quantity': item.get('quantity', 1),
            })
        
        session_metadata = build_booking_metadata(booking, metadata) if metadata is not None else build_booking_metadata(booking)

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=stripe_line_items,
            mode=mode,
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=booking.buyer_email or (booking.client.email if booking.client else None),
            client_reference_id=str(booking.id),  # 将 Booking ID 作为参考
            metadata=session_metadata
        )
        return session
    except Exception as e:
        current_app.logger.error(f"Stripe Checkout Session creation failed: {str(e)}")
        return None


def create_payment_intent(amount, currency='usd', customer_id=None, metadata=None):
    """
    创建 Stripe Payment Intent（用于分期付款）
    
    Args:
        amount: 支付金额（美元）
        currency: 货币类型，默认 'usd'
        customer_id: Stripe Customer ID（可选）
        metadata: 元数据字典（可选）
        
    Returns:
        payment_intent: Stripe Payment Intent 对象
    """
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    
    if not stripe.api_key:
        current_app.logger.error("STRIPE_SECRET_KEY not configured")
        return None
    
    try:
        payment_intent_params = {
            'amount': int(amount * 100),  # Stripe 使用最小货币单位
            'currency': currency,
            'payment_method_types': ['card'],
        }
        
        if customer_id:
            payment_intent_params['customer'] = customer_id
        
        if metadata:
            normalized_metadata = _normalize_metadata(metadata)
            # 检查metadata大小（Stripe限制：每个值最多500字符）
            for key, value in normalized_metadata.items():
                if len(value) > 500:
                    current_app.logger.warning(
                        f"Metadata value for '{key}' exceeds 500 characters ({len(value)} chars). "
                        f"Stripe may reject this. Consider splitting the data."
                    )
            payment_intent_params['metadata'] = normalized_metadata
        
        payment_intent = stripe.PaymentIntent.create(**payment_intent_params)
        current_app.logger.info(f"Payment Intent created successfully: {payment_intent.id}")
        return payment_intent
    except stripe.error.StripeError as e:
        current_app.logger.error(
            f"Stripe API error while creating Payment Intent: {str(e)}. "
            f"Error type: {type(e).__name__}"
        )
        return None
    except Exception as e:
        current_app.logger.error(
            f"Unexpected error while creating Payment Intent: {str(e)}",
            exc_info=True
        )
        return None


def update_payment_intent_amount(payment_intent_id, amount_cents, metadata=None):
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    if not stripe.api_key:
        current_app.logger.error("STRIPE_SECRET_KEY not configured")
        return None
    try:
        params = {
            'amount': int(amount_cents),
        }
        if metadata:
            params['metadata'] = _normalize_metadata(metadata)
        return stripe.PaymentIntent.modify(payment_intent_id, **params)
    except Exception as e:
        current_app.logger.error(f"Stripe Payment Intent update failed: {str(e)}")
        return None


def retrieve_payment_intent(payment_intent_id):
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    if not stripe.api_key:
        current_app.logger.error("STRIPE_SECRET_KEY not configured")
        return None
    try:
        return stripe.PaymentIntent.retrieve(payment_intent_id)
    except Exception as e:
        current_app.logger.error(f"Stripe Payment Intent retrieve failed: {str(e)}")
        return None


def retrieve_payment_method_card_details(payment_method_id):
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    if not stripe.api_key:
        current_app.logger.error("STRIPE_SECRET_KEY not configured")
        return "unknown", "unknown"
    try:
        payment_method = stripe.PaymentMethod.retrieve(payment_method_id)
    except Exception:
        return "unknown", "unknown"

    card = getattr(payment_method, "card", None)
    if not card:
        return "unknown", "unknown"

    return card.get("funding", "unknown"), card.get("brand", "unknown")


def calculate_fee(base_amount_cents, funding, brand):
    if funding != "credit":
        return 0
    if brand == "amex":
        return int(math.ceil(base_amount_cents * 0.035))
    if brand in {"visa", "mastercard"}:
        return int(math.ceil(base_amount_cents * 0.029))
    return int(math.ceil(base_amount_cents * 0.029))


def process_refund(payment_intent_id, amount, reason=None):
    """
    处理 Stripe 退款
    
    Args:
        payment_intent_id: Stripe Payment Intent ID 或 Charge ID
        amount: 退款金额（美元，例如 100.00）
        reason: 退款原因（可选）
        
    Returns:
        refund: Stripe Refund 对象，如果失败则返回 None
    """
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    
    if not stripe.api_key:
        current_app.logger.error("STRIPE_SECRET_KEY not configured")
        return None
    
    try:
        # Convert amount to cents (Stripe uses smallest currency unit)
        amount_cents = int(amount * 100)
        
        # Create refund
        refund = stripe.Refund.create(
            payment_intent=payment_intent_id,
            amount=amount_cents,
            reason='requested_by_customer' if reason else None,
            metadata={
                'refund_reason': reason or 'No reason provided'
            } if reason else None
        )
        
        current_app.logger.info(f"Refund created: {refund.id} for amount ${amount}")
        return refund
        
    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe refund failed: {str(e)}")
        return None
    except Exception as e:
        current_app.logger.error(f"Unexpected error during refund: {str(e)}")
        return None


def calculate_booking_total(booking):
    """
    计算 Booking 的总金额（包括套餐、附加项、折扣）
    
    Args:
        booking: Booking 对象
        
    Returns:
        dict: {
            'subtotal': 小计（套餐 + 附加项）,
            'discount': 折扣金额,
            'total': 总计（净金额，不含 Stripe 手续费），
            'amount_paid': 已支付金额（不含 Stripe 手续费），
            'amount_due': 待支付金额
        }
    
    注意：
    - total 是客户应付的净金额，不包含 Stripe 手续费
    - amount_paid 来自 Booking.amount_paid，也是不含手续费的基础金额
    - Stripe 手续费是在支付时额外收取的，由客户承担，但不进入我们的收入
    """
    subtotal = 0.0
    
    # 计算套餐金额
    for bp in booking.booking_packages.all():
        if bp.package and bp.package.price:
            package_price = float(bp.package.price)
            quantity = int(bp.quantity) if bp.quantity else 1
            subtotal += package_price * quantity
    
    # 计算附加项金额
    for addon in booking.addons.all():
        if addon.addon and addon.addon.price:
            addon_price = float(addon.addon.price)
            quantity = int(addon.quantity) if addon.quantity else 1
            subtotal += addon_price * quantity
    
    # 应用折扣码（从 Booking.discount_amount 获取）
    discount = float(booking.discount_amount) if booking.discount_amount else 0.0
    
    total = max(0.0, subtotal - discount)
    amount_paid = float(booking.amount_paid) if booking.amount_paid else 0.0
    amount_due = max(0.0, total - amount_paid)
    
    return {
        'subtotal': subtotal,
        'discount': discount,
        'total': total,
        'amount_paid': amount_paid,
        'amount_due': amount_due
    }


def calculate_initial_payment_amount(booking, payment_plan='full'):
    """
    计算首付款金额（追缴模式：Catch-up Mode）
    
    根据设计文档，如果用户报名时，分期计划中的某些期数已经过期（DueDate < Today），
    则这些过期的金额必须合并到首付款中一次性支付。
    
    公式：首付款 = 定金 + 所有过期分期的金额 + 所有附加项金额
    
    Args:
        booking: Booking 对象
        payment_plan: 支付计划类型 ('full' 或 'deposit_installment')
        
    Returns:
        dict: {
            'initial_amount': 首付款金额,
            'deposit': 定金金额,
            'overdue_installments': 过期分期金额总和,
            'addons': 附加项金额总和,
            'overdue_details': 过期分期详情列表
        }
    """
    today = date.today()
    initial_amount = 0.0
    deposit_amount = 0.0
    overdue_installments_total = 0.0
    addons_total = 0.0
    overdue_details = []
    
    # 如果是全款支付，返回总金额
    if payment_plan == 'full':
        total_info = calculate_booking_total(booking)
        return {
            'initial_amount': total_info['total'],
            'deposit': 0.0,
            'overdue_installments': 0.0,
            'addons': total_info['subtotal'] - sum(
                float(bp.package.price) * (int(bp.quantity) if bp.quantity else 1)
                for bp in booking.booking_packages.all()
                if bp.package and bp.package.price
            ),
            'overdue_details': []
        }
    
    # 计算附加项金额
    for addon in booking.addons.all():
        if addon.addon and addon.addon.price:
            addon_price = float(addon.addon.price)
            quantity = int(addon.quantity) if addon.quantity else 1
            addons_total += addon_price * quantity
    
    # 遍历所有 BookingPackage，检查分期付款计划
    for bp in booking.booking_packages.all():
        if not bp.package:
            continue
            
        # 检查是否有分期付款计划
        if bp.payment_plan_type == 'deposit_installment' and bp.package.payment_plan_config:
            config = bp.package.payment_plan_config
            if config and config.get('enabled'):
                # 获取定金金额
                deposit = config.get('deposit_amount', 0.0) or config.get('deposit', 0.0)
                deposit_amount += float(deposit) * (int(bp.quantity) if bp.quantity else 1)
                
                # 检查分期付款计划中的过期分期
                installments = config.get('installments', [])
                for inst_data in installments:
                    due_date_str = inst_data.get('date')
                    if not due_date_str:
                        continue
                    
                    try:
                        due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date()
                        inst_amount = float(inst_data.get('amount', 0.0))
                        quantity = int(bp.quantity) if bp.quantity else 1
                        
                        # 如果到期日期 < 今天，则过期，需要合并到首付款
                        if due_date < today:
                            overdue_amount = inst_amount * quantity
                            overdue_installments_total += overdue_amount
                            overdue_details.append({
                                'package_name': bp.package.name,
                                'due_date': due_date_str,
                                'amount': inst_amount,
                                'quantity': quantity,
                                'total': overdue_amount
                            })
                    except (ValueError, TypeError) as e:
                        current_app.logger.error(f"Invalid installment date or amount: {due_date_str}, {str(e)}")
                        continue
        else:
            # 如果没有分期付款计划，使用套餐全价作为首付款
            if bp.package and bp.package.price:
                package_price = float(bp.package.price)
                quantity = int(bp.quantity) if bp.quantity else 1
                deposit_amount += package_price * quantity
    
    # 计算首付款总额：定金 + 过期分期 + 附加项
    initial_amount = deposit_amount + overdue_installments_total + addons_total
    
    current_app.logger.info(
        f"Initial payment calculated for booking {booking.id}: "
        f"deposit={deposit_amount}, overdue={overdue_installments_total}, "
        f"addons={addons_total}, total={initial_amount}"
    )
    
    return {
        'initial_amount': initial_amount,
        'deposit': deposit_amount,
        'overdue_installments': overdue_installments_total,
        'addons': addons_total,
        'overdue_details': overdue_details
    }