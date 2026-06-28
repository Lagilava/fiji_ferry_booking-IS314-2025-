"""Authoritative service layer for money- and inventory-critical operations.

All seat-inventory mutations, booking state transitions, payment confirmation,
and cancellation/refund flows go through this module. Views handle HTTP and
input mapping only; they must not mutate Booking.status / Payment.payment_status
or Schedule.available_seats directly.

Design guarantees
-----------------
* Concurrency: seat reservation and state transitions take a row-level lock
  (SELECT ... FOR UPDATE) on the affected Schedule/Booking row, and inventory is
  changed with atomic ``F()`` expressions. Two concurrent callers serialize on
  the locked row, so overbooking and double-refund races are eliminated under
  READ COMMITTED (MySQL/InnoDB default) or stricter.
* Idempotency: payment confirmation keys off the unique (booking, session_id)
  Payment row; cancellation keys off the booking's terminal state under lock;
  refunds carry a Stripe ``idempotency_key``. Re-delivery / retries are safe.
* State integrity: ``transition_booking`` rejects illegal transitions, so there
  is no bypass path to 'confirmed' or 'cancelled'.
"""

import logging
from decimal import Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from .models import Booking, Schedule, Payment

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


# --------------------------------------------------------------------------- #
# State model
# --------------------------------------------------------------------------- #
class BookingStatus:
    PENDING = 'pending'        # created, seats reserved, awaiting payment (a.k.a. RESERVED)
    CONFIRMED = 'confirmed'    # payment completed
    CANCELLED = 'cancelled'    # released (optionally refunded)


class PaymentStatus:
    PENDING = 'pending'
    COMPLETED = 'completed'
    FAILED = 'failed'
    REFUNDED = 'refunded'


# Allowed Booking.status transitions. Anything not listed is rejected.
ALLOWED_BOOKING_TRANSITIONS = {
    BookingStatus.PENDING: {BookingStatus.PENDING, BookingStatus.CONFIRMED, BookingStatus.CANCELLED},
    BookingStatus.CONFIRMED: {BookingStatus.CONFIRMED, BookingStatus.CANCELLED},
    BookingStatus.CANCELLED: {BookingStatus.CANCELLED},  # terminal
}


class InvalidTransition(Exception):
    """Raised when an illegal booking state transition is attempted."""


def transition_booking(booking, new_status, *, extra_fields=None, save=True):
    """Validate and apply a Booking.status transition.

    Raises InvalidTransition for illegal moves (e.g. cancelled -> confirmed).
    A no-op transition (old == new) is allowed and idempotent.
    """
    old = booking.status
    allowed = ALLOWED_BOOKING_TRANSITIONS.get(old, set())
    if new_status not in allowed:
        raise InvalidTransition(f"Illegal booking transition {old!r} -> {new_status!r}")
    booking.status = new_status
    if save:
        fields = set(extra_fields or [])
        fields.add('status')
        booking.save(update_fields=list(fields)) if booking.pk else booking.save()
    return booking


# --------------------------------------------------------------------------- #
# Seat inventory primitives  (callers MUST already be inside transaction.atomic)
# --------------------------------------------------------------------------- #
def reserve_seats(schedule_id, qty):
    """Atomically reserve ``qty`` seats on a schedule under a row lock.

    Returns True if reserved, False if insufficient availability. Must be called
    inside transaction.atomic(); the SELECT ... FOR UPDATE serializes concurrent
    reservations so no two callers can both pass the availability check.
    """
    if qty <= 0:
        return True
    locked = Schedule.objects.select_for_update().get(pk=schedule_id)
    if locked.available_seats < qty:
        return False
    Schedule.objects.filter(pk=schedule_id).update(available_seats=F('available_seats') - qty)
    return True


def release_seats(schedule_id, qty):
    """Atomically return ``qty`` seats to a schedule."""
    if qty and schedule_id:
        Schedule.objects.filter(pk=schedule_id).update(available_seats=F('available_seats') + qty)


def passenger_count(booking):
    return (booking.passenger_adults or 0) + (booking.passenger_children or 0) + (booking.passenger_infants or 0)


def reserve_vehicle_slots(schedule_id, count):
    """Atomically reserve ``count`` vehicle slots under a row lock.

    Returns True if reserved, False if insufficient. Call inside transaction.atomic().
    """
    if count <= 0:
        return True
    locked = Schedule.objects.select_for_update().get(pk=schedule_id)
    if locked.available_vehicle_slots < count:
        return False
    Schedule.objects.filter(pk=schedule_id).update(
        available_vehicle_slots=F('available_vehicle_slots') - count
    )
    return True


def release_vehicle_slots(schedule_id, count):
    """Atomically return ``count`` vehicle slots to a schedule."""
    if count and schedule_id:
        Schedule.objects.filter(pk=schedule_id).update(
            available_vehicle_slots=F('available_vehicle_slots') + count
        )


