"""Waitlist + smart rebooking policy.

Sold-out sailings accept waitlist entries (guests included, keyed by email).
Whenever inventory is returned to a sailing — a cancellation, an expired
pending booking, a downsized modification — ``process_waitlist`` offers the
freed seats to waiting customers in FIFO order. Seats are never held back for
the waitlist: the offer email is first-come, first-served, so inventory stays
honest and there is no hold/expiry state machine to reconcile.

When a whole sailing is cancelled, ``suggest_alternative`` finds the next
sailing on the same route with room for a booking, and the disruption email
carries a signed one-click "move my booking" link (see views.rebook_oneclick).
All senders are best-effort like the rest of notifications.py.
"""
import logging

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Signed one-click rebook links stop working after this many days.
REBOOK_LINK_MAX_AGE_DAYS = 7
REBOOK_SALT = 'bookings.rebook.oneclick'


def _site():
    return getattr(settings, 'SITE_URL', '').rstrip('/')


# --------------------------------------------------------------------------- #
# Joining / leaving
# --------------------------------------------------------------------------- #
def join_waitlist(schedule, email, seats_requested, user=None):
    """Create (or return the existing live) waitlist entry for this email.

    Returns (entry, created).
    """
    from .models import WaitlistEntry
    email = (email or '').strip().lower()
    existing = WaitlistEntry.objects.filter(
        schedule=schedule, email=email, status__in=['waiting', 'notified']
    ).first()
    if existing:
        return existing, False
    entry = WaitlistEntry.objects.create(
        schedule=schedule,
        user=user if (user and user.is_authenticated) else None,
        email=email,
        seats_requested=max(1, int(seats_requested or 1)),
    )
    logger.info("waitlist: %s joined schedule %s (x%s)", email, schedule.id, entry.seats_requested)
    return entry, True


def leave_waitlist(token):
    """Cancel the entry for ``token``. Returns the entry or None."""
    from .models import WaitlistEntry
    entry = WaitlistEntry.objects.filter(token=token).first()
    if entry and entry.status in ('waiting', 'notified'):
        entry.status = 'cancelled'
        entry.save(update_fields=['status'])
    return entry


# --------------------------------------------------------------------------- #
# Offering freed seats
# --------------------------------------------------------------------------- #
def process_waitlist(schedule_id):
    """Offer newly-freed seats to waiting customers, FIFO.

    Call after inventory has been returned to the schedule (post-commit).
    Marks matched entries 'notified' and emails them a booking link. Entries
    asking for more seats than are free stay 'waiting' (no head-of-line
    blocking for smaller parties behind them).
    """
    from .models import Schedule, WaitlistEntry

    try:
        schedule = Schedule.objects.select_related(
            'route__departure_port', 'route__destination_port', 'ferry'
        ).get(pk=schedule_id)
    except Schedule.DoesNotExist:
        return 0
    if schedule.status != 'scheduled' or schedule.departure_time <= timezone.now():
        return 0

    free = schedule.available_seats
    if free <= 0:
        return 0

    offered = 0
    entries = (
        WaitlistEntry.objects.filter(schedule=schedule, status='waiting')
        .order_by('created_at')
    )
    for entry in entries:
        if free <= 0:
            break
        if entry.seats_requested > free:
            continue  # try smaller parties further down the queue
        if _send_offer_email(entry, schedule):
            with transaction.atomic():
                updated = WaitlistEntry.objects.filter(
                    pk=entry.pk, status='waiting'
                ).update(status='notified', notified_at=timezone.now())
            if updated:
                offered += 1
                free -= entry.seats_requested
    if offered:
        logger.info("waitlist: offered seats to %s customer(s) on schedule %s", offered, schedule_id)
    return offered


def expire_waitlist_for_schedule(schedule, suggest=True):
    """Close out a cancelled/departed sailing's waitlist.

    Marks live entries 'expired' and (optionally) emails each an alternative
    sailing suggestion. Returns the number of entries closed.
    """
    from .models import WaitlistEntry
    entries = list(
        WaitlistEntry.objects.filter(schedule=schedule, status__in=['waiting', 'notified'])
    )
    if not entries:
        return 0
    alt = suggest_alternative(schedule, seats=1)
    for entry in entries:
        entry.status = 'expired'
        entry.save(update_fields=['status'])
        if suggest:
            _send_waitlist_cancelled_email(entry, schedule, alt)
    return len(entries)


def mark_converted(schedule, email):
    """Best-effort: flag this email's live entry as converted after they book."""
    from .models import WaitlistEntry
    if not email:
        return
    WaitlistEntry.objects.filter(
        schedule=schedule, email=email.strip().lower(), status__in=['waiting', 'notified']
    ).update(status='converted')


# --------------------------------------------------------------------------- #
# Smart rebooking (cancelled sailings)
# --------------------------------------------------------------------------- #
def suggest_alternative(schedule, seats=1, vehicles=0, cargo_kg=0):
    """Next sailing on the same route with room, or None."""
    from .models import Schedule
    return (
        Schedule.objects.filter(
            route=schedule.route,
            status='scheduled',
            departure_time__gt=timezone.now(),
            available_seats__gte=seats,
            available_vehicle_slots__gte=vehicles,
            available_cargo_kg__gte=cargo_kg or 0,
        )
        .exclude(pk=schedule.pk)
        .order_by('departure_time')
        .select_related('ferry', 'route__departure_port', 'route__destination_port')
        .first()
    )


