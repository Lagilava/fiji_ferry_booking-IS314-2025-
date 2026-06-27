"""Run the cybersecurity agent's security-posture audit on demand (offline).

Usage:
    python manage.py security_audit
    python manage.py security_audit --json

Exits non-zero when a CRITICAL finding is present, so it is usable as a CI gate.
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the read-only security-posture audit and print findings."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit raw JSON.")

    def handle(self, *args, **opts):
        from bookings.security import run_audit
        data = run_audit()

        if opts["json"]:
            self.stdout.write(json.dumps(data, indent=2))
        else:
            head = self.style.SUCCESS if data["ok"] else self.style.ERROR
            self.stdout.write(head(
                f"{data['passed']}/{data['total']} ok · "
                f"{data['critical_count']} critical · {data['warning_count']} warning "
                f"(ran {data['ran_at']})"
            ))
            for c in data["checks"]:
                if c["ok"]:
                    mark, style = "PASS", self.style.SUCCESS
                elif c["severity"] == "critical":
                    mark, style = "CRIT", self.style.ERROR
                else:
                    mark, style = "WARN", self.style.WARNING
                detail = f"  ({c['detail']})" if c.get("detail") else ""
                self.stdout.write(style(f"  [{mark}] {c['name']}{detail}"))

        if data["critical_count"]:
            raise SystemExit(1)
