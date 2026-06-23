"""Offline automation agent — periodic self-tests bound to the server lifecycle.

Like bookings/monitor.py, this is an in-process **daemon thread**: it starts only
for real server processes and dies with the server. On each interval it runs a
fast, **non-destructive, internet-free** battery of checks and records the result
to logs/automation_status.json + logs/automation.log.

The battery deliberately avoids any operation that mutates persistent data or
touches the network (Stripe/email). It exercises:
  * dependency health (DB / cache / channel layer),
  * read-only HTTP endpoints via the in-process test Client,
  * pure business-logic invariants (pricing + the booking state machine).

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
from datetime import datetime, timezone as dt_timezone

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
        ("GET /bookings/api/routes/", lambda: c.get("/bookings/api/routes/"), {200}),
        # bad input must be handled (no 500)
        ("availability bad-input",
         lambda: c.get("/bookings/api/availability/", {"route_id": "1", "year": "x", "month": "y"}),
         {200}),
        ("GET privacy", lambda: c.get("/bookings/privacy_policy/"), {200}),
        ("GET terms", lambda: c.get("/bookings/terms_of_service/"), {200}),
        ("admin login redirect", lambda: c.get("/admin/"), {302, 200}),
    ]
    results = []
    for name, call, allowed in probes:
        try:
            code = call().status_code
            results.append((name, code in allowed, f"status={code}"))
        except Exception as e:
            results.append((name, False, str(e)[:160]))
    return results


def _check_business_invariants():
    """Pure-function invariants — no DB writes, no network."""
    results = []
    try:
        from bookings import pricing
        # 2 adults @ base 50 should price deterministically via a stub schedule.
        class _Route:
            base_fare = __import__("decimal").Decimal("50.00")
        class _Sched:
            route = _Route()
        total = pricing.calculate_total_price(2, 0, 0, _Sched(),
                                               add_cargo=False, cargo_type=None,
                                               weight_kg=0, addons=[])
        ok = __import__("decimal").Decimal(total) == __import__("decimal").Decimal("100.00")
        results.append(("pricing 2 adults == 100.00", ok, f"got {total}"))
    except Exception as e:
        results.append(("pricing", False, str(e)[:160]))

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
              and "confirmed" in ALLOWED_BOOKING_TRANSITIONS["pending"])
        results.append(("state machine guards transitions", ok, ""))
    except Exception as e:
        results.append(("state machine", False, str(e)[:160]))
    return results


def run_battery():
    """Run all checks and return a structured result dict."""
    checks = []
    for group in (_check_health(), _check_http_endpoints(), _check_business_invariants()):
        for name, ok, detail in group:
            checks.append({"name": name, "ok": bool(ok), "detail": detail})
    passed = sum(1 for c in checks if c["ok"])
    return {
        "ran_at": datetime.now(dt_timezone.utc).isoformat(),
        "passed": passed,
        "total": len(checks),
        "ok": passed == len(checks),
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


def _run(interval):
    log_path, _ = _paths()
    logger.info("Automation agent started (interval=%ss)", interval)
    # small initial delay so the server finishes booting before the first probe
    if _stop_event.wait(5):
        return
    while not _stop_event.is_set():
        try:
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
