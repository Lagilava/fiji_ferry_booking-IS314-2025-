"""Ticket / boarding-pass PDF generation.

Extracted from views.py so PDF rendering is a standalone, testable unit. The
view layer is responsible for fetching the booking and authorizing the request;
this module only turns a (booking, tickets) pair into a PDF response.

The layout is a modern, airline-style boarding pass: a trip-summary header card
followed by one cleanly organised pass per passenger, each with a route hero
(large departure/arrival times), a tidy detail grid, and a perforated QR stub.
"""
import io
import os

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


def render_booking_pdf(booking, tickets):
    """Build the boarding-pass PDF for a booking and return a FileResponse."""
    # ---------- Brand palette (2026 refresh) ----------
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

    gen_time = timezone.localtime(timezone.now())

    # ---------- Helpers ----------
    def _load_image(src):
        try:
            if not src:
                return None
            if isinstance(src, (bytes, io.BytesIO)):
                return ImageReader(src)
            path = str(src)
            if os.path.exists(path):
                return ImageReader(path)
        except Exception:
            pass
        return None

    def fmt_dt(v, fmt="%a, %d %b %Y · %H:%M"):
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

    def fmt_time(v):
        return fmt_dt(v, "%H:%M")

    def fmt_date(v):
        return fmt_dt(v, "%a, %d %b %Y")

    def fmt_duration(td):
        try:
            mins = int(td.total_seconds() // 60)
            h, m = divmod(mins, 60)
            if h and m:
                return f"{h}h {m}m"
            if h:
                return f"{h}h"
            return f"{m}m"
        except Exception:
            return ""

    logo_img = _load_image(os.path.join(settings.BASE_DIR, "static", "logo.png"))

    # ---------- Styles ----------
    base = getSampleStyleSheet()

    def style(name, **kw):
        base.add(ParagraphStyle(name, parent=base["Normal"], **kw))

    style("MicroLabel", fontName="Helvetica-Bold", fontSize=6.5, textColor=FAINT, leading=9, spaceAfter=0)
    style("SectionLabel", fontName="Helvetica-Bold", fontSize=7.5, textColor=MUTED, leading=10)
    style("FieldVal", fontName="Helvetica-Bold", fontSize=10, textColor=TEXT, leading=12)
    style("FieldValSm", fontName="Helvetica-Bold", fontSize=9, textColor=TEXT, leading=11)
    style("PortName", fontName="Helvetica-Bold", fontSize=15, textColor=DEEP, leading=18)
    style("PortNameR", fontName="Helvetica-Bold", fontSize=15, textColor=DEEP, leading=18, alignment=2)
    style("TimeBig", fontName="Helvetica-Bold", fontSize=22, textColor=BRAND, leading=25)
    style("TimeBigR", fontName="Helvetica-Bold", fontSize=22, textColor=BRAND, leading=25, alignment=2)
    style("Duration", fontName="Helvetica", fontSize=7.5, textColor=MUTED, leading=10, alignment=1)
    style("PassTitle", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white, leading=10)
    style("PassMeta", fontName="Helvetica", fontSize=8, textColor=colors.white, leading=10, alignment=2)
    style("StubLabel", fontName="Helvetica-Bold", fontSize=6.5, textColor=FAINT, leading=9, alignment=1)
    style("StubVal", fontName="Helvetica-Bold", fontSize=9, textColor=DEEP, leading=11, alignment=1)
    style("ScanNote", fontName="Helvetica", fontSize=7, textColor=MUTED, leading=9, alignment=1)
    style("Note", fontName="Helvetica", fontSize=7.5, textColor=MUTED, leading=10)
    style("SummaryRoute", fontName="Helvetica-Bold", fontSize=13, textColor=DEEP, leading=16)
    style("Pill", fontName="Helvetica-Bold", fontSize=8, textColor=colors.white, leading=10, alignment=1)

    # ---------- Page furniture ----------
    PAGE_L = 16 * mm
    PAGE_R = 16 * mm
    PAGE_T = 26 * mm
    PAGE_B = 18 * mm
    CONTENT_W = A4[0] - PAGE_L - PAGE_R
    ACCENT_W = 4                        # left-accent stripe width
    INNER_PAD = 14                      # horizontal padding inside accent cards
    INNER_W = CONTENT_W - ACCENT_W - 2 * INNER_PAD

    def draw_header_footer(c, doc):
        band_h = 22 * mm
        c.saveState()

        # --- Header band ---
        c.setFillColor(DEEP)
        c.rect(0, A4[1] - band_h, A4[0], band_h, stroke=0, fill=1)
        c.setFillColor(BRAND)
        c.rect(0, A4[1] - band_h - 1.4 * mm, A4[0], 1.4 * mm, stroke=0, fill=1)

        title_x = PAGE_L
        if logo_img:
            try:
                c.drawImage(logo_img, PAGE_L, A4[1] - band_h / 2 - 7 * mm,
                            width=36 * mm, height=14 * mm,
                            preserveAspectRatio=True, mask='auto')
                title_x = PAGE_L + 44 * mm
            except Exception:
                pass

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(title_x, A4[1] - 12 * mm, "Fiji Ferry")
        c.setFillColor(colors.HexColor("#BAE6FD"))
        c.setFont("Helvetica", 8.5)
        c.drawString(title_x, A4[1] - 16.5 * mm, "Boarding Pass & E-Ticket")

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(A4[0] - PAGE_R, A4[1] - 11 * mm, f"Booking #{booking.id}")
        c.setFillColor(colors.HexColor("#BAE6FD"))
        c.setFont("Helvetica", 8)
        c.drawRightString(A4[0] - PAGE_R, A4[1] - 16 * mm, f"Issued {fmt_dt(gen_time)}")

        # --- Footer band ---
        c.setFillColor(SURFACE_2)
        c.rect(0, 0, A4[0], PAGE_B + 6 * mm, stroke=0, fill=1)
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.6)
        c.line(PAGE_L, PAGE_B + 2 * mm, A4[0] - PAGE_R, PAGE_B + 2 * mm)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7.5)
        c.drawString(PAGE_L, PAGE_B - 3,
                     "Please arrive at the terminal at least 45 minutes before departure with valid photo ID.")
        c.setFillColor(FAINT)
        c.drawString(PAGE_L, PAGE_B - 13,
                     "support@fijiferry.example  ·  +679 738 8496  ·  fijiferry.example")
        c.restoreState()

    class NumberedCanvas(pdfcanvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            super().showPage()

        def save(self):
            num_pages = len(self._saved_page_states) + 1
            for i, state in enumerate(self._saved_page_states):
                self.__dict__.update(state)
                self._draw_page_number(i + 1, num_pages)
                super().showPage()
            self._draw_page_number(num_pages, num_pages)
            super().save()

        def _draw_page_number(self, page_num, total_pages):
            self.saveState()
            self.setFont("Helvetica", 7.5)
            label = f"Page {page_num} of {total_pages}"
            tw = self.stringWidth(label, "Helvetica", 7.5)
            self.setFillColor(FAINT)
            self.drawString(A4[0] - PAGE_R - tw, PAGE_B - 13, label)
            self.restoreState()

    # ---------- Doc template ----------
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=PAGE_L, rightMargin=PAGE_R,
        topMargin=PAGE_T + 8 * mm, bottomMargin=PAGE_B + 6 * mm,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='content')
    doc.addPageTemplates([PageTemplate(id="ticket", frames=[frame], onPage=draw_header_footer)])

    # ---------- Shared trip data ----------
    sched = getattr(booking, 'schedule', None)
    route = getattr(sched, 'route', None) if sched else None
    dep = dest = "—"
    if route:
        dep = getattr(getattr(route, 'departure_port', None), 'name', '—') or '—'
        dest = getattr(getattr(route, 'destination_port', None), 'name', '—') or '—'
    ferry_name = getattr(getattr(sched, 'ferry', None), 'name', '—') if sched else '—'
    dep_dt = getattr(sched, 'departure_time', None) if sched else None
    arr_dt = getattr(sched, 'arrival_time', None) if sched else None
    duration_txt = fmt_duration(getattr(route, 'estimated_duration', None)) if route else ""

    # ---------- Reusable building blocks ----------

    def info_cell(label, value, val_style="FieldVal"):
        """Stacked micro-label + value, zero outer padding."""
        return Table(
            [[Paragraph(label.upper(), base["MicroLabel"])],
             [Paragraph(value if value not in (None, "") else "—", base[val_style])]],
            style=TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (0, 0), 0),
                ('BOTTOMPADDING', (0, 0), (0, 0), 1),
                ('TOPPADDING', (0, 1), (0, 1), 0),
                ('BOTTOMPADDING', (0, 1), (0, 1), 0),
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
            return Paragraph("QR unavailable", base["ScanNote"])

    def accent_card(inner, *, border_color=BORDER, radius=6):
        """Wrap *inner* flowable in a rounded card with a BRAND left-accent stripe."""
        return Table(
            [[Paragraph("", base["Normal"]), inner]],
            colWidths=[ACCENT_W, CONTENT_W - ACCENT_W],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), SURFACE_2),
                ('BACKGROUND', (0, 0), (0, -1), BRAND),
                ('BOX', (0, 0), (-1, -1), 0.8, border_color),
                ('ROUNDEDCORNERS', [radius, radius, radius, radius]),
                # accent stripe — collapse padding
                ('LEFTPADDING', (0, 0), (0, -1), 0),
                ('RIGHTPADDING', (0, 0), (0, -1), 0),
                ('TOPPADDING', (0, 0), (0, -1), 0),
                ('BOTTOMPADDING', (0, 0), (0, -1), 0),
                # content area
                ('LEFTPADDING', (1, 0), (1, -1), INNER_PAD),
                ('RIGHTPADDING', (1, 0), (1, -1), INNER_PAD),
                ('TOPPADDING', (0, 0), (-1, -1), INNER_PAD),
                ('BOTTOMPADDING', (0, 0), (-1, -1), INNER_PAD),
            ]))

    def note_bar(text):
        """Small note line with a thin left accent."""
        return Table(
            [[Paragraph("", base["Normal"]),
              Paragraph(text, base["Note"])]],
            colWidths=[3, CONTENT_W - 3],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), FAINT),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('LEFTPADDING', (1, 0), (1, -1), 8),
            ]))

    story = []

    # ====================================================================== #
    # 1) TRIP SUMMARY CARD
    # ====================================================================== #
    pax_total = (getattr(booking, 'passenger_adults', 0) or 0) \
        + (getattr(booking, 'passenger_children', 0) or 0) \
        + (getattr(booking, 'passenger_infants', 0) or 0)
    pax_bits = []
    if getattr(booking, 'passenger_adults', 0):
        pax_bits.append(f"{booking.passenger_adults} Adult"
                        + ("s" if booking.passenger_adults != 1 else ""))
    if getattr(booking, 'passenger_children', 0):
        pax_bits.append(f"{booking.passenger_children} Child"
                        + ("ren" if booking.passenger_children != 1 else ""))
    if getattr(booking, 'passenger_infants', 0):
        pax_bits.append(f"{booking.passenger_infants} Infant"
                        + ("s" if booking.passenger_infants != 1 else ""))
    pax_label = ", ".join(pax_bits) or f"{pax_total} passenger(s)"

    total_price = getattr(booking, 'total_price', None)
    total_txt = f"FJD {total_price:,.2f}" if total_price is not None else "—"

    status = getattr(booking, 'status', '') or ''
    status_txt = status.title() if status else "Confirmed"
    status_color = SUCCESS if status.lower() == 'confirmed' else OCEAN
    status_pill = Table(
        [[Paragraph(status_txt.upper(), base["Pill"])]],
        colWidths=[26 * mm],
        style=TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), status_color),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('ROUNDEDCORNERS', [4, 4, 4, 4]),
        ]))

    summary_top = Table(
        [[Paragraph("YOUR TRIP", base["SectionLabel"]), status_pill]],
        colWidths=[INNER_W - 26 * mm - 20, 26 * mm],
        style=TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))

    summary_route = Paragraph(f"{dep}  →  {dest}", base["SummaryRoute"])

    summary_grid = Table(
        [[info_cell("Ferry", ferry_name),
          info_cell("Departs", fmt_dt(dep_dt)),
          info_cell("Passengers", pax_label, "FieldValSm"),
          info_cell("Total paid", total_txt)]],
        colWidths=[INNER_W * 0.24, INNER_W * 0.30, INNER_W * 0.28, INNER_W * 0.18],
        style=TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (0, 0), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('LINEBEFORE', (1, 0), (1, -1), 0.4, BORDER),
            ('LINEBEFORE', (2, 0), (2, -1), 0.4, BORDER),
            ('LINEBEFORE', (3, 0), (3, -1), 0.4, BORDER),
        ]))

    summary_inner = Table(
        [[summary_top],
         [Spacer(0, 3 * mm)],
         [summary_route],
         [Spacer(0, 4 * mm)],
         [summary_grid]],
        colWidths=[INNER_W],
        style=TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))

    story += [accent_card(summary_inner), Spacer(0, 8 * mm)]

    # ====================================================================== #
    # 2) BOARDING PASSES (one per ticket)
    # ====================================================================== #
    MAIN_W = CONTENT_W * 0.70
    STUB_W = CONTENT_W * 0.30

    def boarding_pass(t, idx, count):
        passenger = getattr(t, 'passenger', None)
        name = "—"
        ptype = "—"
        if passenger:
            name = (f"{getattr(passenger, 'first_name', '') or ''} "
                    f"{getattr(passenger, 'last_name', '') or ''}").strip() or "—"
            ptype = getattr(passenger, 'get_passenger_type_display', lambda: "—")()
        seat = (getattr(t, 'seat_number', None)
                or getattr(t, 'seat', None) or "Open seating")
        tstatus = getattr(t, 'ticket_status', None)
        tstatus_txt = (tstatus.title() if isinstance(tstatus, str)
                       else str(tstatus or "Active"))
        ticket_id = getattr(t, 'id', '—')

        # --- header strip ---
        strip = Table(
            [[Paragraph("BOARDING PASS", base["PassTitle"]),
              Paragraph(f"Passenger {idx} of {count}", base["PassMeta"])]],
            colWidths=[MAIN_W * 0.5 - 12, MAIN_W * 0.5 - 12],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), DEEP),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (0, 0), 12),
                ('RIGHTPADDING', (1, 0), (1, 0), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))

        # --- brand accent line under header ---
        accent_line = Table(
            [[""]],
            colWidths=[MAIN_W], rowHeights=[5],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), BRAND),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))

        # --- route hero (tinted background) ---
        arrow_style = ParagraphStyle(
            'arrow', parent=base["Normal"],
            fontName="Helvetica-Bold", fontSize=22,
            textColor=BRAND, alignment=1, leading=26)
        arrow = Table(
            [[Paragraph("→", arrow_style)],
             [Paragraph(duration_txt or "Direct", base["Duration"])]],
            style=TableStyle([
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (0, 0), 0),
                ('TOPPADDING', (0, 1), (0, 1), 2),
            ]))

        hero_inner = Table(
            [[Paragraph("DEPART", base["MicroLabel"]), "",
              Paragraph("ARRIVE", ParagraphStyle('mr', parent=base["MicroLabel"], alignment=2))],
             [Paragraph(dep, base["PortName"]), "",
              Paragraph(dest, base["PortNameR"])],
             [Paragraph(fmt_time(dep_dt), base["TimeBig"]), arrow,
              Paragraph(fmt_time(arr_dt), base["TimeBigR"])]],
            colWidths=[MAIN_W * 0.36, MAIN_W * 0.28, MAIN_W * 0.36],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 0),
                ('TOPPADDING', (0, 1), (-1, 1), 0),
                ('BOTTOMPADDING', (0, 1), (-1, 1), 2),
                ('TOPPADDING', (0, 2), (-1, 2), 0),
                ('BOTTOMPADDING', (0, 2), (-1, 2), 10),
            ]))

        hero = Table(
            [[hero_inner]],
            colWidths=[MAIN_W],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), SURFACE_2),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))

        # --- detail grid (with cell dividers) ---
        details = Table(
            [[info_cell("Passenger", name, "FieldValSm"),
              info_cell("Type", ptype),
              info_cell("Seat", str(seat))],
             [info_cell("Date", fmt_date(dep_dt)),
              info_cell("Ferry", ferry_name, "FieldValSm"),
              info_cell("Ticket", f"#{ticket_id}")]],
            colWidths=[MAIN_W * 0.40, MAIN_W * 0.30, MAIN_W * 0.30],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 1), (-1, 1), 6),
                ('BOTTOMPADDING', (0, 1), (-1, 1), 10),
                ('LINEABOVE', (0, 0), (-1, 0), 0.8, BORDER),
                ('LINEBELOW', (0, 0), (-1, 0), 0.4, BORDER),
                ('LINEBEFORE', (1, 0), (1, -1), 0.4, BORDER),
                ('LINEBEFORE', (2, 0), (2, -1), 0.4, BORDER),
            ]))

        # --- bottom status bar ---
        status_right = Table(
            [[Paragraph("●", ParagraphStyle('dot', fontName="Helvetica",
                                             fontSize=7, textColor=SUCCESS, leading=9)),
              Paragraph(tstatus_txt.upper(),
                        ParagraphStyle('st', fontName="Helvetica-Bold",
                                       fontSize=7.5, textColor=SUCCESS, leading=9))]],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))

        status_bar = Table(
            [[Paragraph(f"Ticket #{ticket_id}",
                        ParagraphStyle('sb1', fontName="Helvetica", fontSize=7,
                                       textColor=MUTED, leading=9)),
              status_right]],
            colWidths=[MAIN_W * 0.55, MAIN_W * 0.45],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), SURFACE_2),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (0, 0), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))

        main_content = Table(
            [[strip], [accent_line], [hero], [details], [status_bar]],
            colWidths=[MAIN_W],
            style=TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))

        # --- stub (QR side) ---
        qr_size = STUB_W - 22

        stub_header = Table(
            [[Paragraph("SCAN AT GATE",
                        ParagraphStyle('sh', fontName="Helvetica-Bold", fontSize=8,
                                       textColor=colors.white, leading=10, alignment=1))]],
            colWidths=[STUB_W],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), DEEP),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))

        # Thin brand line mirroring main column's accent line
        stub_accent = Table(
            [[""]],
            colWidths=[STUB_W], rowHeights=[5],
            style=TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), BRAND),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))

        stub = Table(
            [[stub_header],
             [stub_accent],
             [Spacer(0, 3 * mm)],
             [qr_drawing(f"FFB:{booking.id}:{ticket_id}", qr_size)],
             [Spacer(0, 2 * mm)],
             [Paragraph("BOOKING", base["StubLabel"])],
             [Paragraph(f"#{booking.id}", base["StubVal"])],
             [Spacer(0, 1.5 * mm)],
             [Paragraph("TICKET", base["StubLabel"])],
             [Paragraph(f"#{ticket_id}", base["StubVal"])],
             [Spacer(0, 1.5 * mm)],
             [Paragraph("SEAT", base["StubLabel"])],
             [Paragraph(str(seat), base["StubVal"])],
             [Spacer(0, 2 * mm)],
             [Paragraph(tstatus_txt, base["ScanNote"])]],
            colWidths=[STUB_W],
            style=TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ('BACKGROUND', (0, 0), (-1, -1), SURFACE_2),
            ]))

        # --- assemble pass ---
        card = Table(
            [[main_content, stub]],
            colWidths=[MAIN_W, STUB_W],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('BOX', (0, 0), (-1, -1), 0.9, BORDER),
                ('ROUNDEDCORNERS', [6, 6, 6, 6]),
                ('BACKGROUND', (0, 0), (-1, -1), SURFACE),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('BOTTOMPADDING', (0, -1), (-1, -1), 8),
                # perforation line
                ('LINEBEFORE', (1, 0), (1, -1), 0.8, MUTED, None, (3, 3)),
            ]))
        return card

    n = len(tickets)
    for i, t in enumerate(tickets, start=1):
        story += [KeepTogether([
            boarding_pass(t, i, n),
            Spacer(0, 2 * mm),
            note_bar("Valid only for the named passenger and sailing above. "
                     "Non-transferable."),
        ]), Spacer(0, 8 * mm)]

    # ====================================================================== #
    # 3) NO-TICKET FALLBACK
    # ====================================================================== #
    if not tickets:
        contact = (getattr(getattr(booking, 'user', None), 'email', None)
                   or getattr(booking, 'guest_email', None) or "—")
        overview_grid = Table(
            [[info_cell("Booking", f"#{booking.id}"),
              info_cell("Route", f"{dep} → {dest}", "FieldValSm"),
              info_cell("Contact", contact, "FieldValSm")]],
            colWidths=[INNER_W * 0.22, INNER_W * 0.44, INNER_W * 0.34],
            style=TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (0, 0), 0),
                ('LINEBEFORE', (1, 0), (1, -1), 0.4, BORDER),
                ('LINEBEFORE', (2, 0), (2, -1), 0.4, BORDER),
            ]))
        overview_inner = Table(
            [[Paragraph("BOOKING OVERVIEW", base["SectionLabel"])],
             [Spacer(0, 2 * mm)],
             [overview_grid]],
            colWidths=[INNER_W],
            style=TableStyle([
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
        story.append(accent_card(overview_inner))

    # ---------- Build ----------
    doc.build(story, canvasmaker=NumberedCanvas)
    buf.seek(0)
    return FileResponse(
        buf, as_attachment=True,
        filename=f"FijiFerry_Booking_{booking.id}_Tickets.pdf")