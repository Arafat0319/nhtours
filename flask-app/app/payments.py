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


def clamp_refunded_amount(value, base):
    """强制 0 ≤ refunded ≤ base（基础美元）。"""
    try:
        x = float(value or 0.0)
    except (TypeError, ValueError):
        x = 0.0
    try:
        base_f = float(base or 0.0)
    except (TypeError, ValueError):
        base_f = 0.0
    return round(min(max(0.0, x), max(0.0, base_f)), 2)


def payment_refunded_clamped(payment):
    """该笔已退基础额（钳制到 [0, base]）。"""
    return clamp_refunded_amount(payment.refunded_amount, payment_base_amount(payment))


def payment_refundable_remaining(payment):
    """
    该笔剩余可退（基础金额口径，不含卡费）。
    refunded_amount 存的是已退的基础美元（与 Stripe 退款金额一致，因手续费不退）。
    """
    base = payment_base_amount(payment)
    already = payment_refunded_clamped(payment)
    return round(max(0.0, base - already), 2)


def installment_display_label(installment=None, *, installment_number=None, booking_id=None,
                              post_deposit_count=None):
    """
    客户/后台可见的分期名称。
    定金后仅 1 期尾款时显示 Final payment；多期仍为 Installment #n。
    """
    num = installment_number
    if num is None and installment is not None:
        num = getattr(installment, 'installment_number', None)
    if num is None or num == 0:
        return 'Deposit'

    count = post_deposit_count
    if count is None:
        bid = booking_id
        if bid is None and installment is not None:
            bid = getattr(installment, 'booking_id', None)
        count = booking_post_deposit_installment_count(bid) if bid else 0

    if count == 1:
        return 'Final payment'
    return f'Installment #{num}'


def payment_step_label(payment):
    """收据/Manage：Initial / Installment #n / Final payment / Payoff。"""
    meta = dict(payment.payment_metadata or {})
    step = (meta.get('payment_step') or '').strip().lower()
    if step == 'payoff':
        return 'Payoff'
    if step == 'installment':
        inst = getattr(payment, 'installment_payment', None)
        num = getattr(inst, 'installment_number', None) if inst else meta.get('installment_number')
        if num is not None and str(num) != '':
            try:
                num_int = int(num)
            except (TypeError, ValueError):
                return 'Installment'
            bid = getattr(payment, 'booking_id', None) or (
                getattr(inst, 'booking_id', None) if inst else None
            )
            return installment_display_label(
                installment_number=num_int,
                booking_id=bid,
            )
        return 'Installment'
    if step in ('initial', '', 'booking'):
        return 'Initial'
    return step.replace('_', ' ').title() or 'Payment'


def ledger_payments_for_booking(booking):
    """计入账本的 Payment 行（成功/部分退/全退）。"""
    from app.models import Payment

    rows = (
        Payment.query.filter(
            Payment.booking_id == booking.id,
            Payment.status.in_(('succeeded', 'partially_refunded', 'refunded')),
        )
        .order_by(Payment.paid_at.asc(), Payment.created_at.asc(), Payment.id.asc())
        .all()
    )
    return rows


def computed_booking_amount_paid(booking):
    """Σ(payment 基础 − 已退基础)；与 Booking.amount_paid 应对齐。"""
    total = 0.0
    for payment in ledger_payments_for_booking(booking):
        base = payment_base_amount(payment)
        refunded = payment_refunded_clamped(payment)
        total += max(0.0, base - refunded)
    return round(total, 2)


def booking_refunded_total(booking):
    """订单已退基础金额合计（Σ payment.refunded_amount，钳制后）。"""
    total = 0.0
    for payment in ledger_payments_for_booking(booking):
        total += payment_refunded_clamped(payment)
    return round(total, 2)


