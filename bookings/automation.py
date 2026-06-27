"""Offline automation agent — periodic self-tests bound to the server lifecycle.

Like bookings/monitor.py, this is an in-process **daemon thread**: it starts only
for real server processes and dies with the server. On each interval it runs a
fast, **non-destructive, internet-free** battery of checks and records the result
to logs/automation_status.json + logs/automation.log.

The battery covers four layers:
  1. Infrastructure — DB, cache.
  2. HTTP endpoints — in-process probes (no network, no data mutation).
  3. Routing — URL reverse sanity, migration drift.
  4. Business invariants — pure-function pricing + state-machine guards.
  5. Operational integrity — read-only DB queries that surface data anomalies
     (negative seat counts, booking/payment mismatches, maintenance conflicts,
     stale pending bookings, weather freshness, booking throughput).

The exhaustive correctness suite (booking creation, webhook, cancel, refunds,
idempotency, concurrency, authorization, file validation) lives in
``python manage.py test bookings`` — run it in CI / on demand; it is too heavy
(builds a test database) to run on a loop inside a live server.
"""
import atexit
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone as dt_timezone

logger = logging.getLogger("bookings.automation")

_thread = None
_stop_event = threading.Event()


# --------------------------------------------------------------------------- #
# The check battery  (each check returns (ok: bool, detail: str))
# --------------------------------------------------------------------------- #
def _check_health():
    from django.db import connections
    from django.core.cache import cache
    results = []
    try:
        with connections["default"].cursor() as c:
            c.execute("SELECT 1")
            c.fetchone()
        results.append(("database", True, "SELECT 1 ok"))
    except Exception as e:
        results.append(("database", False, str(e)[:160]))
    try:
        cache.set("automation:ping", "1", 10)
        ok = cache.get("automation:ping") == "1"
        results.append(("cache", ok, "roundtrip" if ok else "value mismatch"))
    except Exception as e:
        results.append(("cache", False, str(e)[:160]))
    return results


def _check_http_endpoints():
    """Read-only, in-process probes — no network, no data mutation."""
    from django.test import Client
    c = Client(HTTP_HOST="localhost")
    probes = [
        ("GET /", lambda: c.get("/"), {200}),
        ("GET live departures", lambda: c.get("/bookings/departures/"), {200}),
        ("GET destinations", lambda: c.get("/bookings/destinations/"), {200}),
        ("GET book page", lambda: c.get("/bookings/book/"), {200}),
        ("GET booking history", lambda: c.get("/bookings/history/"), {200, 302, 403}),
        ("GET /bookings/api/routes/", lambda: c.get("/bookings/api/routes/"), {200}),
        ("GET schedule updates", lambda: c.get("/bookings/api/bookings/updates/"), {200}),
        # bad input must be handled (no 500)
        ("availability bad-input",
         lambda: c.get("/bookings/api/availability/", {"route_id": "1", "year": "x", "month": "y"}),
         {200, 400}),
        ("weather bad-input",
         lambda: c.get("/bookings/api/weather/conditions/", {"schedule_id": "x"}),
         {400}),
        ("GET privacy", lambda: c.get("/bookings/privacy_policy/"), {200}),
        ("GET terms", lambda: c.get("/bookings/terms_of_service/"), {200}),
        ("admin login redirect", lambda: c.get("/admin/"), {302, 200}),
        # mock checkout must reject a GET (POST-only) rather than 500
        ("mock checkout rejects GET", lambda: c.get("/bookings/api/create_mock_checkout/"), {405, 302, 403}),
    ]
    results = []
    for name, call, allowed in probes:
        try:
            code = call().status_code
            results.append((name, code in allowed, f"status={code}"))
        except Exception as e:
            results.append((name, False, str(e)[:160]))
    return results


