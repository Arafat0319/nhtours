"""Payments 列表：以 order/booking 为基本单位组装 Full / Installment 数据。"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import joinedload

from app.models import Booking, InstallmentPayment, Payment
from app.utils import pacific_today


def _installment_unpaid(inst):
    return (getattr(inst, 'status', None) or '') in ('pending', 'overdue')


def booking_discount_info(booking):
    """订单折扣摘要（报名/首笔付款时用的优惠码）。"""
    if not booking:
        return None
    amount = float(getattr(booking, 'discount_amount', None) or 0)
    code_obj = getattr(booking, 'discount_code', None)
    code = (code_obj.code if code_obj else None) or None
    if amount <= 0.001 and not code:
        return None
    return {
        'code': code,
        'amount': round(amount, 2),
        'type': getattr(code_obj, 'type', None) if code_obj else None,
        'value': getattr(code_obj, 'amount', None) if code_obj else None,
    }


def _line_display_status(inst, payment=None, *, covered_by_catch_up=False):
    """
    列表展示用状态：若已有成功收款 Payment，即使 installment 行仍为 pending 也显示 paid。
    """
    if covered_by_catch_up:
        return 'paid'
    if payment is not None:
        pst = (payment.status or '').lower()
        if pst == 'succeeded':
            return 'paid'
        if pst == 'partially_refunded':
            return 'partially refunded'
        if pst == 'refunded':
            return 'fully refunded'
        if pst == 'pending':
            return 'pending'
    return (getattr(inst, 'status', None) or 'pending') if inst is not None else 'pending'


def _matches_search(booking, search):
    if not search:
        return True
    q = search.lower()
    order_no = (booking.order_number or '').lower()
    buyer = (booking.buyer_name or '').lower()
    email = (booking.buyer_email or '').lower()
    trip_title = ''
    if booking.trip:
        trip_title = (booking.trip.title or '').lower()
    return (
        q in order_no
        or q in str(booking.id)
        or q in buyer
        or q in email
        or q in trip_title
    )


def _filter_by_schedule_status(group, status_filter):
    if not status_filter:
        return True
    # 兼容 Full 旧筛选 succeeded → paid
    if status_filter == 'succeeded':
        status_filter = 'paid'
    if status_filter == 'paid':
        return not group.get('has_unpaid')
    if status_filter in ('pending', 'overdue'):
        nxt = group.get('next_action_installment')
        return bool(nxt) and (nxt.status or '') == status_filter
    return True


def _attach_payments_and_sub_items(groups, payments_map, *, covered_ids=None):
    covered_ids = covered_ids or set()
    for group in groups:
        deposit = group.get('deposit')
        if deposit:
            deposit_payments = payments_map.get(deposit.id, [])
            # 优先 succeeded 的 Payment，避免挂到 pending PI
            deposit_payment = next(
                (p for p in deposit_payments if (p.status or '') == 'succeeded'),
                deposit_payments[0] if deposit_payments else None,
            )
            group['deposit_payment'] = deposit_payment
            group['deposit_display_status'] = _line_display_status(
                deposit, deposit_payment, covered_by_catch_up=deposit.id in covered_ids
            )
        else:
            group['deposit_payment'] = group.get('primary_payment')
            group['deposit_display_status'] = _line_display_status(
                None, group.get('primary_payment')
            )

        group['others_payments'] = {}
        group['others_covered'] = {}
        for inst in group.get('others') or []:
            inst_payments = payments_map.get(inst.id, [])
            inst_payment = next(
                (p for p in inst_payments if (p.status or '') == 'succeeded'),
                inst_payments[0] if inst_payments else None,
            )
            group['others_payments'][inst.id] = inst_payment
            group['others_covered'][inst.id] = inst.id in covered_ids

        # 未付判断：展示态为 paid/refunded 的不算未付（避免库内 installment 未同步）
        schedule = []
        if deposit:
            schedule.append(deposit)
        schedule.extend(group.get('others') or [])

        def _still_unpaid(inst):
            pay = (
                group.get('deposit_payment')
                if deposit and inst.id == deposit.id
                else group['others_payments'].get(inst.id)
            )
            return _line_display_status(
                inst, pay, covered_by_catch_up=inst.id in covered_ids
            ) in ('pending', 'overdue')

        unpaid = [i for i in schedule if i and _still_unpaid(i)]
        unpaid.sort(
            key=lambda i: (
                i.due_date or datetime.max.date(),
                i.installment_number if i.installment_number is not None else 999,
            )
        )
        group['next_action_installment'] = unpaid[0] if unpaid else None
        group['has_unpaid'] = bool(unpaid)

        sub_items = []
        if group.get('payoff_payment'):
            payoff = group['payoff_payment']
            sub_items.append({
                'type': 'payoff',
                'payment': payoff,
                'payment_time': payoff.paid_at or payoff.created_at or datetime.max,
                'installment': None,
                'display_status': 'paid',
                'covered_by_catch_up': False,
            })
        for inst in group.get('others') or []:
            payment = group['others_payments'].get(inst.id)
            covered = bool(group['others_covered'].get(inst.id))
            if payment and payment.paid_at:
                payment_time = payment.paid_at
            elif inst.paid_at:
                payment_time = inst.paid_at
            else:
                payment_time = None
            sub_items.append({
                'type': 'installment',
                'payment': payment,
                'payment_time': payment_time,
                'installment': inst,
                'display_status': _line_display_status(
                    inst, payment, covered_by_catch_up=covered
                ),
                'covered_by_catch_up': covered,
            })

        def sort_key(item):
            if item['type'] == 'payoff':
                return (2, item['payment_time'] or datetime.max)
            inst = item['installment']
            return (0, inst.installment_number if inst and inst.installment_number is not None else 999)

        group['sub_items'] = sorted(sub_items, key=sort_key)


def build_schedule_order_groups(*, plan_kinds, search='', status_filter='', limit=200):
    """
    按付款计划组装可展开的 order 行。
    plan_kinds: {'deposit_balance'} 或 {'multi'} 或两者。

    按 booking 分页（不再对 InstallmentPayment 全局 limit*4，避免丢单）。
    """
    from app.payments import (
        multi_period_booking_ids,
        parse_catch_up_ids,
        payment_is_payoff,
        single_balance_booking_ids,
    )

    today = pacific_today()
    candidate_ids = set()
    if 'multi' in plan_kinds:
        candidate_ids |= multi_period_booking_ids()
    if 'deposit_balance' in plan_kinds:
        candidate_ids |= single_balance_booking_ids()
    if not candidate_ids:
        return [], today

    bookings_q = (
        Booking.query.options(
            joinedload(Booking.trip),
            joinedload(Booking.client),
            joinedload(Booking.discount_code),
        )
        .filter(Booking.id.in_(candidate_ids))
        .order_by(Booking.created_at.desc())
    )
    # 先多取一些再按 search 过滤，避免搜索时结果过少
    fetch_cap = max(limit * 5, limit)
    bookings = bookings_q.limit(fetch_cap).all()
    if search:
        bookings = [b for b in bookings if _matches_search(b, search)]
    bookings = bookings[:limit]
    booking_ids = [b.id for b in bookings]
    if not booking_ids:
        return [], today

    booking_by_id = {b.id: b for b in bookings}

    all_installments = (
        InstallmentPayment.query.filter(InstallmentPayment.booking_id.in_(booking_ids))
        .order_by(InstallmentPayment.booking_id, InstallmentPayment.installment_number)
        .all()
    )

    booking_payoff_payments = {}
    for payment in Payment.query.filter(
        Payment.booking_id.in_(booking_ids),
        Payment.status.in_(('succeeded', 'partially_refunded', 'refunded')),
    ).all():
        if payment_is_payoff(payment):
            booking_payoff_payments.setdefault(payment.booking_id, []).append(payment)

    grouped = defaultdict(lambda: {'deposit': None, 'others': [], 'payoff_payment': None})
    for installment in all_installments:
        booking_id = installment.booking_id
        if installment.installment_number == 0:
            grouped[booking_id]['deposit'] = installment
        elif installment.installment_number and installment.installment_number > 0:
            grouped[booking_id]['others'].append(installment)

    for booking_id, payoff_list in booking_payoff_payments.items():
        if booking_id in grouped and payoff_list:
            grouped[booking_id]['payoff_payment'] = max(
                payoff_list, key=lambda p: p.created_at or datetime.min
            )

    installment_ids = [inst.id for inst in all_installments]
    payments_map = {}
    if installment_ids:
        for payment in Payment.query.filter(
            Payment.installment_payment_id.in_(installment_ids)
        ).all():
            payments_map.setdefault(payment.installment_payment_id, []).append(payment)

    # Catch-up：被覆盖的非锚定期不再启发式错挂 Payment；仅标记 covered
    covered_ids = set()
    if booking_ids:
        for payment in Payment.query.filter(
            Payment.booking_id.in_(booking_ids),
            Payment.status.in_(('succeeded', 'partially_refunded', 'refunded')),
        ).all():
            meta = dict(payment.payment_metadata or {})
            catch_ids = parse_catch_up_ids(meta)
            if len(catch_ids) < 2:
                continue
            anchor = getattr(payment, 'installment_payment_id', None)
            for cid in catch_ids:
                if anchor is None or cid != anchor:
                    covered_ids.add(cid)

    from app.payments import booking_payments_plan_kind

    result = []
    for booking_id in booking_ids:
        raw = grouped.get(booking_id)
        if not raw:
            continue
        deposit = raw['deposit']
        booking = booking_by_id.get(booking_id) or (deposit.booking if deposit else None)
        if not deposit or not booking:
            continue

        kind = booking_payments_plan_kind(booking_id)
        if kind not in plan_kinds:
            continue

        raw_others = list(raw['others'] or [])
        others = list(raw_others)
        if raw['payoff_payment']:
            payoff_payment = raw['payoff_payment']
            payoff_date = payoff_payment.created_at.date() if payoff_payment.created_at else None
            filtered = []
            for inst in others:
                has_payment = bool(payments_map.get(inst.id))
                if has_payment or inst.status in ('pending', 'overdue'):
                    filtered.append(inst)
                elif inst.status == 'paid':
                    if inst.paid_at and payoff_date:
                        inst_paid_date = (
                            inst.paid_at.date()
                            if isinstance(inst.paid_at, datetime)
                            else inst.paid_at
                        )
                        if inst_paid_date >= payoff_date:
                            continue
                    filtered.append(inst)
                else:
                    filtered.append(inst)
            others = filtered

        others = sorted(others, key=lambda x: x.installment_number)
        result.append({
            'plan_kind': kind,
            'booking': booking,
            'booking_id': booking_id,
            'deposit': deposit,
            'others': others,
            'payoff_payment': raw['payoff_payment'],
            'post_deposit_count': len(raw_others),
            'is_multi_period': kind == 'multi',
            'has_unpaid': False,
            'next_action_installment': None,
            'primary_payment': None,
            'discount': booking_discount_info(booking),
        })

    # 先挂 Payment / 校正展示态，再按 status 筛选
    _attach_payments_and_sub_items(result, payments_map, covered_ids=covered_ids)
    if status_filter:
        result = [g for g in result if _filter_by_schedule_status(g, status_filter)]
    result.sort(
        key=lambda g: g['deposit'].created_at if g['deposit'].created_at else datetime.min,
        reverse=True,
    )
    return result[:limit], today


def build_one_time_order_groups(*, search='', status_filter='', limit=100, exclude_booking_ids=None):
    """一次付全款等：无定金后分期的 order，以 booking 为行。"""
    exclude_booking_ids = set(exclude_booking_ids or ())
    today = pacific_today()

    # 有成功/进行中收款、且不在分期计划集合中的 booking
    pay_q = (
        Payment.query.options(
            joinedload(Payment.booking).joinedload(Booking.trip),
            joinedload(Payment.booking).joinedload(Booking.discount_code),
            joinedload(Payment.client),
            joinedload(Payment.trip),
        )
        .filter(Payment.booking_id.isnot(None))
        .order_by(Payment.created_at.desc())
    )
    if status_filter in ('pending', 'failed', 'refunded', 'partially_refunded', 'succeeded'):
        pay_q = pay_q.filter(Payment.status == status_filter)
    elif status_filter == 'paid':
        pay_q = pay_q.filter(Payment.status == 'succeeded')

    payments = pay_q.limit(limit * 3).all()
    by_booking = {}
    for payment in payments:
        bid = payment.booking_id
        if not bid or bid in exclude_booking_ids:
            continue
        booking = payment.booking
        if not booking or not _matches_search(booking, search):
            continue
        # 只收尚无「定金后分期」的订单
        from app.payments import booking_payments_plan_kind
        if booking_payments_plan_kind(bid) != 'one_time':
            continue
        if bid not in by_booking:
            by_booking[bid] = {
                'plan_kind': 'one_time',
                'booking': booking,
                'booking_id': bid,
                'deposit': None,
                'others': [],
                'payoff_payment': None,
                'post_deposit_count': 0,
                'is_multi_period': False,
                'has_unpaid': payment.status == 'pending',
                'next_action_installment': None,
                'primary_payment': payment,
                'deposit_payment': payment,
                'others_payments': {},
                'sub_items': [],
                'discount': booking_discount_info(booking),
            }
        # 保留最新一笔作为主展示；若有 pending 优先
        cur = by_booking[bid]['primary_payment']
        if payment.status == 'pending' and cur.status != 'pending':
            by_booking[bid]['primary_payment'] = payment
            by_booking[bid]['deposit_payment'] = payment
            by_booking[bid]['has_unpaid'] = True
        elif payment.status == 'succeeded' and cur.status not in ('succeeded', 'pending'):
            by_booking[bid]['primary_payment'] = payment
            by_booking[bid]['deposit_payment'] = payment

    if status_filter == 'overdue':
        # one-time 无分期 overdue 概念
        return [], today

    result = list(by_booking.values())
    result.sort(
        key=lambda g: (
            g['primary_payment'].created_at
            if g.get('primary_payment') and g['primary_payment'].created_at
            else datetime.min
        ),
        reverse=True,
    )
    return result[:limit], today
