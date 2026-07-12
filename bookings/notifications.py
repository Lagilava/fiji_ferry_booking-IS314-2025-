"""Central email notifications: customer booking emails + admin operational alerts.

Kept in one place so every notification uses the same from-address, logging, and
failure handling. All senders are best-effort: a mail failure is logged but never
propagates (a down SMTP server must not break a booking cancellation or a Celery
task).
"""
import logging

from django.conf import settings
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives, send_mail
from django.utils import timezone

logger = logging.getLogger(__name__)


def _booking_recipient(booking):
    """Best email for a booking: the account email, else the guest email."""
    if getattr(booking, "user", None) and booking.user.email:
        return booking.user.email
    return getattr(booking, "guest_email", None)


def _customer_name(booking):
    if getattr(booking, "user", None) and (booking.user.first_name or booking.user.username):
        return booking.user.first_name or booking.user.username
    return "Traveller"


# --------------------------------------------------------------------------- #
# Customer: booking cancellation
# --------------------------------------------------------------------------- #
def send_booking_cancellation_email(booking):
    """Notify the customer their booking was cancelled (and refunded if paid)."""
    to = _booking_recipient(booking)
    if not to:
        return False

    from decimal import Decimal
    from django.db.models import Sum
    route = booking.schedule.route
    dep = route.departure_port.name
    dest = route.destination_port.name
    depart = timezone.localtime(booking.schedule.departure_time).strftime("%a, %b %d %Y at %H:%M")
    # Actual refunded amount per the tiered policy (sum of refund Payment rows).
    refunded_total = abs(
        booking.payments.filter(payment_status="refunded").aggregate(t=Sum("amount"))["t"] or Decimal("0")
    )
    if refunded_total > 0:
        refund_line = (
            f"A refund of FJD {refunded_total} has been issued to your original payment method "
            f"(allow 5–10 business days)."
        )
    else:
        refund_line = (
            "As per our cancellation policy, no refund applies for this cancellation "
            "(cancelled close to departure). Contact us if you believe this is in error."
        )

    subject = f"Booking #{booking.id} cancelled — Fiji Ferry"
    text = (
        f"Bula {_customer_name(booking)},\n\n"
        f"Your booking has been cancelled.\n\n"
        f"Booking ID: {booking.id}\n"
        f"Route: {dep} → {dest}\n"
        f"Departure: {depart}\n\n"
        f"{refund_line}\n\n"
        f"If this wasn't you, please contact us right away.\n\n"
        f"Vinaka,\nFiji Ferry"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:auto">
      <h2 style="color:#b91c1c;margin:0 0 12px">Booking cancelled</h2>
      <p>Bula {_customer_name(booking)}, your booking has been cancelled.</p>
      <table style="border-collapse:collapse;width:100%;font-size:14px">
        <tr><td style="padding:8px;color:#6b7280">Booking ID</td><td style="padding:8px">#{booking.id}</td></tr>
        <tr><td style="padding:8px;color:#6b7280">Route</td><td style="padding:8px">{dep} → {dest}</td></tr>
        <tr><td style="padding:8px;color:#6b7280">Departure</td><td style="padding:8px">{depart}</td></tr>
      </table>
      <p style="margin-top:14px">{refund_line}</p>
      <p style="color:#6b7280;font-size:13px">If this wasn't you, please contact us right away.</p>
      <p>Vinaka,<br>Fiji Ferry</p>
    </div>
    """
    return _send(subject, text, [to], html)


# --------------------------------------------------------------------------- #
# Customer: registration welcome / confirmation
# --------------------------------------------------------------------------- #
def send_welcome_email(user, verify_url=None):
    """Welcome a newly registered account and (optionally) ask them to verify
    their email via a one-click link."""
    to = getattr(user, "email", None)
    if not to:
        return False
    name = user.first_name or user.username or "Traveller"
    site = getattr(settings, "SITE_URL", "").rstrip("/")
    subject = "Welcome to Fiji Ferry — please confirm your email"

    verify_text = f"\nConfirm your email address: {verify_url}\n" if verify_url else ""
    text = (
        f"Bula {name},\n\n"
        f"Your Fiji Ferry account has been created with this email address.\n\n"
        f"You can already book sailings and manage trips — but please confirm your "
        f"email so we know it's really you.\n"
        + verify_text
        + (f"\nVisit: {site}\n" if site and not verify_url else "")
        + "\nIf you didn't create this account, please ignore this email.\n\n"
        f"Vinaka,\nFiji Ferry"
    )
    verify_btn = (
        f'<p><a href="{verify_url}" style="background:#10b981;color:#fff;padding:10px 18px;'
        f'border-radius:8px;text-decoration:none">Confirm my email</a></p>'
        if verify_url else
        (f'<p><a href="{site}" style="background:#10b981;color:#fff;padding:10px 18px;'
         f'border-radius:8px;text-decoration:none">Start booking</a></p>' if site else '')
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:auto">
      <h2 style="color:#0e7490;margin:0 0 12px">Bula {name}, welcome aboard! ⚓</h2>
      <p>Your Fiji Ferry account has been created with <strong>{to}</strong>.</p>
      <p>You can already book and manage trips. Please confirm your email so we know it's really you:</p>
      {verify_btn}
      <p style="color:#6b7280;font-size:13px">If you didn't create this account, please ignore this email.</p>
      <p>Vinaka,<br>Fiji Ferry</p>
    </div>
    """
    return _send(subject, text, [to], html)


# --------------------------------------------------------------------------- #
# Customer: schedule disruption (delay / cancellation / weather hold)
# --------------------------------------------------------------------------- #
_DISRUPTION_COPY = {
    "delayed": {
        "subject": "Your sailing is delayed",
        "headline": "Your sailing has been delayed",
        "color": "#d97706",
        "body": "Your upcoming sailing has been delayed. We're working to confirm a new "
                "departure time and will update you as soon as it's set.",
        "action": "We'll notify you of the new time. No action is needed right now.",
    },
    "cancelled": {
        "subject": "Your sailing has been cancelled",
        "headline": "Your sailing has been cancelled",
        "color": "#b91c1c",
        "body": "Unfortunately your upcoming sailing has been cancelled.",
        "action": "Please rebook an alternative sailing, or reply to this email and our "
                  "team will help arrange a rebooking or refund.",
    },
    "weather_hold": {
        "subject": "Weather alert for your sailing",
        "headline": "Your sailing is under weather review",
        "color": "#b45309",
        "body": "Due to forecast weather conditions, your upcoming sailing is under review "
                "and may be delayed or cancelled for safety.",
        "action": "No action is needed yet — we'll confirm the final decision soon. Watch "
                  "your email for updates.",
    },
}


def notify_schedule_disruption(schedule, kind):
    """Email every customer with an active booking on `schedule` about a
    disruption. `kind` is one of: 'delayed', 'cancelled', 'weather_hold'.

    Returns the number of emails sent. Best-effort and idempotent-safe to call
    on each status change.
    """
    copy = _DISRUPTION_COPY.get(kind)
    if copy is None:
        return 0

    from .models import Booking
    route = schedule.route
    dep = route.departure_port.name
    dest = route.destination_port.name
    depart = timezone.localtime(schedule.departure_time).strftime("%a, %b %d %Y at %H:%M")
    site = getattr(settings, "SITE_URL", "").rstrip("/")
    manage = f"{site}/bookings/history/" if site else ""

    bookings = (
        Booking.objects.filter(schedule=schedule, status__in=["pending", "confirmed"])
        .select_related("user")
    )
    sent = 0
    for booking in bookings:
        to = _booking_recipient(booking)
        if not to:
            continue

        # For cancellations, offer a free one-click move to the next sailing
        # on the same route that fits this booking (seats/vehicles/cargo).
        rebook_html = rebook_text = ""
        if kind == "cancelled":
            try:
                from .waitlist import rebook_offer_for
                alt, one_click_url = rebook_offer_for(booking)
            except Exception:
                logger.exception("Failed to build rebook offer for booking %s", booking.id)
                alt, one_click_url = None, ""
            if alt and one_click_url:
                alt_depart = timezone.localtime(alt.departure_time).strftime("%a, %b %d %Y at %H:%M")
                rebook_text = (
                    f"\nGood news — {alt.ferry.name} sails the same route on {alt_depart} "
                    f"and has room for your whole party. Move your booking to it free of "
                    f"charge with one click:\n{one_click_url}\n"
                )
                rebook_html = f"""
          <div style="background:#ecfdf5;border:1px solid #6ee7b7;border-radius:10px;padding:14px 16px;margin:14px 0">
            <p style="margin:0 0 10px"><strong>Good news:</strong> {alt.ferry.name} sails the same route on
               <strong>{alt_depart}</strong> and has room for your whole party.</p>
            <a href="{one_click_url}" style="background:#10b981;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600">Move my booking — free</a>
          </div>"""

        subject = f"{copy['subject']} — {dep} → {dest}"
        text = (
            f"Bula {_customer_name(booking)},\n\n"
            f"{copy['body']}\n\n"
            f"Booking ID: {booking.id}\n"
            f"Route: {dep} → {dest}\n"
            f"Scheduled departure: {depart}\n\n"
            f"{copy['action']}\n"
            + rebook_text
            + (f"\nManage your booking: {manage}\n" if manage else "")
            + "\nVinaka,\nFiji Ferry"
        )
        html = f"""
        <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:auto">
          <h2 style="color:{copy['color']};margin:0 0 12px">{copy['headline']}</h2>
          <p>Bula {_customer_name(booking)}, {copy['body']}</p>
          <table style="border-collapse:collapse;width:100%;font-size:14px">
            <tr><td style="padding:8px;color:#6b7280">Booking ID</td><td style="padding:8px">#{booking.id}</td></tr>
            <tr><td style="padding:8px;color:#6b7280">Route</td><td style="padding:8px">{dep} → {dest}</td></tr>
            <tr><td style="padding:8px;color:#6b7280">Scheduled departure</td><td style="padding:8px">{depart}</td></tr>
          </table>
          <p style="margin-top:14px">{copy['action']}</p>
          {rebook_html}
          {f'<p><a href="{manage}" style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Manage booking</a></p>' if manage else ''}
          <p>Vinaka,<br>Fiji Ferry</p>
        </div>
        """
        if _send(subject, text, [to], html):
            sent += 1
    if kind == "cancelled":
        # Close out the sailing's waitlist too (suggests the next sailing).
        try:
            from .waitlist import expire_waitlist_for_schedule
            expire_waitlist_for_schedule(schedule)
        except Exception:
            logger.exception("Failed to expire waitlist for schedule %s", schedule.id)

    if sent:
        logger.info("notifications: sent %s '%s' disruption email(s) for schedule %s",
                    sent, kind, schedule.id)
    return sent


# --------------------------------------------------------------------------- #
# Admin: operational alerts
# --------------------------------------------------------------------------- #
def send_admin_alert(subject, message, *, html=None, throttle_key=None, throttle_seconds=0):
    """Email the operations admin. Optionally throttle noisy alerts via cache.

    `throttle_key` + `throttle_seconds` suppress repeat sends within the window
    (e.g. don't email on every failing automation cycle).
    """
    to = getattr(settings, "ADMIN_EMAIL", None)
    if not to:
        return False
    if throttle_key and throttle_seconds:
        if cache.get(throttle_key):
            return False
        cache.set(throttle_key, 1, throttle_seconds)
    return _send(f"[Fiji Ferry Ops] {subject}", message, [to], html)


def send_modification_confirmation_email(booking, amount=None):
    """Confirm a paid booking modification and attach the regenerated tickets.

    Sent after the modification balance settles, so the attached PDF already
    reflects the new passenger roster (added passengers have Ticket rows by
    then, and the PDF is rendered from the live roster rather than a snapshot).
    """
    to = _booking_recipient(booking)
    if not to:
        logger.warning("No recipient for modification email, booking %s", booking.id)
        return False

    route = booking.schedule.route
    dep, dest = route.departure_port.name, route.destination_port.name
    depart = timezone.localtime(booking.schedule.departure_time).strftime("%a, %b %d %Y at %H:%M")
    name = _customer_name(booking)

    passengers = list(booking.passengers.all())
    roster = "".join(
        f"<tr><td style='padding:8px 12px;border:1px solid #eef2f7;background:#f9fafb;'>"
        f"{p.get_full_name()}</td>"
        f"<td style='padding:8px 12px;border:1px solid #eef2f7;background:#f9fafb;'>"
        f"{p.get_passenger_type_display()}</td></tr>"
        for p in passengers
    )
    paid_line = (
        f"<p style='margin:0 0 6px;'>Amount paid today: "
        f"<strong>FJD {amount:.2f}</strong></p>" if amount is not None else ""
    )

    counts = (
        f"{booking.passenger_adults} adult(s), "
        f"{booking.passenger_children} child(ren), "
        f"{booking.passenger_infants} infant(s)"
    )

    text = (
        f"Hi {name},\n\n"
        f"Your booking #{booking.id} has been updated and your payment received.\n\n"
        f"Trip: {dep} to {dest}\nDeparts: {depart}\n"
        f"Passengers: {counts}\nBooking total: FJD {booking.total_price}\n\n"
        f"Your updated tickets are attached as a PDF. Every passenger now has a "
        f"valid boarding pass with its own QR code.\n\n"
        f"Please arrive at least 45 minutes before departure with valid photo ID.\n\n"
        f"Vinaka, and safe travels,\nFiji Ferry Service"
    )

    html = f"""\
<!doctype html>
<html><body style="margin:0;padding:24px;background:#f1f5f9;font-family:Segoe UI,Arial,sans-serif;color:#0f172a;">
  <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;border:1px solid #e2e8f0;">
    <div style="background:linear-gradient(135deg,#0A2540,#0E7490);padding:26px 28px;color:#fff;">
      <div style="font-size:12px;letter-spacing:.12em;text-transform:uppercase;opacity:.85;">Booking updated</div>
      <div style="font-size:23px;font-weight:700;margin-top:4px;">Booking #{booking.id}</div>
    </div>
    <div style="padding:26px 28px;">
      <p style="margin:0 0 16px;">Hi {name}, your payment went through and your booking is updated.</p>

      <div style="background:#ecfdf5;border:1px solid #6ee7b7;border-radius:10px;padding:14px 16px;margin-bottom:20px;">
        {paid_line}
        <p style="margin:0;">Your <strong>updated tickets are attached</strong> to this email as a PDF.</p>
      </div>

      <h3 style="font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;margin:0 0 10px;">Your trip</h3>
      <p style="margin:0 0 4px;font-size:18px;font-weight:700;">{dep} &rarr; {dest}</p>
      <p style="margin:0 0 20px;color:#475569;">{depart}</p>

      <h3 style="font-size:14px;text-transform:uppercase;letter-spacing:.08em;color:#64748b;margin:0 0 10px;">Passengers</h3>
      <table style="width:100%;border-collapse:collapse;margin-bottom:20px;font-size:14px;">{roster}</table>

      <div style="display:flex;justify-content:space-between;border-top:2px solid #0EA5E9;padding-top:12px;font-weight:700;">
        <span>Booking total</span><span>FJD {booking.total_price}</span>
      </div>
    </div>
    <div style="padding:18px 28px;background:#f8fafc;border-top:1px solid #e2e8f0;font-size:12px;color:#64748b;">
      Please arrive at least 45 minutes before departure with valid photo ID.<br>
      Need help? support@fijiferrybooking.com &bull; +679 738 8496
    </div>
  </div>
</body></html>"""

    attachments = []
    try:
        from .models import Ticket
        from .pdf import booking_pdf_bytes
        tickets = list(Ticket.objects.filter(booking=booking).select_related("passenger"))
        attachments.append((
            f"FijiFerry_Booking_{booking.id}_Tickets.pdf",
            booking_pdf_bytes(booking, tickets),
            "application/pdf",
        ))
    except Exception:
        # Never lose the confirmation just because the PDF failed to render.
        logger.exception("Failed to attach updated ticket PDF for booking %s", booking.id)

    return _send(
        f"Your updated Fiji Ferry tickets — Booking #{booking.id}",
        text, [to], html=html, attachments=attachments,
    )


def _send(subject, text, recipients, html=None, attachments=None):
    """Send an email. ``attachments`` is a list of (filename, content, mimetype)."""
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)
    try:
        msg = EmailMultiAlternatives(subject, text, from_email, recipients)
        if html:
            msg.attach_alternative(html, "text/html")
        for name, content, mimetype in (attachments or []):
            msg.attach(name, content, mimetype)
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("notifications: failed to send '%s' to %s", subject, recipients)
        return False