def booking_has_refund(booking):
    """是否有过基础额退款（部分或全额）。"""
    for payment in ledger_payments_for_booking(booking):
        if payment_refunded_clamped(payment) > 0.001:
            return True
        if (payment.status or '') in ('refunded', 'partially_refunded'):
            return True
    return False


def booking_refundable_remaining_total(booking):
    """订单剩余可退基础金额合计。"""
    total = 0.0
    for payment in ledger_payments_for_booking(booking):
        if (payment.status or '') not in ('succeeded', 'partially_refunded', 'refunded'):
            continue
        total += payment_refundable_remaining(payment)
    return round(total, 2)


def booking_refund_display_kind(booking):
    """
    退款展示分类（相对已收款，非行程全价）：
    - None：无退款
    - 'fully_refunded'：已收基础额已全部退完（无可退余额）
    - 'partially_refunded'：退过款但仍有可退余额
    """
    refunded = booking_refunded_total(booking)
    if refunded <= 0.001 and not booking_has_refund(booking):
        return None
    if refunded <= 0.001:
        # 状态标了退款但金额异常时，仍按有退款处理
        remaining = booking_refundable_remaining_total(booking)
        return 'fully_refunded' if remaining <= 0.001 else 'partially_refunded'
    remaining = booking_refundable_remaining_total(booking)
    if remaining <= 0.001:
        return 'fully_refunded'
    return 'partially_refunded'


def booking_balance_due(booking, expected=None):
    """
    客户仍应付金额（Balance due）。
    退款会降低 amount_paid，但不能把已退部分算成「还欠」：
    due = expected − amount_paid − refunded（≡ expected − 原已收基础额）。
    """
    if (getattr(booking, 'status', None) or '') == 'cancelled':
        return None
    if expected is None:
        totals = calculate_booking_total(booking)
        return round(float(totals.get('amount_due') or 0.0), 2)
    paid = float(booking.amount_paid) if booking.amount_paid is not None else 0.0
    refunded = booking_refunded_total(booking)
    return round(max(0.0, float(expected) - paid - refunded), 2)


def booking_has_overdue_amount(booking, today=None):
    """
    当前仍有应付，且存在已过 due_date 的未付分期。
    日历日按美西（与催款一致）。
    """
    from app.models import InstallmentPayment
    from app.utils import pacific_today

    if (booking.status or '') == 'cancelled':
        return False
    if (booking.status or '') == 'fully_paid':
        return False

    today = today or pacific_today()
    past_due = (
        InstallmentPayment.query.filter(
            InstallmentPayment.booking_id == booking.id,
            InstallmentPayment.status.in_(('pending', 'overdue')),
            InstallmentPayment.due_date.isnot(None),
            InstallmentPayment.due_date < today,
        )
        .first()
    )
    if not past_due:
        return False
    try:
        due = float(calculate_booking_total(booking).get('amount_due') or 0)
    except Exception:
        due = 1.0
    return due > 0.001


def booking_payment_display_status(booking, today=None):
    """
    后台 Payment Status 展示态（不改库内 booking.status）。
    优先级：cancelled > fully_refunded / partially_refunded > overdue > 库内 status
    """
    stored = (getattr(booking, 'status', None) or 'pending').strip() or 'pending'
    if stored == 'cancelled':
        return 'cancelled'
    kind = booking_refund_display_kind(booking)
    if kind:
        return kind
    if booking_has_overdue_amount(booking, today=today):
        return 'overdue'
    return stored


