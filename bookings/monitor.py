"""Server status monitor — an in-process agent bound to the server lifecycle.

Lifecycle contract (as requested):
  * The monitor starts when the server process starts (runserver / daphne / ASGI).
  * It runs as a **daemon thread**, so it cannot outlive the server: when the
    server process stops or crashes, the thread is torn down with it.
  * An atexit hook records a final "stopped" status so the offline record shows a
    clean shutdown.

"Offline" status: every tick the agent probes the server's dependencies
(database, cache/Redis, channel layer) and writes a heartbeat to
``logs/server_monitor.log`` plus a machine-readable snapshot to
``logs/server_status.json``. These files can be inspected even when nothing is
connected to the live app — i.e. offline.

Metrics emitted each tick
--------------------------
  * Infrastructure: DB latency, cache roundtrip, channel-layer presence.
  * Celery: active worker count (best-effort ping via Celery inspect).
  * System: process uptime, thread count, disk usage.
  * Domain gauges: pending / confirmed / cancelled booking counts, booking
    throughput (last 1 h / 24 h), upcoming departure count, revenue snapshot
    (confirmed bookings last 24 h), today's cancellation count.

It only starts for actual server processes, never for management commands such
as migrate/test/shell/collectstatic, and is guarded against the runserver
autoreloader starting it twice.
"""
import atexit
import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone as dt_timezone

logger = logging.getLogger("bookings.monitor")

_monitor_thread = None
_stop_event = threading.Event()

# Commands that are NOT a running server — never start the monitor for these.
_NON_SERVER_COMMANDS = {
    "migrate", "makemigrations", "test", "shell", "shell_plus", "collectstatic",
    "createsuperuser", "dbshell", "showmigrations", "loaddata", "dumpdata",
    "check", "flush", "sqlmigrate", "compilemessages", "makemessages",
}


def _status_paths():
    from django.conf import settings
    logs = os.path.join(settings.BASE_DIR, "logs")
    os.makedirs(logs, exist_ok=True)
    return os.path.join(logs, "server_monitor.log"), os.path.join(logs, "server_status.json")


def _timed(fn):
    """Run a check, returning (ok, error, latency_ms)."""
    start = time.perf_counter()
    ok, err = fn()
    return ok, err, round((time.perf_counter() - start) * 1000, 2)


def _check_database():
    from django.db import connections
    try:
        with connections["default"].cursor() as c:
            c.execute("SELECT 1")
            c.fetchone()
        return True, None
    except Exception as e:  # pragma: no cover - exercised only on outage
        return False, str(e)[:200]


def _check_cache():
    try:
        from django.core.cache import cache
        cache.set("monitor:ping", "1", 10)
        return cache.get("monitor:ping") == "1", None
    except Exception as e:  # pragma: no cover
        return False, str(e)[:200]


def _check_channel_layer():
    try:
        from channels.layers import get_channel_layer
        return get_channel_layer() is not None, None
    except Exception as e:  # pragma: no cover
        return False, str(e)[:200]


def _check_celery():
    """Ping active Celery workers via inspect; best-effort — never raises."""
    try:
        from ferry_system.celery import app as celery_app
        inspect = celery_app.control.inspect(timeout=1.5)
        active = inspect.ping()
        if active:
            workers = list(active.keys())
            return True, None, len(workers)
        return False, "no workers responded to ping", 0
    except Exception as e:
        return False, str(e)[:160], 0


def _system_metrics(started_at):
    """Cross-platform, stdlib-only process/system gauges for offline inspection."""
    metrics = {}
    try:
        started_dt = datetime.fromisoformat(started_at)
        uptime = (datetime.now(dt_timezone.utc) - started_dt).total_seconds()
        metrics["uptime_seconds"] = round(uptime, 1)
    except Exception:
        metrics["uptime_seconds"] = None
    try:
        metrics["threads"] = threading.active_count()
    except Exception:
        metrics["threads"] = None
    try:
        import shutil
        from django.conf import settings
        usage = shutil.disk_usage(str(settings.BASE_DIR))
        metrics["disk_free_gb"] = round(usage.free / (1024 ** 3), 2)
        metrics["disk_used_pct"] = round(usage.used / usage.total * 100, 1)
    except Exception:
        metrics["disk_free_gb"] = None
    return metrics


