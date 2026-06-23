import datetime
import logging

import stripe
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Schedule, Booking
from . import services

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY


@shared_task
def update_schedules_status():
    now = timezone.now()
    return Schedule.objects.filter(
        status='scheduled',
        departure_time__lt=now
    ).update(status='departed')


@shared_task
def expire_pending_bookings(max_age_minutes=30):
    """LOG-2: release seats held by abandoned 'pending' bookings.

    Delegates each booking to the service layer so the seat release and state
    transition are atomic and idempotent (safe to run concurrently with the
    user completing checkout).
    """
    cutoff = timezone.now() - datetime.timedelta(minutes=max_age_minutes)
    expired = 0
    ids = list(
        Booking.objects.filter(status='pending', booking_date__lt=cutoff)
        .values_list('id', flat=True)
    )
    for booking_id in ids:
        try:
            if services.expire_pending_booking(booking_id):
                expired += 1
        except Exception:
            logger.exception("Failed to expire pending booking %s", booking_id)
    return expired


@shared_task
def reconcile_pending_payments(max_age_minutes=5, lookback_hours=24):
    """Failure recovery: bookings stuck in 'pending' that actually paid.

    Covers the 'payment succeeded but confirmation never ran' case (browser
    closed before redirect AND webhook missed/misconfigured). For each recent
    pending booking with a Stripe session, ask Stripe for the truth and confirm
    via the service layer if the payment succeeded. Idempotent.
    """
    now = timezone.now()
    older_than = now - datetime.timedelta(minutes=max_age_minutes)
    lookback = now - datetime.timedelta(hours=lookback_hours)
    qs = Booking.objects.filter(
        status='pending',
        booking_date__lt=older_than,
        booking_date__gte=lookback,
        stripe_session_id__isnull=False,
    )
    confirmed = 0
    for booking in qs.iterator():
        try:
            session = stripe.checkout.Session.retrieve(
                booking.stripe_session_id, expand=['payment_intent']
            )
        except Exception:
            logger.exception("Reconcile: failed to retrieve session for booking %s", booking.id)
            continue
        pi = getattr(session, 'payment_intent', None)
        if pi and getattr(pi, 'status', None) == 'succeeded':
            try:
                from decimal import Decimal
                services.confirm_paid_booking(
                    booking.id,
                    session_id=session.id,
                    payment_intent_id=pi.id,
                    amount=Decimal(pi.amount) / 100,
                )
                confirmed += 1
                logger.info("Reconcile: confirmed previously-pending booking %s", booking.id)
            except Exception:
                logger.exception("Reconcile: failed to confirm booking %s", booking.id)
    return confirmed
