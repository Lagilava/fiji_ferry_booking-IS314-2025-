"""Idempotent demo/operational data seeding.

Ensures the system is "ready when the server is up": active ferries, routes
(with map waypoints), and a rolling window of upcoming schedules so the homepage
shows real, bookable sailings instead of empty/fallback data.

Everything here is idempotent — safe to run repeatedly and on every server start.
"""
import logging
import threading
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("bookings.seed")

# Fiji ports (lat/lng within the model's validator bounds: lat -21..-16, lng 176..181)
PORTS = {
    "Suva": (-18.1416, 178.4419),
    "Natovi": (-17.7100, 178.5200),
    "Nabouwalu": (-16.9980, 178.6900),
    "Levuka": (-17.6820, 178.8400),
    "Kadavu (Vunisea)": (-19.0600, 178.1600),
    "Savusavu": (-16.8100, 179.3300),
    "Taveuni": (-16.8500, 179.9700),
    "Lautoka": (-17.6100, 177.4500),
}

FERRIES = [
    ("Lomaiviti Princess", 600),
    ("Spirit of Altruism", 400),
    ("Sinu-i-Wasa", 300),
]

# (departure, destination, base_fare, hours)
ROUTES = [
    ("Suva", "Kadavu (Vunisea)", 50, 4.0),
    ("Natovi", "Levuka", 35, 1.5),
    ("Natovi", "Nabouwalu", 50, 2.75),
    ("Suva", "Savusavu", 90, 12.0),
    ("Suva", "Taveuni", 100, 14.0),
    ("Lautoka", "Savusavu", 80, 10.0),
]

DAILY_DEPARTURES = [time(8, 0), time(14, 0)]


def _ensure_base_data():
    from .models import Port, Ferry, Route
    ports = {}
    for name, (lat, lng) in PORTS.items():
        ports[name] = Port.objects.get_or_create(name=name, defaults={"lat": lat, "lng": lng})[0]

    ferries = []
    for name, cap in FERRIES:
        f, _ = Ferry.objects.get_or_create(name=name, defaults={"capacity": cap, "is_active": True})
        if not f.is_active:               # make sure seeded ferries are active
            f.is_active = True
            f.save(update_fields=["is_active"])
        ferries.append(f)

    routes = []
    for dep, dest, fare, hours in ROUTES:
        dp, ds = ports[dep], ports[dest]
        route, _ = Route.objects.get_or_create(
            departure_port=dp, destination_port=ds,
            defaults={
                "distance_km": Decimal("100"),
                "estimated_duration": timedelta(hours=hours),
                "base_fare": Decimal(str(fare)),
            },
        )
        # Backfill map waypoints (so the homepage map draws the sea route, not just ports).
        if not route.waypoints:
            route.waypoints = [[dp.lat, dp.lng], [ds.lat, ds.lng]]
            route.save(update_fields=["waypoints"])
        routes.append(route)
    return ferries, routes


@transaction.atomic
def ensure_demo_data(days=7):
    """Ensure active ferries, routes (+waypoints), and upcoming schedules exist.

    Creates at most DAILY_DEPARTURES sailings per route per day for the next
    `days` days, skipping any (route, day) that already has a scheduled sailing.
    Returns a summary dict.
    """
    from .models import Schedule

    from .scheduling import validate_schedule_slot

    ferries, routes = _ensure_base_data()
    created = 0
    skipped = 0
    today = timezone.localdate()
    tz = timezone.get_current_timezone()

    for day_offset in range(days):
        op_day = today + timedelta(days=day_offset)
        for i, route in enumerate(routes):
            ferry = ferries[i % len(ferries)]
            for dep_t in DAILY_DEPARTURES:
                naive = datetime.combine(op_day, dep_t)
                departure = timezone.make_aware(naive, tz)
                if departure <= timezone.now():
                    continue  # don't seed sailings in the past
                # idempotent: skip if this ferry/route already departs at this time
                if Schedule.objects.filter(ferry=ferry, route=route,
                                           departure_time=departure).exists():
                    continue
                hrs = route.estimated_duration or timedelta(hours=3)
                arrival = departure + hrs

                # Prevention gate: never auto-create an operationally invalid sailing
                # (inactive/maintenance ferry, turnaround overlap, bad window).
                ok, reason = validate_schedule_slot(ferry, route, departure, arrival)
                if not ok:
                    skipped += 1
                    logger.info("autoseed: skipped %s @ %s — %s", route, departure, reason)
                    continue

                Schedule.objects.create(
                    ferry=ferry, route=route,
                    departure_time=departure,
                    arrival_time=arrival,
                    estimated_duration=f"{int(hrs.total_seconds() // 3600)}h",
                    available_seats=ferry.capacity,
                    status="scheduled",
                    operational_day=op_day,
                    created_by_auto=True,
                )
                created += 1

    upcoming = Schedule.objects.filter(status="scheduled",
                                       departure_time__gt=timezone.now()).count()
    logger.info("ensure_demo_data: created %s new schedules (%s skipped); %s upcoming",
                created, skipped, upcoming)
    return {"created": created, "skipped": skipped, "upcoming": upcoming,
            "routes": len(routes), "ferries": len(ferries)}


# --------------------------------------------------------------------------- #
# Server-startup auto-seed (daemon thread; runs once, off the ready() path)
# --------------------------------------------------------------------------- #
_seeded = threading.Event()


def _autoseed_worker(days, min_upcoming):
    try:
        from .models import Schedule
        # Always ensure base data + waypoints; only generate sailings if thin.
        upcoming = Schedule.objects.filter(status="scheduled",
                                           departure_time__gt=timezone.now()).count()
        if upcoming < min_upcoming:
            ensure_demo_data(days=days)
        else:
            _ensure_base_data()  # still backfill ports/routes/waypoints
            logger.info("autoseed: %s upcoming schedules already present", upcoming)
    except Exception:
        logger.exception("autoseed worker failed")


def start_autoseed():
    """Ensure demo data shortly after a real server process starts."""
    from django.conf import settings
    from .monitor import _is_server_process

    if not getattr(settings, "AUTO_SEED_SCHEDULES", True):
        return
    if not _is_server_process():
        return
    import os, sys
    argv = sys.argv or []
    if "runserver" in argv and "--noreload" not in argv and os.environ.get("RUN_MAIN") != "true":
        return
    if _seeded.is_set():
        return
    _seeded.set()
    days = int(getattr(settings, "AUTO_SEED_DAYS", 7))
    min_upcoming = int(getattr(settings, "AUTO_SEED_MIN_UPCOMING", 6))
    threading.Timer(3.0, _autoseed_worker, args=(days, min_upcoming)).start()