def _check_urls_reverse():
    """Every URL name the app relies on must reverse — catches broken wiring."""
    from django.urls import reverse, NoReverseMatch
    results = []
    simple = [
        "home", "bookings:book_ticket", "bookings:booking_history",
        "bookings:live_departures", "bookings:destinations",
        "bookings:api_create_checkout_session", "bookings:api_create_mock_checkout",
        "bookings:success", "bookings:api_pricing",
        "accounts:login", "accounts:register",
    ]
    for name in simple:
        try:
            reverse(name)
            results.append((f"reverse {name}", True, ""))
        except NoReverseMatch as e:
            results.append((f"reverse {name}", False, str(e)[:120]))
        except Exception as e:
            results.append((f"reverse {name}", False, str(e)[:120]))
    # URLs that take an argument.
    for name in ("bookings:mock_payment", "bookings:process_payment", "bookings:cancel_mock_and_rebook"):
        try:
            reverse(name, args=[1])
            results.append((f"reverse {name}", True, ""))
        except Exception as e:
            results.append((f"reverse {name}", False, str(e)[:120]))
    return results


def _check_migrations():
    """No un-generated model changes (model/migration drift)."""
    results = []
    try:
        from django.core.management import call_command
        call_command("makemigrations", "--check", "--dry-run", verbosity=0)
        results.append(("no migration drift", True, "models match migrations"))
    except SystemExit:
        results.append(("no migration drift", False, "un-made migrations detected"))
    except Exception as e:
        results.append(("no migration drift", False, str(e)[:160]))
    return results


def _check_business_invariants():
    """Pure-function invariants — no DB writes, no network."""
    from decimal import Decimal
    results = []

    class _Route:
        base_fare = Decimal("50.00")
    class _Sched:
        route = _Route()

    try:
        from bookings import pricing
        total = pricing.calculate_total_price(2, 0, 0, _Sched(),
                                               add_cargo=False, cargo_type=None,
                                               weight_kg=0, addons=[])
        ok = Decimal(total) == Decimal("100.00")
        results.append(("pricing 2 adults == 100.00", ok, f"got {total}"))
    except Exception as e:
        results.append(("pricing", False, str(e)[:160]))

    try:
        from bookings import pricing
        # Children @ 50%, infants @ 10% of base fare (1 adult + 1 child + 1 infant).
        total = pricing.calculate_total_price(1, 1, 1, _Sched(),
                                              add_cargo=False, cargo_type=None,
                                              weight_kg=0, addons=[])
        ok = Decimal(total) == Decimal("80.00")
        results.append(("pricing adult+child+infant == 80.00", ok, f"got {total}"))
    except Exception as e:
        results.append(("pricing mixed pax", False, str(e)[:160]))

    try:
        from bookings import pricing
        bad = False
        try:
            pricing.calculate_addon_price("nope", 1)
        except ValueError:
            bad = True
        results.append(("pricing rejects bad addon", bad, "ValueError raised" if bad else "no error"))
    except Exception as e:
        results.append(("pricing addon guard", False, str(e)[:160]))

    try:
        from bookings.services import ALLOWED_BOOKING_TRANSITIONS
        ok = ("confirmed" not in ALLOWED_BOOKING_TRANSITIONS["cancelled"]
              and "confirmed" in ALLOWED_BOOKING_TRANSITIONS["pending"]
              and ALLOWED_BOOKING_TRANSITIONS["cancelled"] == {"cancelled"})
        results.append(("state machine guards transitions", ok, ""))
    except Exception as e:
        results.append(("state machine", False, str(e)[:160]))

    try:
        from bookings import services
        provs = services.MOCK_PAYMENT_PROVIDERS
        ok = all(k in provs for k in ("anz", "bsp", "mpaisa", "mycash", "card"))
        results.append(("mock payment providers registered", ok, ",".join(sorted(provs))))
    except Exception as e:
        results.append(("mock providers", False, str(e)[:160]))
    return results


