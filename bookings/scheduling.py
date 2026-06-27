"""Pre-flight validation for ferry schedules.

A single source of truth that answers: *"is it operationally valid to run this
ferry on this route at this time?"* — used by both the auto-seeder and the admin
``Schedule`` form so a sailing can never be created that:

  1. uses an inactive ferry,
  2. uses a ferry with open (uncompleted) maintenance covering that day,
  3. overlaps another sailing of the same ferry (respecting the route's
     ``safety_buffer_minutes`` for turnaround / the return leg), or
  4. departs outside the route's ``preferred_departure_windows`` (when set).

This is the "prevention" layer: it stops conflicts at creation time instead of
only detecting them after the fact (see bookings/automation.py for the
read-only detective checks).
"""
from datetime import datetime, timedelta

from django.utils import timezone

# Schedule statuses that still occupy the ferry (i.e. count for overlap checks).
ACTIVE_SCHEDULE_STATUSES = ("scheduled", "delayed")


def _parse_window(window):
    """Parse a 'HH:MM-HH:MM' string into (start_time, end_time) or None."""
    try:
        start_s, end_s = window.split("-")
        start = datetime.strptime(start_s.strip(), "%H:%M").time()
        end = datetime.strptime(end_s.strip(), "%H:%M").time()
        return start, end
    except (ValueError, AttributeError):
        return None


def ferry_has_open_maintenance(ferry, on_date):
    """True if the ferry has an uncompleted maintenance log on/before `on_date`."""
    from .models import MaintenanceLog
    return MaintenanceLog.objects.filter(
        ferry=ferry,
        completed_at__isnull=True,
        maintenance_date__lte=on_date,
    ).exists()


def overlapping_schedule(ferry, departure, arrival, buffer_minutes, exclude_id=None):
    """Return the first same-ferry sailing that overlaps [departure, arrival]
    (padded by `buffer_minutes` on both sides), or None.
    """
    from .models import Schedule
    buffer = timedelta(minutes=buffer_minutes or 0)
    qs = Schedule.objects.filter(
        ferry=ferry,
        status__in=ACTIVE_SCHEDULE_STATUSES,
        # Two intervals overlap iff each starts before the other ends.
        departure_time__lt=arrival + buffer,
        arrival_time__gt=departure - buffer,
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.select_related("route").first()


def validate_schedule_slot(ferry, route, departure, arrival, exclude_id=None):
    """Validate a candidate sailing.

    Returns ``(ok: bool, reason: str)``. ``reason`` is empty when ok.
    Pure read-only — performs no writes.
    """
    if ferry is None or route is None:
        return False, "Ferry and route are required."
    if not getattr(ferry, "is_active", True):
        return False, f"Ferry '{ferry.name}' is inactive."
    if arrival <= departure:
        return False, "Arrival time must be after departure time."

    op_date = timezone.localtime(departure).date() if timezone.is_aware(departure) else departure.date()

    # 2. Maintenance
    if ferry_has_open_maintenance(ferry, op_date):
        return False, f"Ferry '{ferry.name}' has open maintenance on {op_date}."

    # 3. Ferry double-booking / insufficient turnaround
    buffer_minutes = getattr(route, "safety_buffer_minutes", 0) or 0
    clash = overlapping_schedule(ferry, departure, arrival, buffer_minutes, exclude_id=exclude_id)
    if clash is not None:
        return False, (
            f"Ferry '{ferry.name}' is already committed to {clash.route} "
            f"departing {timezone.localtime(clash.departure_time):%Y-%m-%d %H:%M} "
            f"(needs {buffer_minutes} min turnaround buffer)."
        )

    # 4. Preferred departure windows (only enforced when configured on the route)
    windows = getattr(route, "preferred_departure_windows", None) or []
    if windows:
        dep_local = timezone.localtime(departure).time() if timezone.is_aware(departure) else departure.time()
        in_window = False
        for w in windows:
            parsed = _parse_window(w)
            if parsed and parsed[0] <= dep_local <= parsed[1]:
                in_window = True
                break
        if not in_window:
            return False, (
                f"Departure {dep_local:%H:%M} is outside the route's preferred "
                f"windows ({', '.join(windows)})."
            )

    return True, ""
