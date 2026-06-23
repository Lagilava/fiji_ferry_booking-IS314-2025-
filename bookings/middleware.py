from django.core.cache import cache
from django.utils import timezone
from .models import Schedule


class ScheduleUpdateMiddleware:
    """Flip departed schedules to the 'departed' status.

    CON-3: previously this issued a write (UPDATE) on the Schedule table on
    *every* HTTP request, causing write amplification and lock contention on the
    same hot table that booking/cancel writes need. It is now gated by a short
    cache lock so the UPDATE runs at most once per interval regardless of request
    volume. (Celery beat also runs bookings.tasks.update_schedules_status.)
    """

    INTERVAL_SECONDS = 60
    LOCK_KEY = "schedule_status_sweep_ts"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # add() is atomic: only the first caller within the interval wins.
        if cache.add(self.LOCK_KEY, 1, self.INTERVAL_SECONDS):
            try:
                Schedule.objects.filter(
                    status='scheduled',
                    departure_time__lt=timezone.now()
                ).update(status='departed')
            except Exception:
                # Never let a maintenance sweep break the request cycle.
                pass
        return self.get_response(request)