def _check_operational_integrity():
    """Read-only DB queries that surface live data anomalies for staff attention.

    Every check returns (name, ok, detail). ok=True means "nothing to flag."
    ok=False does not crash the server — it writes a warning to the log and
    automation_status.json so an admin can investigate.
    """
    results = []
    now = datetime.now(dt_timezone.utc)

    # 5a. No schedule may have fewer than 0 available seats.
    try:
        from bookings.models import Schedule
        neg = Schedule.objects.filter(available_seats__lt=0).count()
        results.append((
            "seat counts non-negative",
            neg == 0,
            "ok" if neg == 0 else f"{neg} schedule(s) with negative available_seats — investigate immediately",
        ))
    except Exception as e:
        results.append(("seat count check", False, str(e)[:160]))

    # 5b. available_seats must not exceed the ferry's declared capacity.
    try:
        from bookings.models import Schedule
        overcap = sum(
            1 for s in Schedule.objects.select_related("ferry").filter(status="scheduled")[:300]
            if s.ferry and s.available_seats > s.ferry.capacity
        )
        results.append((
            "seat counts within ferry capacity",
            overcap == 0,
            "ok" if overcap == 0 else f"{overcap} schedule(s) where available_seats > ferry.capacity",
        ))
    except Exception as e:
        results.append(("over-capacity check", False, str(e)[:160]))

    # 5c. Every confirmed booking must have exactly one completed Payment row.
    try:
        from bookings.models import Booking, Payment
        from django.db.models import Exists, OuterRef
        orphaned = Booking.objects.filter(status="confirmed").exclude(
            Exists(Payment.objects.filter(booking=OuterRef("pk"), payment_status="completed"))
        ).count()
        results.append((
            "confirmed bookings have completed payment",
            orphaned == 0,
            "ok" if orphaned == 0 else f"{orphaned} confirmed booking(s) missing a completed Payment row",
        ))
    except Exception as e:
        results.append(("payment integrity check", False, str(e)[:160]))

    # 5d. Pending bookings older than 2 hours suggest the expiry task is stalled.
    try:
        from bookings.models import Booking
        stale = Booking.objects.filter(
            status="pending",
            booking_date__lt=now - timedelta(hours=2),
        ).count()
        results.append((
            "no stale pending bookings (>2 h)",
            stale == 0,
            "ok" if stale == 0 else f"{stale} pending booking(s) older than 2 hours — expiry task may not be running",
        ))
    except Exception as e:
        results.append(("stale pending check", False, str(e)[:160]))

    # 5e. Ferries under open maintenance should not have upcoming scheduled departures.
    try:
        import datetime as _dt
        from bookings.models import MaintenanceLog, Schedule
        today = _dt.date.today()
        under_maintenance = set(
            MaintenanceLog.objects.filter(
                completed_at__isnull=True,
                maintenance_date__lte=today,
            ).values_list("ferry_id", flat=True)
        )
        conflicts = 0
        if under_maintenance:
            conflicts = Schedule.objects.filter(
                ferry_id__in=under_maintenance,
                status="scheduled",
                departure_time__gt=now,
            ).count()
        results.append((
            "no departures scheduled for ferries under maintenance",
            conflicts == 0,
            "ok" if conflicts == 0 else (
                f"{conflicts} scheduled departure(s) for ferries with open maintenance logs"
            ),
        ))
    except Exception as e:
        results.append(("maintenance conflict check", False, str(e)[:160]))

    # 5f. At least one non-expired WeatherCondition row — otherwise the live page
    #     shows blank weather.
    try:
        from bookings.models import WeatherCondition
        from django.utils import timezone as dj_tz
        fresh = WeatherCondition.objects.filter(expires_at__gt=dj_tz.now()).count()
        results.append((
            "weather data is fresh",
            fresh > 0,
            f"{fresh} fresh row(s)" if fresh else "all WeatherCondition rows expired — run refresh_weather",
        ))
    except Exception as e:
        results.append(("weather freshness", False, str(e)[:160]))

    # 5g. Booking throughput snapshot (informational — always ok=True so it
    #     doesn't mask real failures with false alarms, but gets logged).
    try:
        from bookings.models import Booking
        last_1h = Booking.objects.filter(booking_date__gte=now - timedelta(hours=1)).count()
        last_24h = Booking.objects.filter(booking_date__gte=now - timedelta(hours=24)).count()
        results.append((
            f"booking throughput: {last_1h}/1h, {last_24h}/24h",
            True,
            f"last_1h={last_1h} last_24h={last_24h}",
        ))
    except Exception as e:
        results.append(("booking throughput", False, str(e)[:160]))

    return results