def reconcile_booking_ledger(booking):
    """
    只读核对：amount_paid 是否等于 Σ(base − refunded)。
    同时报告异常 refunded_amount（超出 base）。
    """
    stored = round(float(booking.amount_paid or 0.0), 2)
    computed = computed_booking_amount_paid(booking)
    delta = round(stored - computed, 2)
    anomalies = []
    for payment in ledger_payments_for_booking(booking):
        base = payment_base_amount(payment)
        raw = round(float(payment.refunded_amount or 0.0), 2)
        clamped = clamp_refunded_amount(raw, base)
        meta = dict(payment.payment_metadata or {})
        history = meta.get('refund_history') or []
        if abs(raw - clamped) > 0.001:
            anomalies.append({
                'payment_id': payment.id,
                'issue': 'refunded_amount_out_of_range',
                'refunded_amount': raw,
                'base': base,
                'clamped': clamped,
            })
        if clamped > 0.001 and not history:
            anomalies.append({
                'payment_id': payment.id,
                'issue': 'missing_refund_history',
                'refunded_amount': clamped,
            })
    return {
        'booking_id': booking.id,
        'order_number': getattr(booking, 'order_number', None),
        'stored_amount_paid': stored,
        'computed_amount_paid': computed,
        'delta': delta,
        'ok': abs(delta) < 0.015 and not anomalies,
        'anomalies': anomalies,
    }


def build_receipt_ledger_sections(booking):
    """
    收据用：Payment history / Installment schedule / Refunds。
    金额均为基础美元（不含卡费），除非字段名标明 charged/fee。
    """
    from app.models import InstallmentPayment

    payment_history = []
    refunds = []
    for payment in ledger_payments_for_booking(booking):
        base = payment_base_amount(payment)
        fee = payment_fee_amount(payment)
        charged = payment_charged_amount(payment)
        refunded = payment_refunded_clamped(payment)
        raw_refunded = round(float(payment.refunded_amount or 0.0), 2)
        net = round(max(0.0, base - refunded), 2)
        paid_at = payment.paid_at or payment.created_at
        payment_history.append({
            'id': payment.id,
            'date': paid_at,
            'type_label': payment_step_label(payment),
            'base': base,
            'fee': fee,
            'charged': charged,
            'refunded': refunded,
            'net': net,
            'status': payment.status,
        })
        meta = dict(payment.payment_metadata or {})
        history = list(meta.get('refund_history') or [])
        if history:
            for entry in history:
                try:
                    amt = float(entry.get('amount') or 0)
                except (TypeError, ValueError):
                    amt = 0.0
                if amt <= 0:
                    continue
                refunds.append({
                    'payment_id': payment.id,
                    'amount': round(amt, 2),
                    'reason': entry.get('reason') or '',
                    'at': entry.get('at'),
                    'stripe_refund_id': entry.get('stripe_refund_id'),
                })
        elif refunded > 0.001:
            refunds.append({
                'payment_id': payment.id,
                'amount': refunded,
                'reason': payment.refund_reason or (
                    'Recorded refund' if abs(raw_refunded - refunded) < 0.001
                    else f'Recorded refund (clamped from ${raw_refunded:,.2f})'
                ),
                'at': payment.refunded_at.isoformat() + 'Z' if payment.refunded_at else None,
                'stripe_refund_id': None,
            })

    book_date = booking.created_at.date() if getattr(booking, 'created_at', None) else None
    installment_schedule = []
    rows = (
        InstallmentPayment.query.filter_by(booking_id=booking.id)
        .order_by(InstallmentPayment.installment_number.asc(), InstallmentPayment.id.asc())
        .all()
    )
    post_deposit_count = sum(
        1 for inst in rows if (inst.installment_number or 0) > 0
    )
    for inst in rows:
        note = None
        status_label = (inst.status or 'pending').replace('_', ' ').title()
        if (
            inst.installment_number
            and inst.installment_number > 0
            and inst.status == 'paid'
            and book_date
            and inst.due_date
            and inst.due_date < book_date
        ):
            note = 'Included in initial payment'
            status_label = 'Paid (in initial)'
        elif inst.installment_number == 0:
            status_label = f'Deposit — {status_label}'
        installment_schedule.append({
            'number': inst.installment_number,
            'label': installment_display_label(
                inst,
                post_deposit_count=post_deposit_count,
            ),
            'amount': round(float(inst.amount or 0), 2),
            'due_date': inst.due_date,
            'status': inst.status,
            'status_label': status_label,
            'note': note,
            'paid_at': inst.paid_at,
        })

    return {
        'payment_history': payment_history,
        'installment_schedule': installment_schedule,
        'refunds': refunds,
    }


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