def reserve_cargo(schedule_id, weight_kg):
    """Atomically reserve ``weight_kg`` of cargo capacity under a row lock.

    Returns True if reserved, False if insufficient. Call inside transaction.atomic().
    """
    weight_kg = Decimal(weight_kg or 0)
    if weight_kg <= 0:
        return True
    locked = Schedule.objects.select_for_update().get(pk=schedule_id)
    if locked.available_cargo_kg < weight_kg:
        return False
    Schedule.objects.filter(pk=schedule_id).update(
        available_cargo_kg=F('available_cargo_kg') - weight_kg
    )
    return True


def release_cargo(schedule_id, weight_kg):
    """Atomically return ``weight_kg`` of cargo capacity to a schedule."""
    weight_kg = Decimal(weight_kg or 0)
    if weight_kg > 0 and schedule_id:
        Schedule.objects.filter(pk=schedule_id).update(
            available_cargo_kg=F('available_cargo_kg') + weight_kg
        )


# --------------------------------------------------------------------------- #
# Payment confirmation  (idempotent)
# --------------------------------------------------------------------------- #
@transaction.atomic
def confirm_paid_booking(booking_id, *, session_id, payment_intent_id, amount):
    """Confirm a booking after a successful Stripe payment. Idempotent.

    Safe to call from both the webhook and the success redirect, and safe to
    call repeatedly (Stripe re-delivers webhooks). The booking row is locked and
    the Payment row is keyed on the unique (booking, session_id) pair.
    """
    booking = Booking.objects.select_for_update().get(pk=booking_id)

    payment, _created = Payment.objects.get_or_create(
        booking=booking,
        session_id=session_id,
        defaults={
            'payment_method': 'stripe',
            'amount': amount,
            'payment_status': PaymentStatus.PENDING,
        },
    )
    payment.payment_intent_id = payment_intent_id
    payment.transaction_id = payment_intent_id
    payment.amount = amount
    payment.payment_status = PaymentStatus.COMPLETED
    payment.save()

    booking.payment_intent_id = payment_intent_id
    booking.stripe_session_id = session_id
    if booking.status != BookingStatus.CONFIRMED:
        transition_booking(
            booking, BookingStatus.CONFIRMED,
            extra_fields=['payment_intent_id', 'stripe_session_id'],
        )
    else:
        booking.save(update_fields=['payment_intent_id', 'stripe_session_id'])
    return booking


# --------------------------------------------------------------------------- #
# Mock / local payment confirmation  (idempotent)
# --------------------------------------------------------------------------- #
# Fiji-local payment rails offered as genuine-looking mock gateways. These do not
# move real money; they confirm the booking exactly like Stripe does (same state
# machine, same idempotency guarantees) so the rest of the system is unaffected.
MOCK_PAYMENT_PROVIDERS = {
    'anz':    'ANZ Fiji',
    'bsp':    'BSP',
    'mpaisa': 'Vodafone M-PAiSA',
    'mycash': 'Digicel MyCash',
    'card':   'Card',
}


@transaction.atomic
def confirm_mock_payment(booking_id, *, provider, reference, amount):
    """Confirm a booking paid through a mock Fiji-local gateway. Idempotent.

    Mirrors ``confirm_paid_booking`` but for non-Stripe rails: a ``local`` Payment
    row keyed on the unique (booking, session_id=reference) pair, the booking row
    locked for the transition. Safe to call repeatedly (e.g. a refreshed return
    page) — the second call is a no-op once the booking is confirmed.
    """
    if provider not in MOCK_PAYMENT_PROVIDERS:
        raise ValueError(f"Unknown mock payment provider {provider!r}")

    booking = Booking.objects.select_for_update().get(pk=booking_id)

    payment, _created = Payment.objects.get_or_create(
        booking=booking,
        session_id=reference,
        defaults={
            'payment_method': 'local',
            'amount': amount,
            'payment_status': PaymentStatus.PENDING,
        },
    )
    payment.transaction_id = reference
    payment.amount = amount
    payment.payment_status = PaymentStatus.COMPLETED
    payment.save()

    # Store the reference on the booking so the success page can resolve it the
    # same way it resolves a Stripe session id (the ``mock_`` prefix flags it).
    booking.stripe_session_id = reference
    if booking.status != BookingStatus.CONFIRMED:
        transition_booking(booking, BookingStatus.CONFIRMED, extra_fields=['stripe_session_id'])
    else:
        booking.save(update_fields=['stripe_session_id'])
    return booking


