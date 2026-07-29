"""Generate booking receipt PDF for download (2 pages: Summary + History)."""

from io import BytesIO
from pathlib import Path

from fpdf import FPDF

_EMAIL_LOGO_NAME = "nexus-horizons-email.png"
_HEADER_LOGO_NAME = "nexus-horizons-receipt-header.png"


def _resolve_logo_path(filename=_EMAIL_LOGO_NAME):
    """Find brand logo whether receipt_pdf is loaded from app/ or a temp path."""
    here = Path(__file__).resolve().parent
    candidates = [
        here / "static" / "images" / "icons" / filename,
        here.parent / "app" / "static" / "images" / "icons" / filename,
        Path("/var/www/nhtours/flask-app/app/static/images/icons") / filename,
    ]
    for parent in here.parents:
        candidates.append(parent / "static" / "images" / "icons" / filename)
        candidates.append(parent / "app" / "static" / "images" / "icons" / filename)
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _money(value):
    try:
        return f"${float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _safe(text):
    """FPDF core fonts are Latin-1; map common Unicode punctuation, drop the rest."""
    if text is None:
        return ""
    s = str(text)
    for src, dst in (
        ("\u2014", "-"),  # em dash
        ("\u2013", "-"),  # en dash
        ("\u00b7", "-"),  # middle dot
        ("\u2022", "-"),
        ("\u2018", "'"),
        ("\u2019", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u00a0", " "),
    ):
        s = s.replace(src, dst)
    try:
        s.encode("latin-1")
        return s
    except UnicodeEncodeError:
        return s.encode("latin-1", errors="replace").decode("latin-1")


def _fmt_date(value):
    if not value:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%b %d, %Y")
    return str(value)[:10]


def _logo_rgb_bytes(logo_path, max_height_px=None):
    """Flatten RGBA logo onto white (transparent PNGs can look blank in some viewers)."""
    path = Path(logo_path)
    if not path.is_file():
        return None, 1.0  # bytes, aspect w/h
    try:
        from PIL import Image

        im = Image.open(path).convert("RGBA")
        if max_height_px and im.size[1] > max_height_px:
            ratio = max_height_px / float(im.size[1])
            im = im.resize(
                (max(1, int(im.size[0] * ratio)), max_height_px),
                Image.Resampling.LANCZOS,
            )
        aspect = im.size[0] / float(im.size[1]) if im.size[1] else 1.0
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))
        composed = Image.alpha_composite(bg, im).convert("RGB")
        buf = BytesIO()
        composed.save(buf, format="PNG")
        return buf.getvalue(), aspect
    except Exception:
        try:
            return path.read_bytes(), 1.0
        except OSError:
            return None, 1.0


