"""Ticket / boarding-pass PDF generation.

Extracted from views.py so PDF rendering is a standalone, testable unit. The
view layer is responsible for fetching the booking and authorizing the request;
this module only turns a (booking, tickets) pair into a PDF response.
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
    # ---------- Brand ----------
    BRAND_PRIMARY = colors.HexColor("#0EA5E9")
    BRAND_DARK    = colors.HexColor("#1E40AF")
    TEXT_PRIMARY  = colors.HexColor("#111827")
    TEXT_MUTED    = colors.HexColor("#6B7280")
    BORDER        = colors.HexColor("#E5E7EB")
    SURFACE       = colors.white

    # Timestamp used for "Generated" (always now, localized)
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

    def fmt_dt(v):
        """
        Formats datetimes defensively and converts aware datetimes to local time.
        Also accepts date-like or plain strings.
        """
        try:
            if not v:
                return "—"
            # Datetime-like
            if hasattr(v, "strftime"):
                try:
                    # If aware, convert to local; if naive, leave as-is
                    if timezone.is_aware(v):
                        v = timezone.localtime(v)
                except Exception:
                    pass
                return v.strftime("%a, %d %b %Y %H:%M")
            # Fallback for strings/others
            return str(v)
        except Exception:
            return "—"

    logo_img = _load_image(os.path.join(settings.BASE_DIR, "static", "logo.png"))

    # ---------- Styles ----------
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("SectionLabel", parent=styles["Normal"],
                              fontName="Helvetica-Bold", fontSize=10.5,
                              textColor=BRAND_DARK, spaceAfter=3, leading=12))
    styles.add(ParagraphStyle("Key", parent=styles["Normal"],
                              fontName="Helvetica", fontSize=9.5,
                              textColor=TEXT_MUTED, leading=12))
    styles.add(ParagraphStyle("Val", parent=styles["Normal"],
                              fontName="Helvetica-Bold", fontSize=10.5,
                              textColor=TEXT_PRIMARY, leading=12))
    styles.add(ParagraphStyle("RoutePill", parent=styles["Normal"],
                              fontName="Helvetica-Bold", fontSize=10,
                              textColor=colors.white, alignment=1, leading=12))
    styles.add(ParagraphStyle("SmallNote", parent=styles["Normal"],
                              fontName="Helvetica", fontSize=8.5,
                              textColor=TEXT_MUTED, leading=11))

    # ---------- Page furniture ----------
    PAGE_MARGIN_L = 15 * mm
    PAGE_MARGIN_R = 15 * mm
    PAGE_MARGIN_T = 24 * mm
    PAGE_MARGIN_B = 20 * mm

    def draw_header_footer(c, doc):
        band_h = 20 * mm
        c.saveState()

        # header band
        c.setFillColor(BRAND_PRIMARY)
        c.rect(0, A4[1] - band_h, A4[0], band_h, stroke=0, fill=1)
        c.setFillColor(BRAND_DARK)
        c.rect(0, A4[1] - band_h, A4[0], band_h / 3.0, stroke=0, fill=1)

        # logo + title
        title_x = PAGE_MARGIN_L
        if logo_img:
            try:
                c.drawImage(
                    logo_img,
                    PAGE_MARGIN_L,
                    A4[1] - band_h/2 - 7*mm,
                    width=40*mm,
                    height=14*mm,
                    preserveAspectRatio=True,
                    mask='auto'
                )
                title_x = PAGE_MARGIN_L + 48 * mm
            except Exception:
                pass

        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(title_x, A4[1] - 13 * mm, "Fiji Ferry")
        c.setFont("Helvetica", 10)
        c.drawString(title_x, A4[1] - 18 * mm, f"Booking #{booking.id}")

        # right-aligned "Generated: <now>"
        gen_label = f"Generated: {fmt_dt(gen_time)}"
        c.setFont("Helvetica", 9)
        gw = c.stringWidth(gen_label, "Helvetica", 9)
        c.drawString(A4[0] - PAGE_MARGIN_R - gw, A4[1] - 14.5 * mm, gen_label)

        # soft watermark
        try:
            c.setFillAlpha(0.04)
        except Exception:
            pass
        c.setFillColor(BRAND_PRIMARY)
        c.saveState()
        c.translate(A4[0] * 0.82, A4[1] * 0.22)
        c.rotate(22)
        c.setFont("Helvetica-Bold", 64)
        c.drawCentredString(0, 0, "FIJI FERRY")
        c.restoreState()
        try:
            c.setFillAlpha(1)
        except Exception:
            pass

        # footer
        c.setStrokeColor(BORDER)
        c.setLineWidth(0.6)
        c.line(PAGE_MARGIN_L, PAGE_MARGIN_B, A4[0]-PAGE_MARGIN_R, PAGE_MARGIN_B)
        c.setFillColor(TEXT_MUTED)
        c.setFont("Helvetica", 8.5)
        c.drawString(PAGE_MARGIN_L, PAGE_MARGIN_B - 6, "Present this boarding pass with a valid photo ID.")
        c.drawString(PAGE_MARGIN_L, PAGE_MARGIN_B - 18, "support@fijiferry.example • +679 738 8496")

        c.restoreState()

    class NumberedCanvas(pdfcanvas.Canvas):
        """Standard 'Page X of Y' canvas."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            self._saved_page_states.append(dict(self.__dict__))
            super().showPage()

        def save(self):
            num_pages = len(self._saved_page_states) + 1
            # add page numbers to each saved page state
            for i, state in enumerate(self._saved_page_states):
                self.__dict__.update(state)
                self._draw_page_number(i + 1, num_pages)
                super().showPage()
            # last (current) page
            self._draw_page_number(num_pages, num_pages)
            super().save()

        def _draw_page_number(self, page_num, total_pages):
            self.saveState()
            self.setFont("Helvetica", 8.5)
            label = f"Page {page_num} of {total_pages}"
            tw = self.stringWidth(label, "Helvetica", 8.5)
            self.setFillColor(TEXT_MUTED)
            self.drawString(A4[0] - PAGE_MARGIN_R - tw, PAGE_MARGIN_B - 18, label)
            self.restoreState()

    # ---------- Doc template ----------
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=PAGE_MARGIN_L,
        rightMargin=PAGE_MARGIN_R,
        topMargin=PAGE_MARGIN_T + 10 * mm,  # space for header band
        bottomMargin=PAGE_MARGIN_B + 6 * mm,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='content')
    doc.addPageTemplates([PageTemplate(id="ticket", frames=[frame], onPage=draw_header_footer)])

    # ---------- Flowables ----------
    story = []
    spacer_small = Spacer(0, 4*mm)
    spacer_med   = Spacer(0, 6*mm)
    spacer_large = Spacer(0, 10*mm)

    def kv_row(label, value):
        return [Paragraph(f"{label}:", styles["Key"]),
                Paragraph(value if value else "—", styles["Val"])]

    def route_pill(text, width_mm):
        tbl = Table([[Paragraph(text, styles["RoutePill"])]], colWidths=[width_mm], hAlign='LEFT')
        tbl.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), BRAND_PRIMARY),
            ('TEXTCOLOR', (0,0), (-1,-1), colors.white),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING',(0,0), (-1,-1), 8),
            ('TOPPADDING',  (0,0), (-1,-1), 3),
            ('BOTTOMPADDING',(0,0),(-1,-1), 3),
            ('BOX', (0,0), (-1,-1), 0, BRAND_PRIMARY),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ]))
        return tbl

    def qr_flowable(payload, size=46*mm):
        try:
            widget = rl_qr.QrCodeWidget(payload or "")
            b = widget.getBounds()
            w, h = b[2]-b[0], b[3]-b[1]
            d = Drawing(size, size, transform=[size/w, 0, 0, size/h, 0, 0])
            d.add(widget)
            return d
        except Exception:
            return Paragraph("QR unavailable", styles["SmallNote"])

    # Cards
    for t in tickets:
        # Top line: ticket number + Generated now (instead of "Issued" from the DB)
        top = Table(
            [[Paragraph(f"Ticket #{getattr(t,'id','—')}", styles["SectionLabel"]),
              Paragraph(f"Generated {fmt_dt(gen_time)}",
                        ParagraphStyle('MetaRight', parent=styles["SmallNote"], alignment=2))]],
            colWidths=[None, 60*mm],
            style=TableStyle([('VALIGN',(0,0),(-1,-1),'BOTTOM')])
        )
        story += [top, spacer_small]

        # Route pill
        sched = getattr(booking, 'schedule', None)
        dep = dest = "—"
        if sched and getattr(sched, 'route', None):
            dep = getattr(getattr(sched.route,'departure_port',None), 'name', '—') or '—'
            dest = getattr(getattr(sched.route,'destination_port',None), 'name', '—') or '—'
        route_txt = f"{dep} → {dest}"
        story += [route_pill(route_txt, 90*mm), spacer_med]

        # Passenger
        passenger = getattr(t, 'passenger', None)
        name = ptype = "—"
        if passenger:
            name = (f"{getattr(passenger,'first_name','') or ''} {getattr(passenger,'last_name','') or ''}").strip() or "—"
            ptype = getattr(passenger, 'get_passenger_type_display', lambda: "—")()

        seat = getattr(t, 'seat_number', None) or getattr(t, 'seat', None)
        status = getattr(t, 'ticket_status', None)
        status_txt = (status.title() if isinstance(status, str) else str(status or "—"))

        left_rows = [[Paragraph("Passenger", styles["SectionLabel"]), ""],
                     kv_row("Name", name),
                     kv_row("Type", ptype),
                     kv_row("Booking", f"#{booking.id}")]
        if seat:
            left_rows.append(kv_row("Seat", str(seat)))
        left_rows.append(kv_row("Status", status_txt))
        left_tbl = Table(left_rows, colWidths=[28*mm, 70*mm],
                         style=TableStyle([('SPAN',(0,0),(1,0)), ('VALIGN',(0,0),(-1,-1),'TOP')]))

        # Schedule + QR
        ferry_name = getattr(getattr(sched,'ferry',None), 'name', '—') if sched else '—'
        right_rows = [[Paragraph("Schedule", styles["SectionLabel"]), ""],
                      kv_row("Ferry", ferry_name),
                      kv_row("Route", route_txt),
                      kv_row("Departure", fmt_dt(getattr(sched,'departure_time',None) if sched else None)),
                      kv_row("Arrival",   fmt_dt(getattr(sched,'arrival_time',None) if sched else None))]
        right_tbl = Table(right_rows, colWidths=[28*mm, 60*mm],
                          style=TableStyle([('SPAN',(0,0),(1,0)), ('VALIGN',(0,0),(-1,-1),'TOP')]))

        qr = qr_flowable(f"FFB:{booking.id}:{getattr(t,'id','')}", 46*mm)
        qr_table = Table([[qr]], colWidths=[46*mm], rowHeights=[46*mm],
                         style=TableStyle([
                             ('BOX',(0,0),(-1,-1),0.8,BORDER),
                             ('LEFTPADDING',(0,0),(-1,-1),6),
                             ('RIGHTPADDING',(0,0),(-1,-1),6),
                             ('TOPPADDING',(0,0),(-1,-1),6),
                             ('BOTTOMPADDING',(0,0),(-1,-1),6),
                             ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                             ('ALIGN',(0,0),(-1,-1),'CENTER'),
                         ]))
        right_col = Table([[right_tbl], [Spacer(0, 4)], [qr_table], [Spacer(0, 2)], [Paragraph("Scan at check-in", styles["SmallNote"])]],
                          colWidths=[66*mm],
                          style=TableStyle([('VALIGN',(0,0),(-1,-1),'TOP')]))

        card = Table([[left_tbl, right_col]], colWidths=[100*mm, 66*mm],
                     style=TableStyle([
                         ('BOX',(0,0),(-1,-1),0.8,BORDER),
                         ('BACKGROUND',(0,0),(-1,-1),SURFACE),
                         ('LEFTPADDING',(0,0),(-1,-1),10),
                         ('RIGHTPADDING',(0,0),(-1,-1),10),
                         ('TOPPADDING',(0,0),(-1,-1),10),
                         ('BOTTOMPADDING',(0,0),(-1,-1),10),
                         ('VALIGN',(0,0),(-1,-1),'TOP'),
                     ]))
        story += [KeepTogether(card), Spacer(0, 8),
                  Paragraph("Valid only for listed passenger and sailing.", styles["SmallNote"]),
                  spacer_large]

    if not tickets:
        overview = Table(
            [[Paragraph("Booking Overview", styles["SectionLabel"]), ""],
             kv_row("Booking #", f"#{booking.id}"),
             kv_row("Contact", (getattr(getattr(booking,'user',None),'email',None)
                                or getattr(booking,'guest_email',None) or "—")),
             kv_row("Created", fmt_dt(getattr(booking,'created_at',None)))],
            colWidths=[28*mm, 120*mm],
            style=TableStyle([
                ('SPAN',(0,0),(1,0)),
                ('BOX',(0,0),(-1,-1),0.8,BORDER),
                ('LEFTPADDING',(0,0),(-1,-1),10),
                ('RIGHTPADDING',(0,0),(-1,-1),10),
                ('TOPPADDING',(0,0),(-1,-1),10),
                ('BOTTOMPADDING',(0,0),(-1,-1),10),
                ('VALIGN',(0,0),(-1,-1),'TOP'),
            ])
        )
        story.append(overview)

    # ---------- Build ----------
    doc.build(story, canvasmaker=NumberedCanvas)
    buf.seek(0)
    return FileResponse(buf, as_attachment=True,
                        filename=f"FijiFerry_Booking_{booking.id}_Tickets.pdf")
