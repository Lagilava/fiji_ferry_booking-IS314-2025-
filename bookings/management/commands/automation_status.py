"""Read the last automation-agent result offline.

Usage:
    python manage.py automation_status
    python manage.py automation_status --json
"""
import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Show the most recent automation-agent battery result (offline)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit raw JSON.")

    def handle(self, *args, **opts):
        path = os.path.join(settings.BASE_DIR, "logs", "automation_status.json")
        if not os.path.exists(path):
            self.stdout.write(self.style.WARNING(
                "No automation results yet — the agent has not run with the server."))
            return
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if opts["json"]:
            self.stdout.write(json.dumps(data, indent=2))
            return
        head = self.style.SUCCESS if data.get("ok") else self.style.ERROR
        self.stdout.write(head(f"{data.get('passed')}/{data.get('total')} passed "
                               f"(ran {data.get('ran_at')})"))
        for c in data.get("checks", []):
            mark = "PASS" if c["ok"] else "FAIL"
            detail = f"  ({c['detail']})" if c.get("detail") else ""
            self.stdout.write(f"  [{mark}] {c['name']}{detail}")
