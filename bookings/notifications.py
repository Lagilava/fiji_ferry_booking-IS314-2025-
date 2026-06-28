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

    route = booking.schedule.route
    dep = route.departure_port.name
    dest = route.destination_port.name
    depart = timezone.localtime(booking.schedule.departure_time).strftime("%a, %b %d %Y at %H:%M")
    refunded = booking.payments.filter(payment_status="refunded").exists() if hasattr(booking, "payments") else False
    refund_line = (
        f"A refund of FJD {booking.total_price} has been issued to your original payment method "
        f"(allow 5–10 business days)."
        if refunded else
        "If you had paid, any refund will be processed to your original payment method."
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
def send_welcome_email(user):
    """Confirm a newly registered account to the user's email."""
    to = getattr(user, "email", None)
    if not to:
        return False
    name = user.first_name or user.username or "Traveller"
    site = getattr(settings, "SITE_URL", "").rstrip("/")
    subject = "Welcome to Fiji Ferry — your account is ready"
    text = (
        f"Bula {name},\n\n"
        f"Your Fiji Ferry account has been created successfully with this email address.\n\n"
        f"You can now book sailings, manage your trips, and receive booking confirmations here.\n"
        + (f"\nVisit: {site}\n" if site else "")
        + "\nIf you didn't create this account, please contact us immediately.\n\n"
        f"Vinaka,\nFiji Ferry"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:auto">
      <h2 style="color:#0e7490;margin:0 0 12px">Bula {name}, welcome aboard! ⚓</h2>
      <p>Your Fiji Ferry account has been created with <strong>{to}</strong>.</p>
      <p>You can now book sailings, manage your trips, and receive booking confirmations.</p>
      {f'<p><a href="{site}" style="background:#10b981;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Start booking</a></p>' if site else ''}
      <p style="color:#6b7280;font-size:13px">If you didn't create this account, please contact us immediately.</p>
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
        subject = f"{copy['subject']} — {dep} → {dest}"
        text = (
            f"Bula {_customer_name(booking)},\n\n"
            f"{copy['body']}\n\n"
            f"Booking ID: {booking.id}\n"
            f"Route: {dep} → {dest}\n"
            f"Scheduled departure: {depart}\n\n"
            f"{copy['action']}\n"
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
          {f'<p><a href="{manage}" style="background:#0e7490;color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none">Manage booking</a></p>' if manage else ''}
          <p>Vinaka,<br>Fiji Ferry</p>
        </div>
        """
        if _send(subject, text, [to], html):
            sent += 1
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


def _send(subject, text, recipients, html=None):
    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None)
    try:
        msg = EmailMultiAlternatives(subject, text, from_email, recipients)
        if html:
            msg.attach_alternative(html, "text/html")
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception("notifications: failed to send '%s' to %s", subject, recipients)
        return False
