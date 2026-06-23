"""Run the offline automation self-test battery on demand.

Usage:
    python manage.py run_automation
    python manage.py run_automation --json

Exit code is non-zero if any check fails (handy for CI / cron).
"""
import json
import sys

from django.core.management.base import BaseCommand

from bookings.automation import run_battery


class Command(BaseCommand):
    help = "Run the non-destructive, offline automation check battery."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit raw JSON.")

    def handle(self, *args, **opts):
        result = run_battery()
        if opts["json"]:
            self.stdout.write(json.dumps(result, indent=2))
        else:
            head = self.style.SUCCESS if result["ok"] else self.style.ERROR
            self.stdout.write(head(f"{result['passed']}/{result['total']} checks passed "
                                   f"({result['ran_at']})"))
            for c in result["checks"]:
                mark = "PASS" if c["ok"] else "FAIL"
                style = self.style.SUCCESS if c["ok"] else self.style.ERROR
                detail = f"  ({c['detail']})" if c["detail"] else ""
                self.stdout.write(style(f"  [{mark}] {c['name']}{detail}"))
        if not result["ok"]:
            sys.exit(1)
