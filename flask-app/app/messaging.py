"""
Trip Messages（Manage → New Message）共用逻辑：买家收件人、发信、定时发送。
"""
from datetime import date, datetime, timedelta
from email.utils import formataddr

from flask import current_app

from app import db
from app.models import InstallmentPayment, Message
from app.payments import booking_package_unit_price, booking_addon_unit_price
from app.utils import (
    is_noreply_sender,
    render_branded_customer_message,
    send_email_via_ses,
)


ALLOWED_RECIPIENT_TYPES = frozenset({
    'all',
    'specific',
    'custom',
    'package',
    'payment_due',
    'balance_due',
    'incomplete_questions',
    'missing_signatures',
})


def forced_reply_to_email():
    """
    Messages 群发 Reply-To：固定工作邮箱。
    只用 REPLY_TO_EMAIL（默认 info@），不回落到 RECIPIENT_EMAIL/SENDER_EMAIL
    （本地后两者常是个人 Gmail，仅用于 SES 实测）。
    """
    return (
        (current_app.config.get('REPLY_TO_EMAIL') or '').strip()
        or 'info@nhtours.com'
    )


def booking_expected_amount(booking):
    """应付金额：套餐+附加−折扣（与 Manage / Excel 一致）。"""
    booking_gross = 0.0
    has_packages = False
    seen_addon_ids = set()
    for bp in booking.booking_packages:
        if bp.package:
            package_price = booking_package_unit_price(bp)
            quantity = int(bp.quantity) if bp.quantity is not None else 1
            booking_gross += package_price * quantity
            has_packages = True
    for participant in booking.participants:
        for booking_addon in participant.addons:
            if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                addon_price = booking_addon_unit_price(booking_addon)
                quantity = int(booking_addon.quantity) if booking_addon.quantity is not None else 0
                booking_gross += addon_price * quantity
                seen_addon_ids.add(booking_addon.id)
    for booking_addon in booking.addons:
        if booking_addon.addon and booking_addon.id not in seen_addon_ids:
            addon_price = booking_addon_unit_price(booking_addon)
            quantity = int(booking_addon.quantity) if booking_addon.quantity is not None else 0
            booking_gross += addon_price * quantity
            seen_addon_ids.add(booking_addon.id)
    discount = float(booking.discount_amount) if booking.discount_amount else 0.0
    if not has_packages:
        return round(float(booking.amount_paid) if booking.amount_paid is not None else 0.0, 2)
    return round(max(0.0, booking_gross - discount), 2)


def booking_balance_due(booking):
    """剩余未付；cancelled 返回 None。退款不计入欠款。"""
    from app.payments import booking_balance_due as _payments_balance_due
    return _payments_balance_due(booking, expected=booking_expected_amount(booking))


def _buyer_recipient(booking):
    email = (booking.get_buyer_email() or '').strip()
    if not email:
        return None
    name = (booking.buyer_name or '').strip() or 'Guest'
    return {'email': email, 'name': name, 'booking_id': booking.id}


def _dedupe_by_email(recipients):
    seen = set()
    unique = []
    for recipient in recipients:
        email = (recipient.get('email') or '').strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        unique.append({
            'email': recipient['email'].strip(),
            'name': recipient.get('name') or 'Guest',
        })
    return unique


def collect_message_buyers(trip):
    """非 cancelled 且有买家邮箱的 booking contacts（供 UI Specific / 人数）。"""
    buyers = []
    for booking in trip.bookings:
        if booking.status == 'cancelled':
            continue
        recipient = _buyer_recipient(booking)
        if recipient:
            buyers.append(recipient)
    return _dedupe_by_email(buyers)


def _booking_has_overdue_installment(booking):
    from app.utils import pacific_today

    today = pacific_today()
    for inst in InstallmentPayment.query.filter_by(booking_id=booking.id).all():
        if inst.status in ('cancelled', 'paid'):
            continue
        if inst.status == 'overdue':
            return True
        if inst.due_date and inst.due_date < today and inst.status == 'pending':
            return True
    return False