class ReceiptPDF(FPDF):
    """Letter receipt: header lockup + legacy footer logo on every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._order_label = ""
        self._page_subtitle = "Booking Receipt"
        header_bytes, header_aspect = _logo_rgb_bytes(
            _resolve_logo_path(_HEADER_LOGO_NAME),
            max_height_px=220,
        )
        # Fallback to email logo if header asset missing
        if not header_bytes:
            header_bytes, header_aspect = _logo_rgb_bytes(_resolve_logo_path(_EMAIL_LOGO_NAME))
        footer_bytes, footer_aspect = _logo_rgb_bytes(_resolve_logo_path(_EMAIL_LOGO_NAME))
        self._header_logo_bytes = header_bytes
        self._header_logo_aspect = header_aspect or 1.0
        self._footer_logo_bytes = footer_bytes
        self._footer_logo_aspect = footer_aspect or (300 / 125)
        # Drawn above the footer rule on page 1 (Paid/Pending + due-at-booking notes)
        self._footer_notes = []

    def _draw_logo_bytes(self, data, aspect, x, y, w):
        if not data:
            return 0.0
        self.image(BytesIO(data), x=x, y=y, w=w)
        return w / aspect if aspect else w * 0.4

    def header(self):
        # Preferred size: logo ~17mm, title 18pt; bottom edges aligned
        logo_w = 17
        logo_h = 0.0
        logo_y = 10.0
        if self._header_logo_bytes:
            logo_h = self._draw_logo_bytes(
                self._header_logo_bytes,
                self._header_logo_aspect,
                self.l_margin,
                logo_y,
                logo_w,
            )

        title_h = 7.0
        sub_h = 5.0
        gap = 1.0
        text_block_h = title_h + gap + sub_h
        if logo_h > 0:
            # Align bottoms: NHTOURS baseline with "Booking Receipt - …"
            text_y = logo_y + logo_h - text_block_h
            text_x = self.l_margin + logo_w + 4
        else:
            text_y = 11.0
            text_x = self.l_margin

        self.set_xy(text_x, text_y)
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(17, 24, 39)
        self.cell(0, title_h, "Nexus Horizons Tours", new_x="LMARGIN", new_y="NEXT")
        self.set_xy(text_x, text_y + title_h + gap)
        self.set_font("Helvetica", size=11)
        self.set_text_color(75, 85, 99)
        self.cell(100, sub_h, _safe(self._page_subtitle))

        if self._order_label:
            # Two lines @ 4mm → match text/logo bottom edge
            order_line_h = 4.0
            order_block_h = order_line_h * 2
            order_y = (logo_y + logo_h - order_block_h) if logo_h > 0 else text_y
            self.set_xy(self.w - self.r_margin - 70, order_y)
            self.set_font("Helvetica", size=9)
            self.set_text_color(75, 85, 99)
            self.multi_cell(70, order_line_h, _safe(self._order_label), align="R")

        y = max(logo_y + logo_h + 3, text_y + text_block_h + 3, 30)
        self.set_draw_color(229, 231, 235)
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.set_y(y + 5)

    def footer(self):
        notes = list(getattr(self, "_footer_notes", None) or [])
        show_notes = bool(notes) and self.page_no() == 1
        brand_h = 44.0
        # Reserve space for italic notes above the rule (page 1 only)
        notes_h = 0.0
        if show_notes:
            # ~3.2mm/line; long due-at-booking note wraps ~3–4 lines
            notes_h = 3.0
            for note in notes:
                approx_lines = max(1, (len(note) // 95) + 1)
                notes_h += approx_lines * 3.2 + 1.5
            notes_h += 2.0

        self.set_y(-(brand_h + notes_h))

        if show_notes:
            self.set_font("Helvetica", "I", 7)
            self.set_text_color(107, 114, 128)
            usable = self.w - self.l_margin - self.r_margin
            for note in notes:
                self.set_x(self.l_margin)
                self.multi_cell(usable, 3.2, _safe(note))
                self.ln(1.2)
            self.ln(1.0)

        self.set_draw_color(229, 231, 235)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)
        # Keep original email/footer brand mark unchanged
        if self._footer_logo_bytes:
            logo_w = 34
            x = (self.w - logo_w) / 2
            self._draw_logo_bytes(
                self._footer_logo_bytes,
                self._footer_logo_aspect,
                x,
                self.get_y(),
                logo_w,
            )
            self.set_y(self.get_y() + 15)
        self.set_font("Helvetica", size=8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 4, "Thank you for choosing Nexus Horizons Tours!", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 4, "For inquiries, please contact us at info@nhtours.com", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 4, f"Page {self.page_no()}/{{nb}}", align="C")


def _section_title(pdf, title):
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(0, 7, _safe(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(55, 65, 81)


def _kv_row(pdf, label, value, bold_value=False):
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(55, 65, 81)
    pdf.cell(130, 6, _safe(label))
    pdf.set_font("Helvetica", "B" if bold_value else "", 10)
    pdf.cell(0, 6, _safe(str(value)), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)


def build_booking_receipt_pdf(ctx_or_booking=None, trip=None, expected_amount=None, **kwargs):
    """
    Build a PDF receipt for a booking (2 pages).

    Page 1 — Summary: trip, client, booking, participants, trip total
    Page 2 — History: payment history, installment schedule, refunds

    Prefer passing the shared `_booking_receipt_context` dict as the first argument.
    Returns:
        bytes: PDF file content
    """
    if isinstance(ctx_or_booking, dict):
        ctx = dict(ctx_or_booking)
        ctx.update(kwargs)
    else:
        ctx = dict(kwargs)
        if ctx_or_booking is not None:
            ctx["booking"] = ctx_or_booking
        if trip is not None:
            ctx["trip"] = trip
        if expected_amount is not None:
            ctx["expected_amount"] = expected_amount

    booking = ctx["booking"]
    trip = ctx.get("trip")
    expected_amount = ctx.get("expected_amount")
    participants_info = ctx.get("participants_info") or []
    discount_amount = ctx.get("discount_amount")
    if discount_amount is None:
        discount_amount = float(getattr(booking, "discount_amount", 0) or 0)
    discount_code = ctx.get("discount_code")
    if discount_code is None and getattr(booking, "discount_code", None):
        discount_code = getattr(booking.discount_code, "code", None)

    packages_subtotal = ctx.get("packages_subtotal")
    addons_total = ctx.get("addons_total")
    amount_paid_net = ctx.get("amount_paid_net")
    if amount_paid_net is None:
        amount_paid_net = float(booking.amount_paid or 0)
    amount_pending = ctx.get("amount_pending")
    if amount_pending is None:
        amount_pending = float(expected_amount or 0) - float(amount_paid_net or 0)
    due_at_booking_note = ctx.get("due_at_booking_note")
    payment_history = ctx.get("payment_history") or []
    installment_schedule = ctx.get("installment_schedule") or []
    refunds = ctx.get("refunds") or []

    amount_due_this_time = ctx.get("amount_due_this_time")
    if amount_due_this_time is None:
        if payment_history:
            amount_due_this_time = float(payment_history[0].get("base") or 0)
        else:
            amount_due_this_time = min(
                float(expected_amount or 0),
                max(0.0, float(ctx.get("due_at_booking") or 0)),
            )
    amount_due_this_time = float(amount_due_this_time)
    due_this_time_breakdown = (ctx.get("due_this_time_breakdown") or "").strip() or None

    if packages_subtotal is None:
        packages_subtotal = 0.0
        for bp in list(booking.booking_packages) if booking.booking_packages else []:
            if bp.package:
                packages_subtotal += float(bp.package.price or 0) * int(bp.quantity or 1)

    if addons_total is None:
        addons_total = 0.0
        seen = set()
        for participant in booking.participants:
            for booking_addon in participant.addons:
                if booking_addon.id in seen or not booking_addon.addon:
                    continue
                seen.add(booking_addon.id)
                addons_total += float(booking_addon.addon.price or 0) * int(booking_addon.quantity or 0)
        for booking_addon in booking.addons:
            if booking_addon.id in seen or not booking_addon.addon:
                continue
            seen.add(booking_addon.id)
            addons_total += float(booking_addon.addon.price or 0) * int(booking_addon.quantity or 0)

    order_no = getattr(booking, "order_number", None) or booking.id
    order_date = booking.created_at.strftime("%B %d, %Y") if booking.created_at else ""
    order_label = f"Order number: {order_no}\n{order_date}"

    pdf = ReceiptPDF(format="Letter")
    pdf.alias_nb_pages()
    # Page 1 footer is taller (notes above the rule)
    pdf.set_auto_page_break(auto=True, margin=72)
    pdf.set_margins(18, 40, 18)
    pdf._order_label = order_label

    # 仅一次付全款（无分期计划且付款≤1笔）→ 无 History；定金/分期或已付多笔 → 第 2 页
    show_history_page = bool(installment_schedule) or len(payment_history) > 1
    if ctx.get("show_history_page") is not None:
        show_history_page = bool(ctx.get("show_history_page"))

    footer_notes = [
        "Paid / Remaining are trip base amounts (package + add-ons - discount). "
        "Card processing fees are not included. Due this time is the amount required "
        "for the booking charge (after discount)."
        + (" Payment history is on page 2." if show_history_page else ""),
    ]
    if due_at_booking_note:
        footer_notes.append(due_at_booking_note)
    pdf._footer_notes = footer_notes

    # ── Page 1: Summary (or sole page) ───────────────────────────────
    pdf._page_subtitle = (
        "Booking Receipt - Summary" if show_history_page else "Booking Receipt"
    )
    pdf.add_page()

    # Trip
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(17, 24, 39)
    pdf.multi_cell(0, 7, _safe(trip.title if trip else "Trip"))
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(75, 85, 99)
    if trip and trip.start_date:
        end = trip.end_date.strftime("%B %d, %Y") if trip.end_date else "TBD"
        pdf.multi_cell(0, 6, f"Dates: {trip.start_date.strftime('%B %d, %Y')} - {end}")
        pdf.set_x(pdf.l_margin)
    if trip and getattr(trip, "destination_text", None):
        pdf.multi_cell(0, 6, f"Destination: {_safe(trip.destination_text)}")
        pdf.set_x(pdf.l_margin)
    pdf.ln(3)

    # Client
    _section_title(pdf, "Client Information")
    buyer_name = getattr(booking, "buyer_name", None) or ""
    buyer_email = booking.get_buyer_email() if hasattr(booking, "get_buyer_email") else (booking.buyer_email or "")
    buyer_phone = booking.get_buyer_phone() if hasattr(booking, "get_buyer_phone") else (booking.buyer_phone or "")
    for line in (buyer_name, buyer_email, buyer_phone):
        if line:
            pdf.cell(0, 5, _safe(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Booking details
    _section_title(pdf, "Booking Details")
    packages = list(booking.booking_packages) if booking.booking_packages else []
    if packages:
        for bp in packages:
            if not bp.package:
                continue
            qty = int(bp.quantity or 1)
            price = float(bp.package.price or 0) * qty
            _kv_row(pdf, f"{bp.package.name} x{qty}", _money(price))
    else:
        pdf.cell(0, 6, "No Package", new_x="LMARGIN", new_y="NEXT")

    _kv_row(pdf, "Passengers", str(booking.passenger_count or 0))
    status = (booking.status or "").replace("_", " ").title()
    _kv_row(pdf, "Status", status)
    pdf.ln(2)

    # Participants
    if participants_info:
        _section_title(pdf, "Participants")
        for participant in participants_info:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(17, 24, 39)
            pdf.cell(0, 6, _safe(participant.get("name") or "Participant"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
            pdf.set_text_color(55, 65, 81)
            if participant.get("email"):
                pdf.cell(0, 5, _safe(participant["email"]), new_x="LMARGIN", new_y="NEXT")
            for addon in participant.get("addons") or []:
                line = f"  - {addon.get('name')} x{addon.get('quantity')} - {_money(addon.get('total'))}"
                pdf.cell(0, 5, _safe(line), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
        pdf.ln(1)

    # Trip total
    _section_title(pdf, "Trip Total")
    if packages_subtotal:
        _kv_row(pdf, "Packages:", _money(packages_subtotal))
    if addons_total and float(addons_total) > 0:
        _kv_row(pdf, "Add-ons:", _money(addons_total))

    discount = float(discount_amount or 0)
    if discount > 0:
        pdf.set_text_color(16, 185, 129)
        code = f" ({discount_code})" if discount_code else ""
        pdf.set_font("Helvetica", size=10)
        pdf.cell(130, 6, _safe(f"Discount{code}:"))
        pdf.cell(0, 6, f"-{_money(discount)}", align="R", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(55, 65, 81)

    pdf.set_draw_color(209, 213, 219)
    pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.w - pdf.r_margin, pdf.get_y() + 1)
    pdf.ln(3)
    _kv_row(pdf, "Total Expected (base):", _money(expected_amount), bold_value=True)
    _kv_row(pdf, "Due this time (base):", _money(amount_due_this_time))
    if due_this_time_breakdown:
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(107, 114, 128)
        pdf.multi_cell(0, 4, _safe(due_this_time_breakdown))
        pdf.set_x(pdf.l_margin)
        pdf.set_text_color(55, 65, 81)
        pdf.ln(1)
    _kv_row(pdf, "Amount Paid (net base):", _money(amount_paid_net))
    _kv_row(pdf, "Amount Remaining (net base):", _money(amount_pending), bold_value=True)
    # Paid/Remaining notes → page 1 footer (above the rule)

    def _draw_installment_schedule():
        if not installment_schedule:
            return
        _section_title(pdf, "Installment Schedule")
        for row in installment_schedule:
            left = f"{row.get('label')}  -  due {_fmt_date(row.get('due_date'))}"
            right = f"{_money(row.get('amount'))}  -  {row.get('status_label') or row.get('status')}"
            pdf.set_font("Helvetica", size=9)
            pdf.set_text_color(55, 65, 81)
            pdf.cell(120, 6, _safe(left))
            pdf.cell(0, 6, _safe(right), align="R", new_x="LMARGIN", new_y="NEXT")
            if row.get("note"):
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(107, 114, 128)
                pdf.cell(0, 4, _safe(f"  {row['note']}"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", size=9)
                pdf.set_text_color(55, 65, 81)
        pdf.ln(2)

    def _draw_refunds():
        if not refunds:
            return
        _section_title(pdf, "Refunds (base)")
        for row in refunds:
            at = row.get("at") or ""
            if isinstance(at, str) and "T" in at:
                at = at[:10]
            reason = row.get("reason") or ""
            line = f"{at}  payment #{row.get('payment_id')}  {_money(row.get('amount'))}"
            if reason:
                line += f"  - {_safe(reason)[:70]}"
            pdf.set_font("Helvetica", size=9)
            pdf.set_text_color(55, 65, 81)
            pdf.multi_cell(0, 5, _safe(line))
            pdf.set_x(pdf.l_margin)
        pdf.ln(2)

    if booking.special_requests:
        pdf.ln(3)
        _section_title(pdf, "Special Requests")
        pdf.multi_cell(0, 5, _safe(booking.special_requests))

    # 一次付全款：无第 2 页。定金/分期：第 2 页放 History + 分期明细 + 退款
    if not show_history_page:
        # 极少：全款单若有退款记录，仍留在本页
        if refunds:
            pdf.ln(2)
            _draw_refunds()
    else:
        # ── Page 2: History ─────────────────────────────────────────
        pdf._page_subtitle = "Booking Receipt - History"
        pdf.add_page()

        _section_title(pdf, "Payment History")
        if payment_history:
            for row in payment_history:
                date_s = _fmt_date(row.get("date"))
                label = row.get("type_label") or "Payment"
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(17, 24, 39)
                pdf.cell(0, 6, _safe(f"{date_s}  -  {label}"), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("Helvetica", size=9)
                pdf.set_text_color(55, 65, 81)
                detail = (
                    f"Base {_money(row.get('base'))}  + fee {_money(row.get('fee'))}  "
                    f"= charged {_money(row.get('charged'))}"
                )
                if float(row.get("refunded") or 0) > 0:
                    detail += (
                        f"  |  refunded base {_money(row.get('refunded'))}  "
                        f"|  net {_money(row.get('net'))}"
                    )
                else:
                    detail += f"  |  net {_money(row.get('net'))}"
                pdf.multi_cell(0, 5, _safe(detail))
                pdf.set_x(pdf.l_margin)
                pdf.ln(2)
            pdf.ln(2)
        else:
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(107, 114, 128)
            pdf.cell(0, 6, "No payment records yet.", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        _draw_installment_schedule()
        _draw_refunds()

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()