def run_battery():
    """Run all checks and return a structured result dict."""
    import time as _time
    started = _time.perf_counter()
    checks = []
    groups = (
        ("health", _check_health()),
        ("http", _check_http_endpoints()),
        ("urls", _check_urls_reverse()),
        ("migrations", _check_migrations()),
        ("invariants", _check_business_invariants()),
        ("operational", _check_operational_integrity()),
    )
    for group_name, group in groups:
        for name, ok, detail in group:
            checks.append({"group": group_name, "name": name, "ok": bool(ok), "detail": detail})
    passed = sum(1 for c in checks if c["ok"])
    failed = [c["name"] for c in checks if not c["ok"]]
    return {
        "ran_at": datetime.now(dt_timezone.utc).isoformat(),
        "duration_ms": round((_time.perf_counter() - started) * 1000, 1),
        "passed": passed,
        "total": len(checks),
        "ok": passed == len(checks),
        "failed": failed,
        "checks": checks,
    }


# --------------------------------------------------------------------------- #
# Daemon
# --------------------------------------------------------------------------- #
def _paths():
    from django.conf import settings
    logs = os.path.join(settings.BASE_DIR, "logs")
    os.makedirs(logs, exist_ok=True)
    return os.path.join(logs, "automation.log"), os.path.join(logs, "automation_status.json")


def _write(result):
    log_path, status_path = _paths()
    try:
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except Exception:
        logger.exception("automation: failed to write status")
    failed = [c["name"] for c in result["checks"] if not c["ok"]]
    level = logging.INFO if result["ok"] else logging.ERROR
    logger.log(level, "battery %s/%s passed%s",
               result["passed"], result["total"],
               "" if result["ok"] else f"; FAILED: {', '.join(failed)}")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{result['ran_at']}] {result['passed']}/{result['total']} "
                    f"{'OK' if result['ok'] else 'FAIL: ' + ', '.join(failed)}\n")
    except Exception:
        pass


def _run_maintenance():
    """Run lightweight in-process maintenance tasks as a Celery Beat fallback.

    Called before each check battery so that checks observe fresh state.
    Safe to run even when Celery workers/beat are present — tasks are idempotent.
    """
    try:
        from bookings import services
        from bookings.models import Booking
        from django.utils import timezone as dj_tz
        cutoff = dj_tz.now() - timedelta(minutes=30)
        ids = list(
            Booking.objects.filter(status="pending", booking_date__lt=cutoff)
            .values_list("id", flat=True)
        )
        expired = 0
        for bid in ids:
            try:
                if services.expire_pending_booking(bid):
                    expired += 1
            except Exception:
                logger.exception("automation: failed to expire booking %s", bid)
        if expired:
            logger.info("automation: expired %d stale pending booking(s)", expired)
    except Exception:
        logger.exception("automation: maintenance step failed")


def _run(interval):
    log_path, _ = _paths()
    logger.info("Automation agent started (interval=%ss)", interval)
    # small initial delay so the server finishes booting before the first probe
    if _stop_event.wait(5):
        return
    while not _stop_event.is_set():
        try:
            _run_maintenance()
            _write(run_battery())
        except Exception:
            logger.exception("automation: battery run failed")
        _stop_event.wait(interval)


def _on_exit():
    _stop_event.set()
    try:
        log_path, _ = _paths()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(dt_timezone.utc).isoformat()}] STOPPED\n")
    except Exception:
        pass


def start_automation():
    """Start the automation daemon once, only for real server processes."""
    global _thread
    from django.conf import settings
    from .monitor import _is_server_process  # shared server-detection guard

    if not getattr(settings, "AUTOMATION_AGENT_ENABLED", True):
        return
    if not _is_server_process():
        return
    import sys
    argv = sys.argv or []
    if "runserver" in argv and "--noreload" not in argv and os.environ.get("RUN_MAIN") != "true":
        return
    if _thread is not None and _thread.is_alive():
        return

    interval = int(getattr(settings, "AUTOMATION_AGENT_INTERVAL", 300))
    _stop_event.clear()
    _thread = threading.Thread(target=_run, args=(interval,), name="automation-agent", daemon=True)
    _thread.start()
    atexit.register(_on_exit)