def _booking_matches_package_filter(booking, package_id=None, addon_id=None):
    if package_id:
        try:
            package_id = int(package_id)
        except (TypeError, ValueError):
            return False
        has_pkg = any(bp.package_id == package_id for bp in booking.booking_packages)
        if not has_pkg:
            return False
    if addon_id:
        try:
            addon_id = int(addon_id)
        except (TypeError, ValueError):
            return False
        seen = set()
        for participant in booking.participants:
            for ba in participant.addons:
                if ba.addon_id == addon_id:
                    return True
                seen.add(ba.id)
        for ba in booking.addons:
            if ba.addon_id == addon_id:
                return True
        return False
    return True if package_id else False


def _answer_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _booking_has_incomplete_required_questions(booking, trip):
    required = [q for q in trip.questions.all() if q.required]
    if not required:
        return False
    participants = list(booking.participants)
    if not participants:
        return True
    for participant in participants:
        answers = participant.question_answers or {}
        if not isinstance(answers, dict):
            return True
        for q in required:
            # answers 可能用 str(id) 或 id
            val = answers.get(str(q.id), answers.get(q.id))
            if _answer_empty(val):
                return True
    return False


def _booking_missing_signatures(booking):
    """
    签名尚未独立字段：仅当 question_answers 含 signature/waiver 类键且为空时匹配。
    无此类字段时不匹配（避免误发）。
    """
    found_field = False
    found_empty = False
    for participant in booking.participants:
        answers = participant.question_answers or {}
        if not isinstance(answers, dict):
            continue
        for key, val in answers.items():
            key_l = str(key).lower()
            if 'sign' in key_l or 'waiver' in key_l:
                found_field = True
                if _answer_empty(val):
                    found_empty = True
    return found_field and found_empty


def parse_typed_emails(text_or_list):
    """
    从键入文本或列表解析邮箱。
    支持逗号/分号/换行分隔；可选 Name <email@x.com>。
    """
    import re
    email_re = re.compile(r'[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}', re.I)

    if isinstance(text_or_list, list):
        # 已结构化的 recipients
        if text_or_list and all(isinstance(x, dict) for x in text_or_list):
            out = []
            seen = set()
            for item in text_or_list:
                email = (item.get('email') or '').strip()
                if not email or not email_re.fullmatch(email):
                    continue
                key = email.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    'email': email,
                    'name': (item.get('name') or 'Guest').strip() or 'Guest',
                })
            return out
        raw = '\n'.join(str(x or '') for x in text_or_list)
    else:
        raw = text_or_list or ''

    recipients = []
    seen = set()
    for part in re.split(r'[\n,;]+', raw):
        part = part.strip()
        if not part:
            continue
        m = re.match(r'^(.+?)\s*<([^>]+)>$', part)
        if m:
            name = m.group(1).strip().strip('"\'') or 'Guest'
            email = m.group(2).strip()
        else:
            found = email_re.search(part)
            if not found:
                continue
            email = found.group(0)
            name = part[: found.start()].strip().strip('"\'') or 'Guest'
        email_l = email.lower()
        if email_l in seen:
            continue
        if not email_re.fullmatch(email):
            continue
        seen.add(email_l)
        recipients.append({'email': email, 'name': name})
    return recipients


