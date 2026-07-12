"""Ticket / boarding-pass PDF generation.

Extracted from views.py so PDF rendering is a standalone, testable unit. The
view layer fetches the booking and authorizes the request; this module only
turns a (booking, tickets) pair into a PDF.

Layout: a cover card summarising the trip and the fare, followed by one
airline-style boarding pass per passenger — two to a page — each with a route
hero, a detail grid and a perforated QR stub.
"""
import io
import os
from decimal import Decimal

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone

from reportlab.graphics.barcode import qr as rl_qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, Table, TableStyle,
    Paragraph, Spacer, KeepTogether,
)

# ---------- Brand palette ----------
DEEP      = colors.HexColor("#0A2540")
OCEAN     = colors.HexColor("#0E7490")
BRAND     = colors.HexColor("#0EA5E9")
ACCENT    = colors.HexColor("#06B6D4")
TEXT      = colors.HexColor("#0F172A")
MUTED     = colors.HexColor("#64748B")
FAINT     = colors.HexColor("#94A3B8")
BORDER    = colors.HexColor("#E2E8F0")
SURFACE   = colors.white
SURFACE_2 = colors.HexColor("#F8FAFC")
SUCCESS   = colors.HexColor("#059669")
SKY       = colors.HexColor("#BAE6FD")

PAGE_L = PAGE_R = 15 * mm
PAGE_T = 27 * mm
PAGE_B = 17 * mm
CONTENT_W = A4[0] - PAGE_L - PAGE_R


def booking_pdf_bytes(booking, tickets):
    """Return the boarding-pass PDF for a booking as raw bytes.

    Used to attach the tickets to confirmation emails (a standard attachment,
    which works over Brevo's HTTP API).
    """
    resp = render_booking_pdf(booking, tickets)
    f = resp.file_to_stream
    f.seek(0)
    return f.read()


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _fmt_dt(v, fmt="%a, %d %b %Y · %H:%M"):
    try:
        if not v:
            return "—"
        if hasattr(v, "strftime"):
            try:
                if timezone.is_aware(v):
                    v = timezone.localtime(v)
            except Exception:
                pass
            return v.strftime(fmt)
        return str(v)
    except Exception:
        return "—"


def _fmt_time(v):
    return _fmt_dt(v, "%H:%M")


def _fmt_date(v):
    return _fmt_dt(v, "%a, %d %b %Y")


