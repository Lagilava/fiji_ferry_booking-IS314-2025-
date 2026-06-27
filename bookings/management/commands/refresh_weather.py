"""Refresh weather for all routes that have upcoming, active schedules.

Run on a schedule (cron / Task Scheduler / Celery beat) so the homepage and the
admin dashboard always show current conditions even before any visitor triggers
an on-demand fetch:

    python manage.py refresh_weather

Uses the free, key-less Open-Meteo provider, so it costs nothing.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from bookings.models import Route, Schedule
from bookings.weather.provider import fetch_and_store_weather


class Command(BaseCommand):
    help = "Fetch and store current weather for all routes with upcoming active schedules."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all-routes", action="store_true",
            help="Refresh every route, not just those with upcoming active schedules.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        if options["all_routes"]:
            route_ids = Route.objects.values_list("id", flat=True)
        else:
            route_ids = (
                Schedule.objects
                .filter(status="scheduled", departure_time__gt=now)
                .values_list("route_id", flat=True)
                .distinct()
            )

        routes = Route.objects.select_related("departure_port").filter(id__in=list(route_ids))
        ok, failed = 0, 0
        for route in routes:
            result = fetch_and_store_weather(route)
            if result:
                ok += 1
                self.stdout.write(
                    f"  [ok] {route.departure_port.name}: "
                    f"{result['condition']} {result['temperature']}C"
                )
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"  [--] {route} - no data"))

        self.stdout.write(self.style.SUCCESS(
            f"Weather refreshed for {ok} route(s); {failed} failed."
        ))
