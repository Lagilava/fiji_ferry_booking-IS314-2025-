"""Seed/refresh active ferries, routes, and upcoming schedules (idempotent).

Usage:
    python manage.py ensure_demo_data            # next 7 days
    python manage.py ensure_demo_data --days 14
"""
from django.core.management.base import BaseCommand

from bookings.seed import ensure_demo_data


class Command(BaseCommand):
    help = "Idempotently ensure active ferries, routes, and upcoming schedules exist."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=7)

    def handle(self, *args, **opts):
        summary = ensure_demo_data(days=opts["days"])
        self.stdout.write(self.style.SUCCESS(
            f"OK: created {summary['created']} schedules; "
            f"{summary['upcoming']} upcoming across {summary['routes']} routes / "
            f"{summary['ferries']} ferries."))
