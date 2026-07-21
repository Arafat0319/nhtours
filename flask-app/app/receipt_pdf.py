"""Generate booking receipt PDF for download."""

from io import BytesIO

from fpdf import FPDF


def _money(value):
    try:
        return f"${float(value or 0):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _safe(text):
    """FPDF core fonts are Latin-1; drop unsupported glyphs."""
    if text is None:
        return ""
    s = str(text)
    try:
        s.encode("latin-1")
        return s
    except UnicodeEncodeError:
        return s.encode("latin-1", errors="replace").decode("latin-1")


class ReceiptPDF(FPDF):
    def footer(self):
        self.set_y(-18)
        self.set_font("Helvetica", size=9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, "Thank you for choosing Nexus Horizons Tours!", align="C", new_x="LMARGIN", new_y="NEXT")
        self.cell(0, 5, "For inquiries, please contact us at info@nhtours.com", align="C")


def build_booking_receipt_pdf(booking, trip, expected_amount, participants_info=None):
    """
    Build a PDF receipt for a booking.

    Returns:
        bytes: PDF file content
    """
    participants_info = participants_info or []
    pdf = ReceiptPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_margins(18, 18, 18)

    # Header
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(0, 10, "Nexus Horizons Tours", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    pdf.set_text_color(75, 85, 99)
    pdf.cell(110, 7, "Booking Receipt")

    order_date = booking.created_at.strftime("%B %d, %Y") if booking.created_at else ""
    pdf.set_xy(pdf.w - pdf.r_margin - 70, pdf.get_y() - 7)
    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(70, 5, f"Order number: {booking.id}\n{order_date}", align="R")
    pdf.ln(4)
    pdf.set_draw_color(229, 231, 235)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(8)

    # Trip
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(17, 24, 39)
    pdf.multi_cell(0, 7, _safe(trip.title if trip else "Trip"))
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(75, 85, 99)
    if trip and trip.start_date:
        end = trip.end_date.strftime("%B %d, %Y") if trip.end_date else "TBD"
        pdf.cell(0, 6, f"Dates: {trip.start_date.strftime('%B %d, %Y')} - {end}", new_x="LMARGIN", new_y="NEXT")
    if trip and getattr(trip, "destination_text", None):
        pdf.cell(0, 6, f"Destination: {_safe(trip.destination_text)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Client
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(0, 7, "Client Information", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(55, 65, 81)
    buyer_name = getattr(booking, "buyer_name", None) or ""
    buyer_email = booking.get_buyer_email() if hasattr(booking, "get_buyer_email") else (booking.buyer_email or "")
    buyer_phone = booking.get_buyer_phone() if hasattr(booking, "get_buyer_phone") else (booking.buyer_phone or "")
    for line in (buyer_name, buyer_email, buyer_phone):
        if line:
            pdf.cell(0, 5, _safe(line), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Booking details
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(0, 7, "Booking Details", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(55, 65, 81)

    packages = list(booking.booking_packages) if booking.booking_packages else []
    if packages:
        for bp in packages:
            if not bp.package:
                continue
            qty = int(bp.quantity or 1)
            price = float(bp.package.price or 0) * qty
            label = f"{bp.package.name} x{qty}"
            pdf.cell(130, 6, _safe(label))
            pdf.cell(0, 6, _money(price), align="R", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 6, "No Package", new_x="LMARGIN", new_y="NEXT")

    pdf.cell(130, 6, "Passengers")
    pdf.cell(0, 6, str(booking.passenger_count or 0), align="R", new_x="LMARGIN", new_y="NEXT")
    status = (booking.status or "").replace("_", " ").title()
    pdf.cell(130, 6, "Status")
    pdf.cell(0, 6, _safe(status), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Participants
    if participants_info:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(17, 24, 39)
        pdf.cell(0, 7, "Participants", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        pdf.set_text_color(55, 65, 81)
        for participant in participants_info:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, _safe(participant.get("name") or "Participant"), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=10)
            if participant.get("email"):
                pdf.cell(0, 5, _safe(participant["email"]), new_x="LMARGIN", new_y="NEXT")
            for addon in participant.get("addons") or []:
                line = f"  - {addon.get('name')} x{addon.get('quantity')} - {_money(addon.get('total'))}"
                pdf.cell(0, 5, _safe(line), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

    # Payment summary
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(17, 24, 39)
    pdf.cell(0, 7, "Payment Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(55, 65, 81)

    if packages:
        for bp in packages:
            if not bp.package:
                continue
            qty = int(bp.quantity or 1)
            price = float(bp.package.price or 0) * qty
            pdf.cell(130, 6, _safe(f"{bp.package.name} x{qty}:"))
            pdf.cell(0, 6, _money(price), align="R", new_x="LMARGIN", new_y="NEXT")

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

    if addons_total > 0:
        pdf.cell(130, 6, "Add-ons:")
        pdf.cell(0, 6, _money(addons_total), align="R", new_x="LMARGIN", new_y="NEXT")

    paid = float(booking.amount_paid or 0)
    pending = float(expected_amount or 0) - paid
    pdf.set_draw_color(209, 213, 219)
    pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.w - pdf.r_margin, pdf.get_y() + 1)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(130, 6, "Total Expected:")
    pdf.cell(0, 6, _money(expected_amount), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.cell(130, 6, "Amount Paid:")
    pdf.cell(0, 6, _money(paid), align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(130, 6, "Amount Pending:")
    pdf.cell(0, 6, _money(pending), align="R", new_x="LMARGIN", new_y="NEXT")

    if booking.special_requests:
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 7, "Special Requests", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=10)
        pdf.multi_cell(0, 5, _safe(booking.special_requests))

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()