def installment_has_other_unpaid(installment, all_installments=None):
    """
    当前期之外是否还有未付分期。
    无其他未付时（即最后一期）付款页不展示 PAY OFF。
    """
    from app.models import InstallmentPayment

    if not installment:
        return False
    if all_installments is None:
        booking_id = getattr(installment, 'booking_id', None)
        if not booking_id:
            return False
        all_installments = InstallmentPayment.query.filter_by(booking_id=booking_id).all()
    return any(
        getattr(i, 'id', None) != getattr(installment, 'id', None)
        and (getattr(i, 'status', None) or '') in ('pending', 'overdue')
        for i in (all_installments or [])
    )


def booking_post_deposit_installment_count(booking_id):
    """定金之后的期数（installment_number > 0）。"""
    from app.models import InstallmentPayment

    if not booking_id:
        return 0
    return (
        InstallmentPayment.query.filter(
            InstallmentPayment.booking_id == booking_id,
            InstallmentPayment.installment_number > 0,
        ).count()
    )


def booking_is_multi_period_plan(booking_id):
    """
    真正的多期分期：定金后有 **大于 1 期** 尾款。
    定金 + 单笔尾款（deposit + balance）不算 Installment Payments 分类。
    """
    return booking_post_deposit_installment_count(booking_id) > 1


def _booking_ids_with_post_deposit_count(count_op, count_value, booking_ids=None):
    """按定金后期数筛选 booking_id。count_op: 'eq' | 'gt'。"""
    from app import db
    from app.models import InstallmentPayment
    from sqlalchemy import func

    having = (
        func.count(InstallmentPayment.id) == count_value
        if count_op == 'eq'
        else func.count(InstallmentPayment.id) > count_value
    )
    q = (
        db.session.query(InstallmentPayment.booking_id)
        .filter(InstallmentPayment.installment_number > 0)
        .group_by(InstallmentPayment.booking_id)
        .having(having)
    )
    if booking_ids is not None:
        ids = list(booking_ids)
        if not ids:
            return set()
        q = q.filter(InstallmentPayment.booking_id.in_(ids))
    return {row[0] for row in q.all() if row[0] is not None}


def multi_period_booking_ids(booking_ids=None):
    """定金后 >1 期 → Installment Payments。"""
    return _booking_ids_with_post_deposit_count('gt', 1, booking_ids=booking_ids)


def single_balance_booking_ids(booking_ids=None):
    """定金后恰好 1 期尾款（Final payment）→ Full Payments。"""
    return _booking_ids_with_post_deposit_count('eq', 1, booking_ids=booking_ids)


def booking_payments_plan_kind(booking_id):
    """
    订单在 Payments 页的归属：
    - multi: 定金后 >1 期 → Installment
    - deposit_balance: 定金 + 1 笔尾款 → Full
    - one_time: 无分期尾款（一次付清等）→ Full
    """
    n = booking_post_deposit_installment_count(booking_id)
    if n > 1:
        return 'multi'
    if n == 1:
        return 'deposit_balance'
    return 'one_time'


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

    base = payment_base_amount(payment)
    already = payment_refunded_clamped(payment)
    # 不变量：0 ≤ refunded_amount ≤ base，且必须有 refund_history
    payment.refunded_amount = clamp_refunded_amount(already + refund_amount, base)
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
    amount_refunded = booking_refunded_total(booking)
    # 已退部分曾计入收款，不能因退款再变成「欠款」
    amount_due = max(0.0, total - amount_paid - amount_refunded)
    
    return {
        'subtotal': subtotal,
        'discount': discount,
        'total': total,
        'amount_paid': amount_paid,
        'amount_refunded': amount_refunded,
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