def _fmt_duration(td):
    try:
        mins = int(td.total_seconds() // 60)
        h, m = divmod(mins, 60)
        if h and m:
            return f"{h}h {m}m"
        return f"{h}h" if h else f"{m}m"
    except Exception:
        return ""


def _money(v):
    try:
        return f"{Decimal(str(v)):,.2f}"
    except Exception:
        return "0.00"


def _load_image(src):
    try:
        if not src:
            return None
        if isinstance(src, (bytes, io.BytesIO)):
            return ImageReader(src)
        if os.path.exists(str(src)):
            return ImageReader(str(src))
    except Exception:
        pass
    return None


class _NumberedCanvas(pdfcanvas.Canvas):
    """Stamps "Page X of Y" once the total is known.

    ``showPage`` must NOT emit the page — it only snapshots state and starts a
    fresh page. ``save`` then replays each snapshot exactly once. The previous
    implementation called ``super().showPage()`` in both places, which emitted
    every page twice and invented a trailing blank page from an off-by-one
    ``num_pages``.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_number(total)
            super().showPage()
        super().save()

    def _draw_page_number(self, total):
        if total < 2:
            return  # a single-page ticket needs no pagination furniture
        self.saveState()
        self.setFont("Helvetica", 7.5)
        label = f"Page {self._pageNumber} of {total}"
        tw = self.stringWidth(label, "Helvetica", 7.5)
        self.setFillColor(FAINT)
        self.drawString(A4[0] - PAGE_R - tw, PAGE_B - 13, label)
        self.restoreState()


def render_booking_pdf(booking, tickets):
    """Build the boarding-pass PDF for a booking and return a FileResponse."""
    gen_time = timezone.localtime(timezone.now())

    schedule = booking.schedule
    route = schedule.route
    dep = route.departure_port.name
    dest = route.destination_port.name
    ferry = getattr(schedule.ferry, "name", None) or "—"

    depart_dt = schedule.departure_time
    arrive_dt = getattr(schedule, "arrival_time", None)
    duration = _fmt_duration(route.estimated_duration) if route.estimated_duration else ""

    logo_img = _load_image(os.path.join(settings.BASE_DIR, "static", "logo.png"))

    # ---------- Styles ----------
    base = getSampleStyleSheet()

    def style(name, **kw):
        base.add(ParagraphStyle(name, parent=base["Normal"], **kw))

    style("Label",     fontName="Helvetica-Bold", fontSize=6.5, textColor=FAINT, leading=9)
    style("LabelR",    fontName="Helvetica-Bold", fontSize=6.5, textColor=FAINT, leading=9, alignment=2)
    style("Val",       fontName="Helvetica-Bold", fontSize=9.5, textColor=TEXT, leading=12)
    style("ValSm",     fontName="Helvetica-Bold", fontSize=8.5, textColor=TEXT, leading=11)
    style("Port",      fontName="Helvetica-Bold", fontSize=13, textColor=DEEP, leading=16)
    style("PortR",     fontName="Helvetica-Bold", fontSize=13, textColor=DEEP, leading=16, alignment=2)
    style("Time",      fontName="Helvetica-Bold", fontSize=20, textColor=BRAND, leading=23)
    style("TimeR",     fontName="Helvetica-Bold", fontSize=20, textColor=BRAND, leading=23, alignment=2)
    style("Dur",       fontName="Helvetica", fontSize=7, textColor=MUTED, leading=9, alignment=1, spaceBefore=2)
    style("BarL",      fontName="Helvetica-Bold", fontSize=8, textColor=colors.white, leading=10)
    style("BarR",      fontName="Helvetica", fontSize=8, textColor=SKY, leading=10, alignment=2)
    style("StubLabel", fontName="Helvetica-Bold", fontSize=6, textColor=FAINT, leading=8, alignment=1)
    style("StubVal",   fontName="Helvetica-Bold", fontSize=8.5, textColor=DEEP, leading=10, alignment=1)
    style("Scan",      fontName="Helvetica-Bold", fontSize=6.5, textColor=MUTED, leading=9, alignment=1)
    style("Note",      fontName="Helvetica", fontSize=7, textColor=MUTED, leading=9)
    style("Section",   fontName="Helvetica-Bold", fontSize=7.5, textColor=MUTED, leading=10)
    style("RouteBig",  fontName="Helvetica-Bold", fontSize=15, textColor=DEEP, leading=18)
    style("Pill",      fontName="Helvetica-Bold", fontSize=7.5, textColor=colors.white, leading=10, alignment=1)
    style("Fare",      fontName="Helvetica", fontSize=8.5, textColor=TEXT, leading=11)
    style("FareR",     fontName="Helvetica", fontSize=8.5, textColor=TEXT, leading=11, alignment=2)
    style("FareTot",   fontName="Helvetica-Bold", fontSize=10, textColor=DEEP, leading=13)
    style("FareTotR",  fontName="Helvetica-Bold", fontSize=10, textColor=DEEP, leading=13, alignment=2)

    # ---------- Page furniture ----------
    def draw_header_footer(c, doc):
        band_h = 23 * mm
        c.saveState()

        c.setFillColor(DEEP)
        c.rect(0, A4[1] - band_h, A4[0], band_h, stroke=0, fill=1)
        c.setFillColor(BRAND)
        c.rect(0, A4[1] - band_h - 1.3 * mm, A4[0], 1.3 * mm, stroke=0, fill=1)

        title_x = PAGE_L
        drew_logo = False
        if logo_img:
            try:
                c.drawImage(logo_img, PAGE_L, A4[1] - band_h / 2 - 4.5 * mm,
                            width=9 * mm, height=9 * mm,
                            preserveAspectRatio=True, mask='auto')
                drew_logo = True
            except Exception:
                drew_logo = False
        if not drew_logo:
            # Vector monogram: never renders as unreadable squashed artwork.
            c.setFillColor(BRAND)
            c.roundRect(PAGE_L, A4[1] - band_h / 2 - 4.5 * mm, 9 * mm, 9 * mm, 2 * mm, stroke=0, fill=1)
            c.setFillColor(colors.white)
            c.setFont("Helvetica-Bold", 10)
            c.drawCentredString(PAGE_L + 4.5 * mm, A4[1] - band_h / 2 - 1.4 * mm, "FF")
        title_x = PAGE_L + 12.5 * mm

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(title_x, A4[1] - 11.5 * mm, "Fiji Ferry")
        c.setFillColor(SKY)
        c.setFont("Helvetica", 8)
        c.drawString(title_x, A4[1] - 16 * mm, "Boarding Pass & E-Ticket")

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(A4[0] - PAGE_R, A4[1] - 11 * mm, f"Booking #{booking.id}")
        c.setFillColor(SKY)
        c.setFont("Helvetica", 7.5)
        c.drawRightString(A4[0] - PAGE_R, A4[1] - 15.5 * mm, f"Issued {_fmt_dt(gen_time)}")

        # Footer
        c.setFillColor(SURFACE_2)
        c.rect(0, 0, A4[0], PAGE_B + 5 * mm, stroke=0, fill=1)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.6)
        c.line(PAGE_L, PAGE_B + 2 * mm, A4[0] - PAGE_R, PAGE_B + 2 * mm)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(PAGE_L, PAGE_B - 3,
                     "Arrive at the terminal at least 45 minutes before departure with valid photo ID.")
        c.setFillColor(FAINT)
        c.drawString(PAGE_L, PAGE_B - 12,
                     "support@fijiferrybooking.com  ·  +679 738 8496  ·  fijiferrybooking.com")
        c.restoreState()

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=PAGE_L, rightMargin=PAGE_R, topMargin=PAGE_T, bottomMargin=PAGE_B,
        title=f"Fiji Ferry Booking #{booking.id}", author="Fiji Ferry Booking",
    )
    frame = Frame(PAGE_L, PAGE_B, CONTENT_W, A4[1] - PAGE_T - PAGE_B,
                  leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="body")
    doc.addPageTemplates([PageTemplate(id="ticket", frames=[frame], onPage=draw_header_footer)])

    # ---------- Building blocks ----------
    def cell(label, value, vstyle="Val", align_right=False):
        return Table(
            [[Paragraph(label.upper(), base["LabelR" if align_right else "Label"])],
             [Paragraph(str(value), base[vstyle])]],
            style=TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, 0), 0),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 2),
                ('TOPPADDING', (0, 1), (-1, 1), 0),
                ('BOTTOMPADDING', (0, 1), (-1, 1), 0),
            ]))

    def qr_drawing(payload, size):
        try:
            widget = rl_qr.QrCodeWidget(payload or "")
            b = widget.getBounds()
            w, h = b[2] - b[0], b[3] - b[1]
            d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
            d.add(widget)
            return d
        except Exception:
            return Paragraph("QR unavailable", base["Scan"])

    def pill(text, bg):
        return Table(
            [[Paragraph(text.upper(), base["Pill"])]],
            colWidths=[24 * mm], rowHeights=[6.4 * mm],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), bg),
                ('ROUNDEDCORNERS', [3, 3, 3, 3]),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))

    def route_hero(width, time_style_l="Time", time_style_r="TimeR",
                   port_style_l="Port", port_style_r="PortR"):
        """Departure time/port  →  arrival time/port, with the duration between."""
        arr_txt = _fmt_time(arrive_dt) if arrive_dt else "—"
        col = width / 3.0
        mid = Table(
            [[Paragraph("&rarr;", ParagraphStyle(
                "arrow", parent=base["Normal"], fontName="Helvetica-Bold",
                fontSize=13, textColor=BRAND, alignment=1))],
             [Paragraph(duration or "&nbsp;", base["Dur"])]],
            colWidths=[col],
            style=TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
        return Table(
            [[Paragraph("DEPART", base["Label"]), "", Paragraph("ARRIVE", base["LabelR"])],
             [Paragraph(dep, base[port_style_l]), "", Paragraph(dest, base[port_style_r])],
             [Paragraph(_fmt_time(depart_dt), base[time_style_l]), mid,
              Paragraph(arr_txt, base[time_style_r])]],
            colWidths=[col, col, col],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('SPAN', (1, 0), (1, 1)),
                ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 1), ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ]))

    story = []

    # ====================================================================== #
    # 1) TRIP SUMMARY
    # ====================================================================== #
    status = (booking.status or "").lower()
    status_bg = SUCCESS if status == "confirmed" else (MUTED if status == "pending" else colors.HexColor("#DC2626"))

    total_pax = booking.passenger_adults + booking.passenger_children + booking.passenger_infants
    pax_bits = []
    if booking.passenger_adults:
        pax_bits.append(f"{booking.passenger_adults} adult" + ("s" if booking.passenger_adults > 1 else ""))
    if booking.passenger_children:
        pax_bits.append(f"{booking.passenger_children} child" + ("ren" if booking.passenger_children > 1 else ""))
    if booking.passenger_infants:
        pax_bits.append(f"{booking.passenger_infants} infant" + ("s" if booking.passenger_infants > 1 else ""))
    pax_txt = ", ".join(pax_bits) or "—"

    inner_w = CONTENT_W - 24

    head_row = Table(
        [[Paragraph("YOUR TRIP", base["Section"]), pill(status or "unknown", status_bg)]],
        colWidths=[inner_w - 24 * mm, 24 * mm],
        style=TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

    facts = Table(
        [[cell("Ferry", ferry, "ValSm"),
          cell("Departs", _fmt_dt(depart_dt), "ValSm"),
          cell("Passengers", pax_txt, "ValSm"),
          cell("Total paid", f"FJD {_money(booking.total_price)}", "ValSm")]],
        colWidths=[inner_w * 0.26, inner_w * 0.28, inner_w * 0.26, inner_w * 0.20],
        style=TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (0, 0), 0),
            ('LEFTPADDING', (1, 0), (-1, 0), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('LINEBEFORE', (1, 0), (-1, -1), 0.4, BORDER),
            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

    summary_inner = Table(
        [[head_row],
         [Spacer(0, 3.5 * mm)],
         [Paragraph(f"{dep} &rarr; {dest}", base["RouteBig"])],
         [Spacer(0, 4 * mm)],
         [facts]],
        colWidths=[inner_w],
        style=TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

    story.append(Table(
        [[summary_inner]], colWidths=[CONTENT_W],
        style=TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), SURFACE_2),
            ('BOX', (0, 0), (-1, -1), 0.8, BORDER),
            ('ROUNDEDCORNERS', [7, 7, 7, 7]),
            ('LINEBEFORE', (0, 0), (0, -1), 3.2, BRAND),
            ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING', (0, 0), (-1, -1), 11), ('BOTTOMPADDING', (0, 0), (-1, -1), 11),
        ])))
    story.append(Spacer(0, 5 * mm))

    # ====================================================================== #
    # 2) FARE BREAKDOWN — what the customer actually paid for
    # ====================================================================== #
    base_fare = route.base_fare or Decimal("35.50")
    rows = []

    def fare_row(label, qty, unit, amount):
        # Only spell out "qty × unit" when we actually know the unit price;
        # add-ons store a line total, so showing "1 × FJD 0.00" would be a lie.
        if qty and unit is not None:
            detail = f"{qty} × FJD {_money(unit)}"
        elif qty and qty > 1:
            detail = f"× {qty}"
        else:
            detail = ""
        rows.append([
            Paragraph(label, base["Fare"]),
            Paragraph(detail, base["Fare"]),
            Paragraph(f"FJD {_money(amount)}", base["FareR"]),
        ])

    if booking.passenger_adults:
        fare_row("Adults", booking.passenger_adults, base_fare, Decimal(booking.passenger_adults) * base_fare)
    if booking.passenger_children:
        u = base_fare * Decimal("0.5")
        fare_row("Children (50%)", booking.passenger_children, u, Decimal(booking.passenger_children) * u)
    if booking.passenger_infants:
        u = base_fare * Decimal("0.1")
        fare_row("Infants (10%)", booking.passenger_infants, u, Decimal(booking.passenger_infants) * u)

    try:
        for c_ in booking.cargo.all():
            fare_row(f"Cargo — {c_.cargo_type} ({c_.weight_kg} kg)", None, None, c_.price or 0)
    except Exception:
        pass
    try:
        for a_ in booking.add_ons.all():
            fare_row(a_.get_add_on_type_display(), a_.quantity, None, a_.price or 0)
    except Exception:
        pass

    if rows:
        rows.append([
            Paragraph("Total paid", base["FareTot"]), "",
            Paragraph(f"FJD {_money(booking.total_price)}", base["FareTotR"]),
        ])
        fare_tbl = Table(
            rows, colWidths=[CONTENT_W * 0.46, CONTENT_W * 0.30, CONTENT_W * 0.24],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LINEBELOW', (0, 0), (-1, -2), 0.4, BORDER),
                ('LINEABOVE', (0, -1), (-1, -1), 1.1, BRAND),
                ('BACKGROUND', (0, -1), (-1, -1), SURFACE_2),
                ('BOX', (0, 0), (-1, -1), 0.8, BORDER),
                ('ROUNDEDCORNERS', [7, 7, 7, 7]),
            ]))
        story.append(KeepTogether([
            Paragraph("FARE BREAKDOWN", base["Section"]), Spacer(0, 2 * mm), fare_tbl,
        ]))
        story.append(Spacer(0, 6 * mm))

    # ====================================================================== #
    # 3) BOARDING PASSES — two per page
    # ====================================================================== #
    STUB_W = 40 * mm
    MAIN_W = CONTENT_W - STUB_W
    MAIN_INNER = MAIN_W - 20

    def boarding_pass(t, idx, total):
        p = t.passenger
        name = p.get_full_name() if hasattr(p, "get_full_name") else f"{p.first_name} {p.last_name}"
        ptype = p.get_passenger_type_display() if hasattr(p, "get_passenger_type_display") else p.passenger_type
        seat = getattr(t, "seat_number", None) or getattr(t, "seat", None) or "Open seating"
        tstatus = (t.ticket_status or "active").upper()

        bar = Table(
            [[Paragraph("BOARDING PASS", base["BarL"]),
              Paragraph(f"Passenger {idx} of {total}", base["BarR"])]],
            colWidths=[MAIN_INNER * 0.5, MAIN_INNER * 0.5],
            style=TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
        bar_wrap = Table(
            [[bar]], colWidths=[MAIN_W],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), DEEP),
                ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ('LINEBELOW', (0, 0), (-1, -1), 1.6, BRAND),
            ]))

        details = Table(
            [[cell("Passenger", name, "ValSm"), cell("Type", ptype, "ValSm"), cell("Seat", str(seat), "ValSm")],
             [cell("Date", _fmt_date(depart_dt), "ValSm"), cell("Ferry", ferry, "ValSm"),
              cell("Ticket", f"#{t.id}", "ValSm")]],
            colWidths=[MAIN_INNER / 3.0] * 3,
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (0, -1), 0), ('LEFTPADDING', (1, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, 0), 0), ('BOTTOMPADDING', (0, 0), (-1, 0), 7),
                ('TOPPADDING', (0, 1), (-1, 1), 7), ('BOTTOMPADDING', (0, 1), (-1, 1), 0),
                ('LINEABOVE', (0, 1), (-1, 1), 0.4, BORDER),
            ]))

        main = Table(
            [[bar_wrap],
             [Table([[route_hero(MAIN_INNER)]], colWidths=[MAIN_W],
                    style=TableStyle([
                        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                        ('TOPPADDING', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
                        ('BACKGROUND', (0, 0), (-1, -1), SURFACE_2),
                    ]))],
             [Table([[details]], colWidths=[MAIN_W],
                    style=TableStyle([
                        ('LEFTPADDING', (0, 0), (-1, -1), 10), ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                        ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                    ]))]],
            colWidths=[MAIN_W],
            style=TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))

        qr_payload = getattr(t, "qr_token", "") or ""
        stub = Table(
            [[Paragraph("SCAN AT GATE", base["Scan"])],
             [Spacer(0, 2 * mm)],
             [qr_drawing(qr_payload, 26 * mm)],
             [Spacer(0, 2 * mm)],
             [Paragraph(f"#{booking.id} · #{t.id}", base["StubVal"])],
             [Paragraph(tstatus, ParagraphStyle(
                 "st", parent=base["StubLabel"],
                 textColor=SUCCESS if tstatus == "ACTIVE" else MUTED))]],
            colWidths=[STUB_W - 16],
            style=TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
        stub_wrap = Table(
            [[stub]], colWidths=[STUB_W],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), SURFACE_2),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ]))

        return Table(
            [[main, stub_wrap]], colWidths=[MAIN_W, STUB_W],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOX', (0, 0), (-1, -1), 0.9, BORDER),
                ('ROUNDEDCORNERS', [7, 7, 7, 7]),
                ('BACKGROUND', (0, 0), (0, -1), SURFACE),
                # Tint the stub on the OUTER cell: the nested table only spans its
                # own content height, which left a white gap under the QR code.
                ('BACKGROUND', (1, 0), (1, -1), SURFACE_2),
                ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('LINEBEFORE', (1, 0), (1, -1), 0.8, FAINT, None, (2, 2)),
            ]))

    if tickets:
        story.append(Paragraph("BOARDING PASSES", base["Section"]))
        story.append(Spacer(0, 2 * mm))

    n = len(tickets)
    for i, t in enumerate(tickets, start=1):
        story.append(KeepTogether([
            boarding_pass(t, i, n),
            Spacer(0, 1.5 * mm),
            Paragraph("Valid only for the named passenger and sailing above. Non-transferable.", base["Note"]),
        ]))
        story.append(Spacer(0, 5 * mm))

    # ====================================================================== #
    # 4) NO-TICKET FALLBACK
    # ====================================================================== #
    if not tickets:
        contact = (getattr(getattr(booking, "user", None), "email", None)
                   or getattr(booking, "guest_email", None) or "—")
        story.append(Table(
            [[cell("Booking", f"#{booking.id}", "ValSm"),
              cell("Route", f"{dep} → {dest}", "ValSm"),
              cell("Contact", contact, "ValSm")]],
            colWidths=[CONTENT_W * 0.22, CONTENT_W * 0.44, CONTENT_W * 0.34],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOX', (0, 0), (-1, -1), 0.8, BORDER),
                ('ROUNDEDCORNERS', [7, 7, 7, 7]),
                ('LEFTPADDING', (0, 0), (-1, -1), 12), ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ])))
        story.append(Spacer(0, 3 * mm))
        story.append(Paragraph(
            "Tickets for this booking have not been issued yet. They appear here once payment is confirmed.",
            base["Note"]))

    doc.build(story, canvasmaker=_NumberedCanvas)
    buf.seek(0)
    return FileResponse(
        buf, as_attachment=True,
        filename=f"FijiFerry_Booking_{booking.id}_Tickets.pdf",
        content_type="application/pdf",
    )