def get_recipients_for_trip(trip, recipient_config):
    """根据配置返回买家收件人列表（按邮箱去重）。"""
    recipient_config = recipient_config or {}
    recipient_type = recipient_config.get('type') or 'all'
    recipients = []

    if recipient_type == 'custom':
        # 优先用键入原文；否则用 recipients 列表
        if recipient_config.get('emails_text'):
            return parse_typed_emails(recipient_config.get('emails_text'))
        return parse_typed_emails(recipient_config.get('recipients') or [])

    if recipient_type == 'specific':
        raw = recipient_config.get('recipients') or []
        for item in raw:
            if isinstance(item, dict):
                email = (item.get('email') or '').strip()
                if email:
                    recipients.append({
                        'email': email,
                        'name': (item.get('name') or 'Guest').strip() or 'Guest',
                    })
            elif isinstance(item, str) and item.strip():
                recipients.append({'email': item.strip(), 'name': 'Guest'})
        return _dedupe_by_email(recipients)

    package_id = recipient_config.get('package_id')
    addon_id = recipient_config.get('addon_id')

    for booking in trip.bookings:
        if booking.status == 'cancelled':
            continue

        if recipient_type in ('balance_due', 'payment_due'):
            bal = booking_balance_due(booking)
            past_due = _booking_has_overdue_installment(booking)
            if not past_due and (bal is None or bal <= 0):
                continue
        elif recipient_type == 'package':
            if not _booking_matches_package_filter(booking, package_id, addon_id):
                continue
        elif recipient_type == 'incomplete_questions':
            if not _booking_has_incomplete_required_questions(booking, trip):
                continue
        elif recipient_type == 'missing_signatures':
            if not _booking_missing_signatures(booking):
                continue
        elif recipient_type != 'all':
            continue

        recipient = _buyer_recipient(booking)
        if recipient:
            recipients.append(recipient)

    return _dedupe_by_email(recipients)


def recipient_counts_for_trip(trip):
    """供 Manage UI 显示各筛选项人数。"""
    buyers = collect_message_buyers(trip)
    payment_due = get_recipients_for_trip(trip, {'type': 'payment_due'})
    incomplete = get_recipients_for_trip(trip, {'type': 'incomplete_questions'})
    missing_sig = get_recipients_for_trip(trip, {'type': 'missing_signatures'})

    package_counts = {}
    for pkg in trip.packages.all():
        package_counts[str(pkg.id)] = len(
            get_recipients_for_trip(trip, {'type': 'package', 'package_id': pkg.id})
        )
    addon_counts = {}
    for addon in trip.add_ons.all():
        addon_counts[str(addon.id)] = len(
            get_recipients_for_trip(trip, {'type': 'package', 'addon_id': addon.id})
        )

    return {
        'all': len(buyers),
        'payment_due': len(payment_due),
        'balance_due': len(payment_due),
        'incomplete_questions': len(incomplete),
        'missing_signatures': len(missing_sig),
        'packages': package_counts,
        'addons': addon_counts,
    }


def send_message_emails(message, recipients):
    """
    向收件人列表发 SES 邮件。
    From = Sender name <SENDER_EMAIL>；Reply-To = REPLY_TO_EMAIL（个人邮箱发信时由 utils 自动对齐）。
    返回 (sent_count, failed_count)。
    """
    reply_to = forced_reply_to_email()
    message.reply_to_email = reply_to
    from_email = current_app.config.get('SENDER_EMAIL') or reply_to
    from_header = formataddr((message.sender_name or 'Nexus Horizons Tours', from_email))
    text_body = message.body_text or ''
    trip_title = (message.trip.title if message.trip else '') or 'Nexus Horizons Tours'
    contact = (current_app.config.get('REPLY_TO_EMAIL') or 'info@nhtours.com').strip()
    if is_noreply_sender(contact):
        contact = 'info@nhtours.com'
    html_body = render_branded_customer_message(
        subject_line=message.subject or trip_title,
        brand_subtitle=trip_title,
        message_html=message.body_html or '',
        show_default_signoff=False,
        contact_email=contact,
    )
    if text_body.strip():
        text_body = (
            f"{text_body.rstrip()}\n\n"
            f"--\nQuestions? Please email us at {contact} (this message was sent from a no-reply address).\n"
        )

    sent_count = 0
    failed_count = 0
    errors = []
    for recipient in recipients:
        success, detail = send_email_via_ses(
            sender=from_header,
            recipient=recipient['email'],
            subject=message.subject,
            html_body=html_body,
            text_body=text_body,
            reply_to=reply_to,
        )
        if success:
            sent_count += 1
        else:
            failed_count += 1
            errors.append(f"{recipient['email']}: {detail}")
    if errors:
        current_app.logger.error('Message send failures: ' + '; '.join(errors))
    return sent_count, failed_count


