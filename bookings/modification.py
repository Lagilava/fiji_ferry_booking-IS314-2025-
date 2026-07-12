"""Rules and pricing for modifying an existing booking.

Kept free of ``request`` and DB writes (except the explicit quote helpers) so the
policy is unit-testable and reused identically by the view, the templates and the
help assistant. The booking flow's own rules live in ``pricing.py`` and
``views.validate_passenger_data``; this module layers the *change* policy on top.

Policy (see also the chatbot's "modify" intent, which quotes these constants):
  * Changes close ``MODIFY_CUTOFF_HOURS`` before departure.
  * Only ``confirmed`` bookings may be modified.
  * Any change to passenger counts incurs a flat ``MODIFICATION_FEE``, on top of
    the difference in fare. Reducing passengers still pays the fee, and the fare
    drop is refunded, so the net can be a charge or a refund.
  * Added adults/children need a name, an age and an ID document; added children
    and infants must be linked to an adult on the booking.
"""
import datetime
from decimal import Decimal

from django.utils import timezone

from .pricing import calculate_total_price

#: Flat admin fee applied whenever passenger counts change.
MODIFICATION_FEE = Decimal('15.00')

#: Modifications close this many hours before departure.
MODIFY_CUTOFF_HOURS = 24

#: Guardrail matching the booking form's per-type maximum.
MAX_PER_TYPE = 20


def modify_deadline(booking):
    """The instant after which this booking can no longer be modified."""
    return booking.schedule.departure_time - datetime.timedelta(hours=MODIFY_CUTOFF_HOURS)


def can_modify(booking, now=None):
    """Return ``(allowed, reason)``. ``reason`` is user-facing when not allowed."""
    now = now or timezone.now()

    if booking.status != 'confirmed':
        return False, f"Only confirmed bookings can be modified (this one is {booking.get_status_display().lower()})."

    if booking.schedule.departure_time <= now:
        return False, "This sailing has already departed."

    if now >= modify_deadline(booking):
        return False, (
            f"Changes close {MODIFY_CUTOFF_HOURS} hours before departure. "
            "Please contact our team for assistance."
        )

    return True, None


def _fare_for(booking, adults, children, infants):
    """Total fare for these counts, holding cargo/add-ons/vehicle constant."""
    cargo = booking.cargo.first()
    return calculate_total_price(
        adults, children, infants, booking.schedule,
        add_cargo=bool(cargo),
        cargo_type=cargo.cargo_type if cargo else None,
        weight_kg=cargo.weight_kg if cargo else 0,
        addons=[{'type': a.add_on_type, 'quantity': a.quantity} for a in booking.add_ons.all()],
    )


def quote(booking, adults, children, infants):
    """Price a proposed passenger-count change.

    Returns a dict describing the money movement. ``net`` > 0 means the customer
    owes us that much; ``net`` < 0 means we refund ``-net``. The flat fee applies
    only when the counts actually change.
    """
    old_counts = (booking.passenger_adults, booking.passenger_children, booking.passenger_infants)
    new_counts = (adults, children, infants)
    counts_changed = old_counts != new_counts

    old_fare = Decimal(booking.total_price)
    new_fare = _fare_for(booking, adults, children, infants)
    fare_difference = new_fare - old_fare
    fee = MODIFICATION_FEE if counts_changed else Decimal('0.00')

    return {
        'counts_changed': counts_changed,
        'old_fare': old_fare,
        'new_fare': new_fare,
        'fare_difference': fare_difference,
        'fee': fee,
        'net': fare_difference + fee,
        'seats_delta': sum(new_counts) - sum(old_counts),
    }


def validate_counts(adults, children, infants):
    """Structural checks on the requested counts. Returns a list of messages."""
    errors = []
    total = adults + children + infants

    if any(v < 0 for v in (adults, children, infants)):
        errors.append("Passenger counts cannot be negative.")
    if any(v > MAX_PER_TYPE for v in (adults, children, infants)):
        errors.append(f"You can book at most {MAX_PER_TYPE} passengers of each type.")
    if total == 0:
        errors.append("At least one passenger is required.")
    if adults == 0 and (children > 0 or infants > 0):
        errors.append("Children and infants must travel with at least one adult.")

    return errors