def make_rebook_token(booking, new_schedule):
    """Signed, expiring token authorizing a free one-click move."""
    return signing.dumps({'b': booking.id, 's': new_schedule.id}, salt=REBOOK_SALT)


def read_rebook_token(token):
    """Return {'b': booking_id, 's': schedule_id} or raise signing.BadSignature."""
    return signing.loads(
        token, salt=REBOOK_SALT, max_age=REBOOK_LINK_MAX_AGE_DAYS * 86400
    )


def rebook_offer_for(booking):
    """(alternative_schedule, one_click_url) for a disrupted booking, or (None, '')."""
    from .services import passenger_count
    from django.db.models import Sum
    from decimal import Decimal
    seats = passenger_count(booking)
    vehicles = booking.vehicles.count()
    cargo_kg = booking.cargo.aggregate(t=Sum('weight_kg'))['t'] or Decimal('0')
    alt = suggest_alternative(booking.schedule, seats=seats, vehicles=vehicles, cargo_kg=cargo_kg)
    if not alt:
        return None, ''
    site = _site()
    url = reverse('bookings:rebook_oneclick', args=[make_rebook_token(booking, alt)])
    return alt, f"{site}{url}" if site else url


# --------------------------------------------------------------------------- #
# Emails
# --------------------------------------------------------------------------- #
def _fmt(dt):
    return timezone.localtime(dt).strftime("%a, %b %d %Y at %H:%M")


def _send_offer_email(entry, schedule):
    from .notifications import _send
    route = schedule.route
    dep, dest = route.departure_port.name, route.destination_port.name
    site = _site()
    book_url = f"{site}{reverse('bookings:book_ticket')}?schedule_id={schedule.id}&passengers={entry.seats_requested}"
    leave_url = f"{site}{reverse('bookings:waitlist_leave', args=[entry.token])}"

    subject = f"Seats just opened up — {dep} → {dest}"
    text = (
        f"Bula,\n\n"
        f"Good news! Seats have become available on the sailing you were waitlisted for:\n\n"
        f"Route: {dep} → {dest}\n"
        f"Ferry: {schedule.ferry.name}\n"
        f"Departure: {_fmt(schedule.departure_time)}\n"
        f"Seats you asked for: {entry.seats_requested}\n\n"
        f"Seats are first-come, first-served — book now:\n{book_url}\n\n"
        f"No longer travelling? Leave the waitlist: {leave_url}\n\n"
        f"Vinaka,\nFiji Ferry"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:auto">
      <h2 style="color:#047857;margin:0 0 12px">Seats just opened up! ⛴️</h2>
      <p>Bula, seats have become available on the sailing you were waitlisted for:</p>
      <table style="border-collapse:collapse;width:100%;font-size:14px">
        <tr><td style="padding:8px;color:#6b7280">Route</td><td style="padding:8px">{dep} → {dest}</td></tr>
        <tr><td style="padding:8px;color:#6b7280">Ferry</td><td style="padding:8px">{schedule.ferry.name}</td></tr>
        <tr><td style="padding:8px;color:#6b7280">Departure</td><td style="padding:8px">{_fmt(schedule.departure_time)}</td></tr>
        <tr><td style="padding:8px;color:#6b7280">Seats requested</td><td style="padding:8px">{entry.seats_requested}</td></tr>
      </table>
      <p style="margin-top:14px">Seats are <strong>first-come, first-served</strong> — grab yours now:</p>
      <p><a href="{book_url}" style="background:#10b981;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600">Book my seats</a></p>
      <p style="color:#6b7280;font-size:13px">No longer travelling? <a href="{leave_url}">Leave the waitlist</a>.</p>
      <p>Vinaka,<br>Fiji Ferry</p>
    </div>
    """
    return _send(subject, text, [entry.email], html)


def _send_waitlist_cancelled_email(entry, schedule, alt):
    from .notifications import _send
    route = schedule.route
    dep, dest = route.departure_port.name, route.destination_port.name
    site = _site()

    if alt:
        alt_line = (
            f"The next available sailing on this route departs {_fmt(alt.departure_time)} "
            f"on {alt.ferry.name}."
        )
        book_url = f"{site}{reverse('bookings:book_ticket')}?schedule_id={alt.id}&passengers={entry.seats_requested}"
        cta = f'<p><a href="{book_url}" style="background:#0e7490;color:#fff;padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:600">Book the next sailing</a></p>'
        text_cta = f"Book it here: {book_url}\n"
    else:
        alt_line = "There is no alternative sailing on this route yet — please check back soon."
        cta, text_cta = '', ''

    subject = f"Sailing cancelled — {dep} → {dest} (you were on the waitlist)"
    text = (
        f"Bula,\n\n"
        f"The sailing you were waitlisted for ({dep} → {dest}, "
        f"{_fmt(schedule.departure_time)}) has been cancelled.\n\n"
        f"{alt_line}\n{text_cta}\nVinaka,\nFiji Ferry"
    )
    html = f"""
    <div style="font-family:Inter,Arial,sans-serif;max-width:560px;margin:auto">
      <h2 style="color:#b91c1c;margin:0 0 12px">That sailing was cancelled</h2>
      <p>Bula, the sailing you were waitlisted for ({dep} → {dest},
         {_fmt(schedule.departure_time)}) has been cancelled.</p>
      <p>{alt_line}</p>
      {cta}
      <p>Vinaka,<br>Fiji Ferry</p>
    </div>
    """
    return _send(subject, text, [entry.email], html)
