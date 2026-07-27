"""Booking form field validation (shared by API create / free booking path)."""

from __future__ import annotations

import re
from datetime import date, datetime

EMAIL_RE = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.I)
# Digits only count 7–15; allow + spaces ( ) -
PHONE_ALLOWED_RE = re.compile(r"^[\d\s+\-().]+$")
NAME_RE = re.compile(
    r"^[\w\s\-'\u00B7\u00C0-\u024F\u0400-\u04FF\u4E00-\u9FFF\u3040-\u30FF\uAC00-\uD7AF.]{1,64}$",
    re.UNICODE,
)
ZIP_RE = re.compile(r"^[A-Z0-9\s\-]{3,12}$", re.I)
DOB_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_email(value, *, required=False) -> str | None:
    if is_blank(value):
        return "Email is required." if required else None
    if not EMAIL_RE.fullmatch(str(value).strip()):
        return "Please enter a valid email address."
    return None


def validate_phone(value, *, required=False) -> str | None:
    if is_blank(value):
        return "Phone number is required." if required else None
    s = str(value).strip()
    if not PHONE_ALLOWED_RE.fullmatch(s):
        return "Please enter a valid phone number."
    digits = re.sub(r"\D", "", s)
    if len(digits) < 7 or len(digits) > 15:
        return "Please enter a valid phone number."
    return None


def validate_name(value, *, required=False) -> str | None:
    if is_blank(value):
        return "Name is required." if required else None
    s = str(value).strip()
    if len(s) < 1 or len(s) > 64:
        return "Please enter a valid name."
    if not NAME_RE.fullmatch(s):
        return "Please enter a valid name."
    return None


def validate_dob(value, *, required=False, today=None) -> str | None:
    if is_blank(value):
        return "Date of birth is required." if required else None
    s = str(value).strip()
    if not DOB_RE.fullmatch(s):
        return "Please enter a valid date of birth."
    try:
        dob = datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return "Please enter a valid date of birth."
    ref = today or date.today()
    if dob > ref:
        return "Please enter a valid date of birth."
    age_days = (ref - dob).days
    if age_days > 120 * 365 + 30:
        return "Please enter a valid date of birth."
    return None


def validate_zip(value, *, required=False) -> str | None:
    if is_blank(value):
        return "ZIP/postal code is required." if required else None
    s = str(value).strip()
    if not ZIP_RE.fullmatch(s):
        return "Please enter a valid ZIP/postal code."
    return None


def validate_buyer_info(buyer_info) -> list[str]:
    """Return list of error messages for buyer_info dict (empty = ok)."""
    buyer_info = buyer_info or {}
    errors = []

    for key, fn, required in (
        ("first_name", validate_name, True),
        ("last_name", validate_name, True),
        ("email", validate_email, True),
        ("phone", validate_phone, False),
        ("home_phone", validate_phone, False),
        ("work_phone", validate_phone, False),
        ("zip_code", validate_zip, False),
        ("emergency_contact_name", validate_name, False),
        ("emergency_contact_phone", validate_phone, False),
        ("emergency_contact_email", validate_email, False),
    ):
        msg = fn(buyer_info.get(key), required=required)
        if msg:
            label = key.replace("_", " ")
            errors.append(f"Buyer {label}: {msg}")

    return errors


def validate_participants(participants) -> list[str]:
    """Validate participants list; custom free-text questions are not regex-checked."""
    errors = []
    for idx, p in enumerate(participants or [], start=1):
        prefix = f"Participant {idx}"
        p = p or {}

        for key, fn, required in (
            ("first_name", validate_name, True),
            ("last_name", validate_name, True),
            ("email", validate_email, False),
            ("phone", validate_phone, False),
        ):
            msg = fn(p.get(key), required=required)
            if msg:
                errors.append(f"{prefix} {key.replace('_', ' ')}: {msg}")

        dob = p.get("dob") or p.get("date_of_birth")
        msg = validate_dob(dob, required=True)
        if msg:
            errors.append(f"{prefix} date of birth: {msg}")

        middle = p.get("middle_name")
        if not is_blank(middle):
            msg = validate_name(middle, required=False)
            if msg:
                errors.append(f"{prefix} middle name: {msg}")

        # Custom questions stored as dict question_id -> value, with types from trip config unavailable:
        # only validate values that look like email/phone when key metadata present in answer objects.
        custom = p.get("custom_answers") or p.get("answers") or p.get("questions") or {}
        if isinstance(custom, dict):
            for qid, val in custom.items():
                if isinstance(val, dict):
                    qtype = (val.get("type") or "").lower()
                    raw = val.get("value") or val.get("answer")
                    req = bool(val.get("required"))
                else:
                    continue
                if qtype == "email":
                    msg = validate_email(raw, required=req)
                elif qtype in ("phone", "tel"):
                    msg = validate_phone(raw, required=req)
                elif qtype in ("date", "dob"):
                    msg = validate_dob(raw, required=req)
                else:
                    msg = None
                if msg:
                    errors.append(f"{prefix} custom field: {msg}")
        elif isinstance(custom, list):
            for a in custom:
                if not isinstance(a, dict):
                    continue
                qtype = (a.get("type") or "").lower()
                raw = a.get("value") or a.get("answer")
                req = bool(a.get("required"))
                if qtype == "email":
                    msg = validate_email(raw, required=req)
                elif qtype in ("phone", "tel"):
                    msg = validate_phone(raw, required=req)
                elif qtype in ("date", "dob"):
                    msg = validate_dob(raw, required=req)
                else:
                    msg = None
                if msg:
                    errors.append(f"{prefix} custom field: {msg}")

    return errors


def validate_booking_payload(buyer_info, participants) -> list[str]:
    """Full payload check used by handle_booking_submission."""
    return validate_buyer_info(buyer_info) + validate_participants(participants)
