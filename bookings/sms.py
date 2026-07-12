"""SMS + WhatsApp notifications via Twilio's REST API.

Why this exists
---------------
In Fiji, SMS and WhatsApp reach travellers far more reliably than email. Every
customer-facing email in :mod:`bookings.notifications` has an optional SMS/
WhatsApp counterpart routed through here so disruption alerts, refunds, and
boarding reminders actually land on the phone in someone's pocket.

Design guarantees
-----------------
* **Best-effort, never fatal.** A messaging failure (or missing config) is logged
  and swallowed — it must never break a booking cancellation or a Celery task.
* **No new dependency.** We call Twilio's HTTPS API with ``requests`` (already a
  project dependency) instead of pulling in the Twilio SDK.
* **No-op when unconfigured.** With no ``TWILIO_*`` settings the module quietly
  disables itself, so local/dev and CI never try to send real messages.
* **E.164 normalisation** with a configurable default country (Fiji, +679) so
  locally-entered numbers like ``9992222`` still resolve to a sendable address.
"""
import logging
import re

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


def is_configured() -> bool:
    """True when Twilio credentials and at least one sender are present."""
    return bool(
        getattr(settings, "TWILIO_ACCOUNT_SID", "")
        and getattr(settings, "TWILIO_AUTH_TOKEN", "")
        and (getattr(settings, "TWILIO_SMS_FROM", "") or getattr(settings, "TWILIO_WHATSAPP_FROM", ""))
    )


def normalize_phone(raw: str) -> str | None:
    """Return an E.164 phone number (``+6799990000``) or ``None`` if unusable.

    Bare local numbers are prefixed with the configured default country code
    (``SMS_DEFAULT_COUNTRY_CODE``, defaulting to Fiji's +679).
    """
    if not raw:
        return None
    raw = raw.strip()
    had_plus = raw.startswith("+")
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if had_plus:
        return "+" + digits
    cc = str(getattr(settings, "SMS_DEFAULT_COUNTRY_CODE", "679"))
    # Already includes the country code (e.g. "6799990000").
    if digits.startswith(cc):
        return "+" + digits
    return "+" + cc + digits


def _post(payload) -> bool:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", "")
    token = getattr(settings, "TWILIO_AUTH_TOKEN", "")
    try:
        resp = requests.post(
            _TWILIO_API.format(sid=sid),
            data=payload,
            auth=(sid, token),
            timeout=getattr(settings, "SMS_TIMEOUT", 10),
        )
        if resp.status_code >= 400:
            logger.warning("sms: Twilio rejected message (%s): %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception:
        logger.exception("sms: failed to reach Twilio")
        return False


def send_sms(to: str, body: str) -> bool:
    """Send a plain SMS. Best-effort; returns True only on accepted delivery."""
    if not is_configured():
        logger.debug("sms: not configured, skipping SMS to %s", to)
        return False
    sender = getattr(settings, "TWILIO_SMS_FROM", "")
    if not sender:
        return False
    dest = normalize_phone(to)
    if not dest:
        return False
    return _post({"To": dest, "From": sender, "Body": body})


def send_whatsapp(to: str, body: str) -> bool:
    """Send a WhatsApp message via Twilio. Best-effort."""
    if not is_configured():
        logger.debug("sms: not configured, skipping WhatsApp to %s", to)
        return False
    sender = getattr(settings, "TWILIO_WHATSAPP_FROM", "")
    if not sender:
        return False
    dest = normalize_phone(to)
    if not dest:
        return False
    return _post({"To": f"whatsapp:{dest}", "From": f"whatsapp:{sender}", "Body": body})


def notify(to: str, body: str) -> bool:
    """Send over the preferred channel(s).

    Routes to WhatsApp and/or SMS depending on which senders are configured,
    controlled by ``SMS_CHANNELS`` (default ``"sms"``; may be ``"whatsapp"`` or
    ``"both"``). Returns True if any channel accepted the message.
    """
    channels = str(getattr(settings, "SMS_CHANNELS", "sms")).lower()
    sent = False
    if channels in ("whatsapp", "both"):
        sent = send_whatsapp(to, body) or sent
    if channels in ("sms", "both"):
        sent = send_sms(to, body) or sent
    return sent


def booking_phone(booking) -> str | None:
    """Best contact number for a booking.

    Prefers the account's phone, then the group leader / first passenger with a
    number on file. Returns ``None`` when nothing sendable exists.
    """
    user = getattr(booking, "user", None)
    if user is not None and getattr(user, "phone_number", ""):
        return user.phone_number
    leader = getattr(booking, "group_leader", None)
    if leader is not None and getattr(leader, "phone", ""):
        return leader.phone
    for p in booking.passengers.all():
        if getattr(p, "phone", ""):
            return p.phone
    return None