# --------------------------------------------------------------------------- #
# Cancellation + refund  (idempotent, atomic)
# --------------------------------------------------------------------------- #
@transaction.atomic
def cancel_booking(booking_id, *, do_refund=True):
    """Cancel a booking: refund (idempotently), release seats, cancel tickets.

    Returns (booking, changed: bool). ``changed`` is False when the booking was
    already cancelled (idempotent no-op). The booking row is locked for the whole
    operation so two concurrent cancels cannot both refund or double-release seats.
    """
    booking = Booking.objects.select_for_update().get(pk=booking_id)

    if booking.status == BookingStatus.CANCELLED:
        return booking, False  # idempotent

    seats = passenger_count(booking)

    if do_refund and booking.payment_intent_id:
        # idempotency_key makes Stripe collapse a retried refund into one.
        refund = stripe.Refund.create(
            payment_intent=booking.payment_intent_id,
            amount=int(booking.total_price * 100),
            idempotency_key=f"ferry-refund-{booking.id}",
        )
        Payment.objects.create(
            booking=booking,
            payment_method='stripe',
            amount=-booking.total_price,
            payment_status=PaymentStatus.REFUNDED,
            transaction_id=refund.id,
        )

    release_seats(booking.schedule_id, seats)
    # Return the vehicle slots and cargo weight this booking was holding.
    release_vehicle_slots(booking.schedule_id, booking.vehicles.count())
    cargo_kg = booking.cargo.aggregate(total=Sum('weight_kg'))['total'] or Decimal('0')
    release_cargo(booking.schedule_id, cargo_kg)
    transition_booking(booking, BookingStatus.CANCELLED)

    booking.tickets.update(ticket_status='cancelled')

    # Email the customer once the cancellation has actually committed (keeps the
    # slow SMTP call out of the row-locked transaction). Best-effort.
    def _notify():
        from .notifications import send_booking_cancellation_email
        send_booking_cancellation_email(booking)
    transaction.on_commit(_notify)

    return booking, True


# --------------------------------------------------------------------------- #
# Rebook — move all confirmed passengers to a different schedule
# --------------------------------------------------------------------------- #
@transaction.atomic
def rebook_booking(booking_id, new_schedule_id, *, moved_by=None):
    """Move a confirmed booking to new_schedule, releasing the old seat hold.

    Returns (booking, old_schedule_id). Raises ValueError if the new schedule
    has insufficient seats or the booking is not confirmed/pending.
    """
    booking = Booking.objects.select_for_update().get(pk=booking_id)
    if booking.status == BookingStatus.CANCELLED:
        raise ValueError("Cannot rebook a cancelled booking.")

    seats = passenger_count(booking)
    veh = booking.vehicles.count()
    cargo_kg = booking.cargo.aggregate(total=Sum('weight_kg'))['total'] or Decimal('0')

    new_schedule = Schedule.objects.select_for_update().get(pk=new_schedule_id)
    if new_schedule.available_seats < seats:
        raise ValueError(
            f"New schedule only has {new_schedule.available_seats} seat(s); booking needs {seats}."
        )
    if new_schedule.available_vehicle_slots < veh:
        raise ValueError(
            f"New schedule only has {new_schedule.available_vehicle_slots} vehicle slot(s); booking needs {veh}."
        )
    if new_schedule.available_cargo_kg < cargo_kg:
        raise ValueError(
            f"New schedule only has {new_schedule.available_cargo_kg} kg cargo capacity; booking needs {cargo_kg} kg."
        )

    old_schedule_id = booking.schedule_id

    # Release from old, reserve on new (seats + vehicle slots + cargo)
    release_seats(old_schedule_id, seats)
    release_vehicle_slots(old_schedule_id, veh)
    release_cargo(old_schedule_id, cargo_kg)
    Schedule.objects.filter(pk=new_schedule_id).update(
        available_seats=F('available_seats') - seats,
        available_vehicle_slots=F('available_vehicle_slots') - veh,
        available_cargo_kg=F('available_cargo_kg') - cargo_kg,
    )

    booking.schedule = new_schedule
    booking.save(update_fields=['schedule'])

    logger.info(
        "Booking %s reBooked: schedule %s → %s by %s",
        booking_id, old_schedule_id, new_schedule_id, moved_by or 'system',
    )
    return booking, old_schedule_id


# --------------------------------------------------------------------------- #
# Manual payment confirmation (staff override for stuck bookings)
# --------------------------------------------------------------------------- #
@transaction.atomic
def manually_confirm_booking(booking_id, *, confirmed_by, reference=''):
    """Confirm a pending booking without a Stripe payment (staff override).

    Creates a local payment record so the audit trail is complete.
    """
    booking = Booking.objects.select_for_update().get(pk=booking_id)
    if booking.status == BookingStatus.CONFIRMED:
        return booking, False  # already confirmed
    if booking.status == BookingStatus.CANCELLED:
        raise ValueError("Cannot confirm a cancelled booking.")

    Payment.objects.create(
        booking=booking,
        payment_method='local',
        amount=booking.total_price,
        payment_status=PaymentStatus.COMPLETED,
        transaction_id=reference or f'manual-{booking_id}',
    )
    transition_booking(booking, BookingStatus.CONFIRMED)
    logger.info("Booking %s manually confirmed by %s (ref=%s)", booking_id, confirmed_by, reference)
    return booking, True


# --------------------------------------------------------------------------- #
# Expiry / reconciliation helpers (used by Celery tasks)
# --------------------------------------------------------------------------- #
@transaction.atomic
def expire_pending_booking(booking_id):
    """Release seats for one abandoned pending booking. Idempotent per booking."""
    booking = Booking.objects.select_for_update().filter(
        pk=booking_id, status=BookingStatus.PENDING
    ).first()
    if not booking:
        return False
    release_seats(booking.schedule_id, passenger_count(booking))
    transition_booking(booking, BookingStatus.CANCELLED)
    return True