def _domain_gauges():
    """Cheap, read-only business gauges — surface operational state without a dashboard."""
    gauges = {}
    try:
        from decimal import Decimal
        from django.db.models import Sum
        from django.utils import timezone as djtz
        from .models import Booking, Schedule, Payment
        now = djtz.now()
        cutoff_1h = now - timedelta(hours=1)
        cutoff_24h = now - timedelta(hours=24)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Booking state counts.
        gauges["pending_bookings"] = Booking.objects.filter(status="pending").count()
        gauges["confirmed_bookings"] = Booking.objects.filter(status="confirmed").count()
        gauges["cancelled_today"] = Booking.objects.filter(
            status="cancelled", booking_date__gte=today_start
        ).count()

        # Throughput — bookings created recently.
        gauges["bookings_last_1h"] = Booking.objects.filter(booking_date__gte=cutoff_1h).count()
        gauges["bookings_last_24h"] = Booking.objects.filter(booking_date__gte=cutoff_24h).count()

        # Revenue from confirmed bookings in the last 24 h.
        revenue = (
            Payment.objects.filter(
                payment_status="completed",
                booking__status="confirmed",
                booking__booking_date__gte=cutoff_24h,
            ).aggregate(total=Sum("amount"))["total"] or Decimal("0")
        )
        gauges["revenue_last_24h_fjd"] = float(revenue)

        # Schedule state.
        gauges["upcoming_schedules"] = Schedule.objects.filter(
            status="scheduled", departure_time__gt=now
        ).count()
        gauges["departing_next_2h"] = Schedule.objects.filter(
            status="scheduled",
            departure_time__gt=now,
            departure_time__lte=now + timedelta(hours=2),
        ).count()
    except Exception as e:  # pragma: no cover - only on DB outage / early boot
        gauges["error"] = str(e)[:160]
    return gauges


def _snapshot(pid, started_at, consecutive_failures=0):
    db_ok, db_err, db_ms = _timed(_check_database)
    cache_ok, cache_err, cache_ms = _timed(_check_cache)
    ch_ok, ch_err, ch_ms = _timed(_check_channel_layer)
    celery_ok, celery_err, celery_workers = _check_celery()
    healthy = db_ok and cache_ok
    snapshot = {
        "state": "running",
        "healthy": healthy,
        "severity": "ok" if healthy else ("critical" if consecutive_failures >= 3 else "warning"),
        "consecutive_failures": consecutive_failures,
        "pid": pid,
        "started_at": started_at,
        "checked_at": datetime.now(dt_timezone.utc).isoformat(),
        "checks": {
            "database": {"ok": db_ok, "error": db_err, "latency_ms": db_ms},
            "cache": {"ok": cache_ok, "error": cache_err, "latency_ms": cache_ms},
            "channel_layer": {"ok": ch_ok, "error": ch_err, "latency_ms": ch_ms},
            "celery": {"ok": celery_ok, "error": celery_err, "active_workers": celery_workers},
        },
        "system": _system_metrics(started_at),
    }
    # Domain gauges only make sense when the DB is reachable.
    if db_ok:
        snapshot["gauges"] = _domain_gauges()
    return snapshot


def _write_status(log_path, status_path, snapshot):
    try:
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except Exception:
        logger.exception("monitor: failed to write status file")
    level = logging.INFO if snapshot.get("healthy") else logging.ERROR
    checks = snapshot.get("checks", {})
    parts = []
    for k, v in checks.items():
        if k == "celery":
            parts.append(f"celery={'ok' if v['ok'] else 'FAIL'}(workers={v.get('active_workers', 0)})")
        else:
            parts.append(f"{k}={'ok' if v['ok'] else 'FAIL'}({v.get('latency_ms', '?')}ms)")
    gauges = snapshot.get("gauges", {})
    if gauges and not gauges.get("error"):
        parts.append(
            f"bookings(1h={gauges.get('bookings_last_1h', '?')} "
            f"24h={gauges.get('bookings_last_24h', '?')} "
            f"pending={gauges.get('pending_bookings', '?')})"
        )
    summary = " ".join(parts)
    severity = snapshot.get("severity", "ok")
    logger.log(level, "heartbeat pid=%s severity=%s %s",
               snapshot.get("pid"), severity, summary)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{snapshot['checked_at']}] {snapshot['state']} "
                    f"severity={severity} healthy={snapshot['healthy']} {summary}\n")
    except Exception:
        logger.exception("monitor: failed to append heartbeat log")


