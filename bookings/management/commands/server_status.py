"""Offline server-status inspector.

Reads the snapshot written by the in-process monitor (bookings/monitor.py) and
reports whether the server is running, stale (heartbeat too old -> likely
crashed/killed), or cleanly stopped. Works without the live server.

Usage:
    python manage.py server_status
    python manage.py server_status --json
"""
import json
import os
from datetime import datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Report the server status recorded by the in-process monitor (offline)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit raw JSON.")

    def handle(self, *args, **opts):
        path = os.path.join(settings.BASE_DIR, "logs", "server_status.json")
        if not os.path.exists(path):
            self.stdout.write(self.style.WARNING("No status file yet — the server has not run with the monitor."))
            return

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        interval = int(getattr(settings, "SERVER_MONITOR_INTERVAL", 15))
        # If the last heartbeat is older than ~3 intervals while state=running,
        # the process almost certainly died without a clean shutdown.
        derived = data.get("state", "unknown")
        age = None
        try:
            checked = datetime.fromisoformat(data["checked_at"])
            age = (datetime.now(timezone.utc) - checked).total_seconds()
            if derived == "running" and age > max(interval * 3, 30):
                derived = "stale (no recent heartbeat — server likely down)"
        except Exception:
            pass

        if opts["json"]:
            data["derived_state"] = derived
            data["heartbeat_age_seconds"] = age
            self.stdout.write(json.dumps(data, indent=2))
            return

        healthy = data.get("healthy")
        style = self.style.SUCCESS if (derived == "running" and healthy) else self.style.ERROR
        self.stdout.write(style(f"State:   {derived}"))
        self.stdout.write(f"Healthy: {healthy}")
        self.stdout.write(f"PID:     {data.get('pid')}")
        self.stdout.write(f"Started: {data.get('started_at')}")
        self.stdout.write(f"Last check: {data.get('checked_at')}"
                          + (f" ({age:.0f}s ago)" if age is not None else ""))
        for name, c in (data.get("checks") or {}).items():
            mark = "ok" if c.get("ok") else f"FAIL ({c.get('error')})"
            self.stdout.write(f"  - {name}: {mark}")
