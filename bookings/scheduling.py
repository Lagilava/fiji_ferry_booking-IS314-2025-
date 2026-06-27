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
# weather_hold counts too: the ferry stays assigned and the sailing can be
# released back to 'scheduled' once weather clears.
ACTIVE_SCHEDULE_STATUSES = ("scheduled", "delayed", "weather_hold")


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


# --------------------------------------------------------------------------- #
# Weather risk evaluation (Layer B: flag-for-review holds)
# --------------------------------------------------------------------------- #
# Condition keywords that warrant a hold regardless of measured wind/precip.
_SEVERE_CONDITION_KEYWORDS = ("thunderstorm", "violent", "hurricane", "gale", "heavy rain")


def weather_breaches_threshold(weather, wind_kmh, precip_pct):
    """Return a human-readable reason string if `weather` is unsafe, else ''.

    `weather` is a WeatherCondition instance (or any object exposing
    wind_speed / precipitation_probability / condition).
    """
    if weather is None:
        return ""
    wind = getattr(weather, "wind_speed", None)
    precip = getattr(weather, "precipitation_probability", None)
    condition = (getattr(weather, "condition", None) or "").lower()

    if wind is not None and wind_kmh and wind > wind_kmh:
        return f"wind {round(float(wind), 1)} km/h exceeds {wind_kmh} km/h"
    if precip is not None and precip_pct and precip > precip_pct:
        return f"precipitation {round(float(precip), 0)}% exceeds {precip_pct}%"
    for kw in _SEVERE_CONDITION_KEYWORDS:
        if kw in condition:
            return f"severe condition: {getattr(weather, 'condition', '')}"
    return ""


def evaluate_weather_holds():
    """Move at-risk upcoming sailings to 'weather_hold' for staff review.

    Flag-for-review semantics: a breaching sailing is held (becomes
    non-bookable) but is **never** auto-cancelled, and is **never**
    auto-released — a staff member decides via the admin. Idempotent and safe
    to run on a loop. Returns a summary dict.
    """
    from django.conf import settings
    from .models import Schedule, WeatherCondition

    if not getattr(settings, "WEATHER_HOLD_ENABLED", True):
        return {"enabled": False, "held": 0, "evaluated": 0}

    wind_kmh = float(getattr(settings, "WEATHER_HOLD_WIND_KMH", 45))
    precip_pct = float(getattr(settings, "WEATHER_HOLD_PRECIP_PCT", 85))
    horizon_h = int(getattr(settings, "WEATHER_HOLD_HORIZON_HOURS", 24))

    now = timezone.now()
    horizon = now + timedelta(hours=horizon_h)

    # Cache the latest fresh weather per route so we hit the DB once per route.
    fresh_weather = {}
    for w in WeatherCondition.objects.filter(expires_at__gt=now).order_by("route_id", "-updated_at"):
        fresh_weather.setdefault(w.route_id, w)

    held = 0
    evaluated = 0
    candidates = Schedule.objects.filter(
        status="scheduled",
        departure_time__gt=now,
        departure_time__lte=horizon,
    ).select_related("route", "ferry")

    for sched in candidates:
        evaluated += 1
        weather = fresh_weather.get(sched.route_id)
        reason = weather_breaches_threshold(weather, wind_kmh, precip_pct)
        if not reason:
            continue
        sched.status = "weather_hold"
        stamp = timezone.localtime(now).strftime("%Y-%m-%d %H:%M")
        note = f"[{stamp}] Auto weather-hold: {reason}. Needs staff review."
        sched.notes = f"{sched.notes}\n{note}" if sched.notes else note
        sched.save(update_fields=["status", "notes", "last_updated"])
        held += 1

    return {"enabled": True, "held": held, "evaluated": evaluated,
            "wind_kmh": wind_kmh, "precip_pct": precip_pct, "horizon_h": horizon_h}


# --------------------------------------------------------------------------- #
# Operational risk finders (Layer D: surface conflicts to staff)
# --------------------------------------------------------------------------- #
def upcoming_maintenance_conflicts():
    """Upcoming 'scheduled' sailings whose ferry has open maintenance.

    These slipped past prevention (e.g. maintenance opened *after* the sailing
    was created) and need a staff decision. Returns a list of Schedule rows.
    """
    import datetime as _dt
    from .models import MaintenanceLog, Schedule

    today = _dt.date.today()
    under_maintenance = list(
        MaintenanceLog.objects.filter(
            completed_at__isnull=True, maintenance_date__lte=today
        ).values_list("ferry_id", flat=True)
    )
    if not under_maintenance:
        return []
    return list(
        Schedule.objects.filter(
            ferry_id__in=under_maintenance,
            status="scheduled",
            departure_time__gt=timezone.now(),
        ).select_related("ferry", "route__departure_port", "route__destination_port")
        .order_by("departure_time")[:50]
    )


def upcoming_overlap_conflicts(days=7):
    """Upcoming active sailings where the same ferry overlaps itself.

    Sweeps per ferry in time order (no per-row queries) and flags any sailing
    that departs before the previous one's arrival + the route turnaround buffer.
    Returns a list of dicts: {"schedule": <later>, "clash": <earlier>}.
    """
    from .models import Schedule

    now = timezone.now()
    horizon = now + timedelta(days=days)
    sailings = list(
        Schedule.objects.filter(
            status__in=ACTIVE_SCHEDULE_STATUSES,
            departure_time__gt=now,
            departure_time__lte=horizon,
        ).select_related("ferry", "route__departure_port", "route__destination_port")
        .order_by("ferry_id", "departure_time")
    )
    conflicts = []
    prev_by_ferry = {}
    for s in sailings:
        prev = prev_by_ferry.get(s.ferry_id)
        if prev is not None:
            buffer = timedelta(minutes=getattr(prev.route, "safety_buffer_minutes", 0) or 0)
            if s.departure_time < prev.arrival_time + buffer:
                conflicts.append({"schedule": s, "clash": prev})
        # keep the sailing that ends latest as the reference for the next one
        if prev is None or s.arrival_time > prev.arrival_time:
            prev_by_ferry[s.ferry_id] = s
    return conflicts


def routes_with_stale_weather():
    """Routes that have upcoming sailings but no fresh weather data.

    Returns a list of Route rows — staff should run refresh_weather or check
    the provider, because risk evaluation can't judge these sailings.
    """
    from .models import Route, Schedule, WeatherCondition

    now = timezone.now()
    route_ids = set(
        Schedule.objects.filter(
            status__in=("scheduled", "weather_hold"), departure_time__gt=now
        ).values_list("route_id", flat=True)
    )
    if not route_ids:
        return []
    fresh = set(
        WeatherCondition.objects.filter(
            route_id__in=route_ids, expires_at__gt=now
        ).values_list("route_id", flat=True)
    )
    stale_ids = route_ids - fresh
    if not stale_ids:
        return []
    return list(
        Route.objects.select_related("departure_port", "destination_port").filter(id__in=stale_ids)
    )


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
