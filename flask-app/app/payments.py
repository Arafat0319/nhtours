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
    if getattr(booking, 'order_number', None):
        base['order_number'] = booking.order_number
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


def safe_cancel_payment_intent(payment_intent_id, reason=''):
    """
    取消 PaymentIntent；已 canceled / succeeded 等不可取消状态不视为失败。
    free_ 占位 ID 直接跳过。返回 True 表示已取消或无需取消。
    """
    if not payment_intent_id or str(payment_intent_id).startswith('free_'):
        return True

    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    if not stripe.api_key:
        current_app.logger.warning(
            f"safe_cancel_payment_intent: no STRIPE_SECRET_KEY ({reason})"
        )
        return False

    try:
        pi = stripe.PaymentIntent.retrieve(payment_intent_id)
        status = getattr(pi, 'status', None)
        if status == 'canceled':
            current_app.logger.info(
                f"PaymentIntent {payment_intent_id} already canceled ({reason})"
            )
            return True
        if status in ('succeeded', 'processing'):
            current_app.logger.info(
                f"PaymentIntent {payment_intent_id} status={status}, skip cancel ({reason})"
            )
            return True
        if status in (
            'requires_payment_method',
            'requires_confirmation',
            'requires_action',
            'requires_capture',
        ):
            stripe.PaymentIntent.cancel(payment_intent_id)
            current_app.logger.info(
                f"Cancelled PaymentIntent {payment_intent_id} ({reason})"
            )
            return True
        current_app.logger.info(
            f"PaymentIntent {payment_intent_id} status={status}, skip cancel ({reason})"
        )
        return True
    except Exception as e:
        err = str(e).lower()
        if 'already been canceled' in err or 'already canceled' in err:
            current_app.logger.info(
                f"PaymentIntent {payment_intent_id} already canceled ({reason})"
            )
            return True
        current_app.logger.warning(
            f"safe_cancel_payment_intent failed for {payment_intent_id} ({reason}): {e}"
        )
        return False


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


def extract_stripe_charge_id(payment_intent):
    """从 PaymentIntent（dict 或 Stripe 对象）取出 latest_charge id。"""
    if not payment_intent:
        return None
    if isinstance(payment_intent, dict):
        latest = payment_intent.get('latest_charge')
        charges = (payment_intent.get('charges') or {}).get('data') or []
    else:
        latest = getattr(payment_intent, 'latest_charge', None)
        charges_obj = getattr(payment_intent, 'charges', None)
        charges = list(getattr(charges_obj, 'data', None) or []) if charges_obj else []
    if isinstance(latest, str) and latest.startswith('ch_'):
        return latest
    if latest is not None and hasattr(latest, 'id'):
        return latest.id
    if charges:
        first = charges[0]
        if isinstance(first, dict):
            return first.get('id')
        return getattr(first, 'id', None)
    return None


def payment_charged_amount(payment):
    """客户该笔实扣（美元，含手续费）。"""
    if payment.final_amount_cents is not None:
        return round(payment.final_amount_cents / 100.0, 2)
    return round(float(payment.amount or 0.0), 2)


def payment_base_amount(payment):
    """该笔基础金额（美元，不含卡费）。卡费不退。"""
    if payment.base_amount_cents is not None:
        return round(payment.base_amount_cents / 100.0, 2)
    charged = payment_charged_amount(payment)
    fee = (payment.fee_cents or 0) / 100.0
    return round(max(0.0, charged - fee), 2)


def payment_fee_amount(payment):
    """该笔卡手续费（美元），永不退还。"""
    if payment.fee_cents is not None:
        return round(payment.fee_cents / 100.0, 2)
    return round(max(0.0, payment_charged_amount(payment) - payment_base_amount(payment)), 2)


def payment_refundable_remaining(payment):
    """
    该笔剩余可退（基础金额口径，不含卡费）。
    refunded_amount 存的是已退的基础美元（与 Stripe 退款金额一致，因手续费不退）。
    """
    base = payment_base_amount(payment)
    already = round(float(payment.refunded_amount or 0.0), 2)
    return round(max(0.0, base - already), 2)


def booking_deposit_reserved(booking, deposit_hint=None):
    """订单上默认保留不退的定金（基础金额）。"""
    if deposit_hint is None:
        deposit_hint = 0.0
        for bp in booking.booking_packages:
            cfg = (bp.package.payment_plan_config if bp.package else None) or {}
            dep = cfg.get('deposit_amount') or cfg.get('deposit')
            if dep is not None:
                try:
                    deposit_hint = float(dep) * (int(bp.quantity) if bp.quantity else 1)
                    break
                except (TypeError, ValueError):
                    pass
    try:
        deposit_hint = float(deposit_hint or 0.0)
    except (TypeError, ValueError):
        deposit_hint = 0.0
    paid = round(float(booking.amount_paid or 0.0), 2)
    return round(min(max(0.0, deposit_hint), paid), 2)


def payment_max_refund(payment, booking, include_deposit=False, deposit_hint=None):
    """
    管理员可退上限（基础金额）：
    - 不超过该笔剩余基础可退
    - 默认不含定金：不超过 booking.amount_paid − 定金保留
    - 勾选 include_deposit 后可退满该笔剩余
    """
    pay_remaining = payment_refundable_remaining(payment)
    if include_deposit:
        return pay_remaining
    reserved = booking_deposit_reserved(booking, deposit_hint=deposit_hint)
    booking_cap = round(max(0.0, float(booking.amount_paid or 0.0) - reserved), 2)
    return round(min(pay_remaining, booking_cap), 2)