def deliver_message(message, recipients=None):
    """解析收件人（若未传入）、发信并更新 message 统计为 sent。"""
    trip = message.trip
    if recipients is None:
        recipients = get_recipients_for_trip(trip, message.recipient_config or {})
    message.total_recipients = len(recipients)
    sent_count, failed_count = send_message_emails(message, recipients)
    message.sent_at = datetime.utcnow()
    message.sent_count = sent_count
    message.failed_count = failed_count
    message.status = 'sent'
    message.scheduled_at = None
    return sent_count, failed_count


def recipient_type_label(recipient_config):
    cfg = recipient_config or {}
    t = cfg.get('type') or 'all'
    labels = {
        'all': 'Everyone on this trip',
        'payment_due': 'Payments past due / balance due',
        'balance_due': 'Balance due',
        'incomplete_questions': 'Incomplete required questions',
        'missing_signatures': 'Missing signatures',
        'package': 'Specific package or add-on',
        'specific': 'Specific booking contacts',
        'custom': 'Entered email addresses',
    }
    return labels.get(t, t)


def message_to_dict(message, include_recipients=False):
    data = {
        'id': message.id,
        'trip_id': message.trip_id,
        'sender_name': message.sender_name,
        'reply_to_email': message.reply_to_email,
        'subject': message.subject or '',
        'body_html': message.body_html or '',
        'body_text': message.body_text or '',
        'recipient_config': message.recipient_config or {},
        'send_to_label': recipient_type_label(message.recipient_config),
        'status': message.status,
        'scheduled_at': message.scheduled_at.strftime('%Y-%m-%dT%H:%M') if message.scheduled_at else '',
        'scheduled_at_display': (
            message.scheduled_at.strftime('%Y-%m-%d %H:%M') if message.scheduled_at else ''
        ),
        'total_recipients': message.total_recipients or 0,
        'sent_count': message.sent_count or 0,
        'failed_count': message.failed_count or 0,
        'sent_at': message.sent_at.isoformat() if message.sent_at else None,
        'sent_at_display': (
            message.sent_at.strftime('%Y-%m-%d %H:%M') if message.sent_at else ''
        ),
        'created_at': message.created_at.isoformat() if message.created_at else None,
        'updated_at': message.updated_at.isoformat() if message.updated_at else None,
    }
    if include_recipients and message.trip:
        try:
            data['recipients'] = get_recipients_for_trip(
                message.trip, message.recipient_config or {}
            )
        except Exception:
            data['recipients'] = []
    return data


def send_due_scheduled_messages():
    """
    扫描到期 scheduled 消息并发送。
    先把 status 改为 sending，降低多 worker 双发概率。
    """
    now = datetime.utcnow()
    stuck_before = now - timedelta(minutes=10)
    Message.query.filter(
        Message.status == 'sending',
        Message.updated_at < stuck_before,
    ).update({'status': 'scheduled', 'updated_at': now}, synchronize_session=False)
    db.session.commit()

    due = (
        Message.query.filter(
            Message.status == 'scheduled',
            Message.scheduled_at.isnot(None),
            Message.scheduled_at <= now,
        )
        .order_by(Message.scheduled_at.asc())
        .all()
    )
    if not due:
        return 0

    processed = 0
    for message in due:
        claimed = (
            Message.query.filter_by(id=message.id, status='scheduled')
            .update({'status': 'sending', 'updated_at': now}, synchronize_session=False)
        )
        db.session.commit()
        if not claimed:
            continue

        message = Message.query.get(message.id)
        if not message:
            continue
        try:
            deliver_message(message)
            db.session.commit()
            processed += 1
            current_app.logger.info(
                f"Scheduled message {message.id} sent: "
                f"ok={message.sent_count} fail={message.failed_count}"
            )
        except Exception as e:
            db.session.rollback()
            try:
                message = Message.query.get(message.id)
                if message and message.status == 'sending':
                    message.status = 'scheduled'
                    db.session.commit()
            except Exception:
                db.session.rollback()
            current_app.logger.error(
                f"Scheduled message {message.id if message else '?'} failed: {e}",
                exc_info=True,
            )
    return processed
