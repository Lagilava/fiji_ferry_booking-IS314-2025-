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
from datetime import datetime, timezone as dt_timezone

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


def _snapshot(pid, started_at):
    db_ok, db_err = _check_database()
    cache_ok, cache_err = _check_cache()
    ch_ok, ch_err = _check_channel_layer()
    healthy = db_ok and cache_ok
    return {
        "state": "running",
        "healthy": healthy,
        "pid": pid,
        "started_at": started_at,
        "checked_at": datetime.now(dt_timezone.utc).isoformat(),
        "checks": {
            "database": {"ok": db_ok, "error": db_err},
            "cache": {"ok": cache_ok, "error": cache_err},
            "channel_layer": {"ok": ch_ok, "error": ch_err},
        },
    }


def _write_status(log_path, status_path, snapshot):
    try:
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2)
    except Exception:
        logger.exception("monitor: failed to write status file")
    level = logging.INFO if snapshot.get("healthy") else logging.ERROR
    checks = snapshot.get("checks", {})
    summary = " ".join(f"{k}={'ok' if v['ok'] else 'FAIL'}" for k, v in checks.items())
    logger.log(level, "heartbeat pid=%s healthy=%s %s",
               snapshot.get("pid"), snapshot.get("healthy"), summary)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{snapshot['checked_at']}] {snapshot['state']} "
                    f"healthy={snapshot['healthy']} {summary}\n")
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
    while not _stop_event.is_set():
        try:
            _write_status(log_path, status_path, _snapshot(pid, started_at))
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