def stripe_refunded_as_base(payment, stripe_refunded_charged):
    """
    Stripe Charge.amount_refunded（实扣口径累计）→ 本地应记的基础已退。
    手续费不退：超过 base 的部分（卡费）忽略，不扣 Booking.amount_paid。
    """
    base = payment_base_amount(payment)
    return round(min(max(0.0, float(stripe_refunded_charged or 0.0)), base), 2)


def charged_refund_to_base(payment, refund_amount):
    """
    兼容旧调用：将实扣口径退款映射为基础金额（手续费部分截断）。
    新代码优先用 stripe_refunded_as_base 做累计换算。
    """
    return stripe_refunded_as_base(payment, refund_amount)


def process_refund(payment_intent_id, amount, reason=None):
    """
    通过 Stripe PaymentIntent 发起退款（金额为美元基础金额，不含卡费）。

    Returns:
        (refund, error_message): 成功时 (Refund, None)；失败时 (None, str)
    """
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')

    if not stripe.api_key:
        return None, 'STRIPE_SECRET_KEY not configured'

    if not payment_intent_id or not str(payment_intent_id).startswith('pi_'):
        return None, 'Invalid payment_intent_id (expected pi_…)'

    try:
        amount_cents = int(round(float(amount) * 100))
        if amount_cents <= 0:
            return None, 'Refund amount must be positive'

        params = {
            'payment_intent': payment_intent_id,
            'amount': amount_cents,
        }
        if reason:
            params['reason'] = 'requested_by_customer'
            params['metadata'] = {'refund_reason': reason[:500]}

        refund = stripe.Refund.create(**params)
        current_app.logger.info(f"Refund created: {refund.id} for amount ${amount} on {payment_intent_id}")
        return refund, None

    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe refund failed: {str(e)}")
        return None, str(e)
    except Exception as e:
        current_app.logger.error(f"Unexpected error during refund: {str(e)}")
        return None, str(e)


def cancel_unpaid_installments(booking):
    """
    订单取消后：未付分期（pending/overdue）标为 cancelled，并尽量取消关联 Stripe PI。
    已付分期不动。调用方负责 commit。
    """
    from app.models import InstallmentPayment

    if not booking or not getattr(booking, 'id', None):
        return 0
    rows = InstallmentPayment.query.filter(
        InstallmentPayment.booking_id == booking.id,
        InstallmentPayment.status.in_(('pending', 'overdue')),
    ).all()
    for inst in rows:
        if getattr(inst, 'payment_intent_id', None):
            safe_cancel_payment_intent(
                inst.payment_intent_id,
                reason=f'booking {booking.id} cancelled installment {inst.id}',
            )
        inst.status = 'cancelled'
    return len(rows)


def apply_refund_to_ledger(payment, booking, refund_amount, reason=None, stripe_refund_id=None,
                           cancel_booking=False, manual_only=False):
    """
    将一笔退款写入 Payment + Booking（调用方负责 commit）。

    refund_amount: 基础金额美元（不含卡费）。卡费永不计入。
    """
    refund_amount = round(float(refund_amount), 2)
    remaining = payment_refundable_remaining(payment)
    if refund_amount <= 0:
        raise ValueError('Refund amount must be positive')
    if refund_amount > remaining + 0.001:
        raise ValueError(f'Refund amount ${refund_amount:.2f} exceeds remaining ${remaining:.2f}')

    already = round(float(payment.refunded_amount or 0.0), 2)
    payment.refunded_amount = round(already + refund_amount, 2)
    payment.refunded_at = datetime.utcnow()
    if reason:
        payment.refund_reason = (reason or '')[:200]

    meta = dict(payment.payment_metadata or {})
    history = list(meta.get('refund_history') or [])
    history.append({
        'amount': refund_amount,
        'reason': reason or '',
        'stripe_refund_id': stripe_refund_id,
        'manual_only': bool(manual_only),
        'excludes_fee': True,
        'at': datetime.utcnow().isoformat() + 'Z',
    })
    meta['refund_history'] = history
    if stripe_refund_id:
        meta['last_stripe_refund_id'] = stripe_refund_id
    payment.payment_metadata = meta

    base = payment_base_amount(payment)
    if payment.refunded_amount >= base - 0.001:
        payment.status = 'refunded'
        payment.refunded_amount = base
    else:
        payment.status = 'partially_refunded'

    # 基础金额退款，直接扣 Booking.amount_paid
    booking.amount_paid = max(0.0, round(float(booking.amount_paid or 0.0) - refund_amount, 2))

    if cancel_booking or booking.amount_paid <= 0.001:
        if booking.amount_paid <= 0.001:
            booking.amount_paid = 0.0
        if cancel_booking or booking.amount_paid == 0.0:
            booking.status = 'cancelled'
            cancel_unpaid_installments(booking)
    elif booking.status == 'fully_paid':
        booking.status = 'deposit_paid'

    return {
        'refund_amount': refund_amount,
        'base_reduction': refund_amount,
        'payment_refunded_amount': payment.refunded_amount,
        'booking_amount_paid': booking.amount_paid,
        'booking_status': booking.status,
    }


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