def _run(interval, pid, started_at):
    log_path, status_path = _status_paths()
    logger.info("Server monitor started (pid=%s, interval=%ss)", pid, interval)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{started_at}] STARTED pid={pid}\n")
    except Exception:
        pass
    # Loop until the process exits (daemon thread) or stop is requested.
    consecutive_failures = 0
    while not _stop_event.is_set():
        try:
            snapshot = _snapshot(pid, started_at, consecutive_failures)
            consecutive_failures = consecutive_failures + 1 if not snapshot["healthy"] else 0
            # Re-stamp severity now that the failure streak is updated.
            snapshot["consecutive_failures"] = consecutive_failures
            if snapshot["healthy"]:
                snapshot["severity"] = "ok"
            else:
                snapshot["severity"] = "critical" if consecutive_failures >= 3 else "warning"
            _write_status(log_path, status_path, snapshot)
        except Exception:
            logger.exception("monitor: tick failed")
        _stop_event.wait(interval)


def _on_exit(pid, started_at):
    """Record a clean shutdown when the server process is exiting."""
    _stop_event.set()
    try:
        log_path, status_path = _status_paths()
        stopped = {
            "state": "stopped",
            "healthy": False,
            "pid": pid,
            "started_at": started_at,
            "checked_at": datetime.now(dt_timezone.utc).isoformat(),
            "checks": {},
        }
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(stopped, f, indent=2)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{stopped['checked_at']}] STOPPED pid={pid}\n")
        logger.info("Server monitor stopped (pid=%s)", pid)
    except Exception:
        pass


def _is_server_process():
    """True only when this process is actually serving requests."""
    argv = sys.argv or []
    joined = " ".join(argv).lower()
    # Daphne / uvicorn / gunicorn launch the ASGI/WSGI app directly.
    if any(s in joined for s in ("daphne", "uvicorn", "gunicorn", "asgi", "wsgi")):
        return True
    if "runserver" in argv:
        return True
    # Any management command in the deny-list is not a server.
    for cmd in argv[1:]:
        if cmd in _NON_SERVER_COMMANDS:
            return False
    return False


def start_monitor():
    """Start the monitor daemon thread once, if this is a server process.

    Safe to call from AppConfig.ready(); it self-guards against:
      * non-server management commands,
      * the runserver autoreloader's parent process (RUN_MAIN),
      * being started more than once.
    """
    global _monitor_thread
    from django.conf import settings

    if not getattr(settings, "SERVER_MONITOR_ENABLED", True):
        return
    if not _is_server_process():
        return
    # Under `runserver` with the autoreloader, Django spawns a reloader parent;
    # only the child (RUN_MAIN=true) should run the monitor. With --noreload
    # there is no child and RUN_MAIN is unset, so don't gate on it then.
    argv = sys.argv or []
    if "runserver" in argv and "--noreload" not in argv and os.environ.get("RUN_MAIN") != "true":
        return
    if _monitor_thread is not None and _monitor_thread.is_alive():
        return

    interval = int(getattr(settings, "SERVER_MONITOR_INTERVAL", 15))
    pid = os.getpid()
    started_at = datetime.now(dt_timezone.utc).isoformat()
    _stop_event.clear()
    _monitor_thread = threading.Thread(
        target=_run, args=(interval, pid, started_at),
        name="server-monitor", daemon=True,
    )
    _monitor_thread.start()
    atexit.register(_on_exit, pid, started_at)
