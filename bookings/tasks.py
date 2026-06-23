import datetime

from celery import shared_task
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Schedule, Booking


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

    Seats are reserved when a checkout session is created. If the customer never
    completes payment, those seats would otherwise be held forever. This expires
    pending bookings older than max_age_minutes and atomically restores the seats.
    """
    cutoff = timezone.now() - datetime.timedelta(minutes=max_age_minutes)
    expired = 0
    stale = Booking.objects.filter(status='pending', booking_date__lt=cutoff)
    for booking in stale.iterator():
        with transaction.atomic():
            locked = (
                Booking.objects.select_for_update()
                .filter(pk=booking.pk, status='pending')
                .first()
            )
            if not locked:
                continue  # already handled by another worker / state changed
            seats = (locked.passenger_adults or 0) + (locked.passenger_children or 0) + (locked.passenger_infants or 0)
            if locked.schedule_id and seats:
                Schedule.objects.filter(pk=locked.schedule_id).update(
                    available_seats=F('available_seats') + seats
                )
            locked.status = 'cancelled'
            locked.save(update_fields=['status'])
            expired += 1
    return expired
