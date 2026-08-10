"""
行程老师只读名单（Teacher View）
- Trip.teacher_view_slug：可自定义短码（Basics 可编辑）；改码即旧链失效
- build_teacher_roster_context：组装 Bookings / Participants 只读数据（无财务合计、无写操作）
"""

from __future__ import annotations

import re
import secrets

from sqlalchemy.orm import joinedload

from app.models import Booking, Trip
from app.payments import (
    booking_addon_unit_price,
    booking_ids_with_payoff,
    booking_payment_display_status,
    booking_payment_type_display,
)


TEACHER_VIEW_SLUG_BYTES = 16  # token_urlsafe → ~22 chars
_TEACHER_SLUG_SAFE = re.compile(r'[^A-Za-z0-9_-]+')


def generate_teacher_view_slug():
    """生成不可猜的老师分享码（URL 安全）。"""
    return secrets.token_urlsafe(TEACHER_VIEW_SLUG_BYTES)


def normalize_teacher_view_slug(raw):
    """清洗用户输入：字母数字、连字符、下划线；最长 64。"""
    s = (raw or '').strip()
    s = _TEACHER_SLUG_SAFE.sub('-', s)
    s = s.strip('-_')[:64]
    return s


def ensure_teacher_view_slug(trip):
    """若尚未生成则写入新码（不 commit）；返回当前 slug。"""
    if trip is None:
        return None
    current = (getattr(trip, 'teacher_view_slug', None) or '').strip()
    if current:
        return current
    slug = _unique_teacher_view_slug()
    trip.teacher_view_slug = slug
    return slug


def apply_teacher_view_slug(trip, raw):
    """
    应用 Basics 输入的 teacher view slug（不 commit）。
    空输入 → 保留已有或惰性生成。
    冲突 → ValueError。
    """
    cleaned = normalize_teacher_view_slug(raw)
    if not cleaned:
        return ensure_teacher_view_slug(trip)
    existing = (
        Trip.query.filter(
            Trip.teacher_view_slug == cleaned,
            Trip.id != getattr(trip, 'id', None),
        ).first()
    )
    if existing:
        raise ValueError('That teacher view slug is already in use by another trip.')
    trip.teacher_view_slug = cleaned
    return cleaned


def reset_teacher_view_slug(trip):
    """换新码（旧链接立即失效）；不 commit；返回新 slug。"""
    slug = _unique_teacher_view_slug(exclude_trip_id=getattr(trip, 'id', None))
    trip.teacher_view_slug = slug
    return slug


def _unique_teacher_view_slug(exclude_trip_id=None, attempts=8):
    for _ in range(attempts):
        candidate = generate_teacher_view_slug()
        q = Trip.query.filter_by(teacher_view_slug=candidate)
        if exclude_trip_id is not None:
            q = q.filter(Trip.id != exclude_trip_id)
        if q.first() is None:
            return candidate
    # 极端碰撞：加长
    return secrets.token_urlsafe(TEACHER_VIEW_SLUG_BYTES + 8)


def build_booking_addons_summary(bookings):
    """与 Manage 页一致的订单级 add-ons 汇总。"""
    booking_addons_summary = {}
    for booking in bookings:
        addons_map = {}
        participant_ids = [p.id for p in booking.participants]
        for participant in booking.participants:
            for booking_addon in participant.addons:
                if booking_addon.addon:
                    addon_name = booking_addon.addon.name
                    addons_map[addon_name] = addons_map.get(addon_name, 0) + booking_addon.quantity
        for booking_addon in booking.addons:
            if booking_addon.addon and (
                booking_addon.participant_id is None
                or booking_addon.participant_id not in participant_ids
            ):
                addon_name = booking_addon.addon.name
                addons_map[addon_name] = addons_map.get(addon_name, 0) + booking_addon.quantity
        booking_addons_summary[booking.id] = addons_map
    return booking_addons_summary


def build_participants_roster(bookings):
    """Participants Tab 花名册行（与 manage_trip 字段对齐）。"""
    all_participants = []
    for booking in bookings:
        for participant in booking.participants:
            participant_addons = []
            seen_addon_ids = set()
            for booking_addon in participant.addons:
                if booking_addon.addon and booking_addon.id not in seen_addon_ids:
                    participant_addons.append({
                        'name': booking_addon.addon.name,
                        'quantity': booking_addon.quantity,
                        'price': booking_addon_unit_price(booking_addon),
                    })
                    seen_addon_ids.add(booking_addon.id)
            for booking_addon in booking.addons:
                if (
                    booking_addon.addon
                    and booking_addon.participant_id == participant.id
                    and booking_addon.id not in seen_addon_ids
                ):
                    participant_addons.append({
                        'name': booking_addon.addon.name,
                        'quantity': booking_addon.quantity,
                        'price': booking_addon_unit_price(booking_addon),
                    })
                    seen_addon_ids.add(booking_addon.id)

            first_name = (getattr(participant, 'first_name', None) or '').strip()
            last_name = (getattr(participant, 'last_name', None) or '').strip()
            if not first_name and not last_name:
                name_parts = (participant.name or '').strip().split(None, 1)
                first_name = name_parts[0] if name_parts else ''
                last_name = name_parts[1] if len(name_parts) > 1 else ''

            buyer_name = (booking.buyer_name or '').strip()
            if not buyer_name and booking.client:
                buyer_name = (booking.client.name or '').strip()
            buyer_email = (booking.get_buyer_email() or '').strip()

            all_participants.append({
                'id': participant.id,
                'name': participant.name,
                'first_name': first_name,
                'last_name': last_name,
                'email': participant.email,
                'phone': participant.phone,
                'gender': getattr(participant, 'gender', None) or '',
                'dob': participant.dob.strftime('%Y-%m-%d') if getattr(participant, 'dob', None) else '',
                'registration_type': getattr(participant, 'registration_type', None) or '',
                'booking_id': booking.id,
                'order_number': booking.order_number or f'#{booking.id}',
                'buyer_name': buyer_name,
                'buyer_email': buyer_email,
                'addons': participant_addons,
                'question_answers': participant.question_answers or {},
            })
    return all_participants


def load_trip_bookings(trip):
    return (
        Booking.query.filter_by(trip_id=trip.id)
        .options(joinedload(Booking.client))
        .order_by(Booking.created_at.asc())
        .all()
    )


def build_teacher_roster_context(trip):
    """
    老师只读页模板上下文。
    含付款状态标签，不含金额财务栏 / Messages / 写操作数据。
    """
    bookings = load_trip_bookings(trip)
    booking_addons_summary = build_booking_addons_summary(bookings)
    booking_payment_statuses = {
        b.id: booking_payment_display_status(b) for b in bookings
    }
    booking_payment_types = {
        b.id: booking_payment_type_display(b) for b in bookings
    }
    booking_payoff_ids = booking_ids_with_payoff([b.id for b in bookings])
    all_participants = build_participants_roster(bookings)
    custom_questions = trip.questions.all() if trip.questions else []

    return {
        'trip': trip,
        'bookings': bookings,
        'booking_addons_summary': booking_addons_summary,
        'booking_payment_statuses': booking_payment_statuses,
        'booking_payment_types': booking_payment_types,
        'booking_payoff_ids': booking_payoff_ids,
        'all_participants': all_participants,
        'total_participants_count': len(all_participants),
        'custom_questions': custom_questions,
        'title': f'{trip.title} — Roster',
    }
