from django.core.management.base import BaseCommand
from django.utils import timezone
from bookings.models import Port, Route, Schedule, Ferry
import random
import math
from datetime import timedelta, datetime, time
from django.db import transaction


class Command(BaseCommand):
    help = 'Auto-create schedules for all ferries, starting two days from now.'

    def haversine(self, lat1, lon1, lat2, lon2):
        """Calculate distance between two points using Haversine formula."""
        R = 6371  # km
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return R * c

    def handle(self, *args, **options):
        with transaction.atomic():
            ferries = list(Ferry.objects.filter(is_active=True))
            routes = list(Route.objects.all())
            if not ferries or not routes:
                self.stdout.write(self.style.ERROR('No ferries or routes available'))
                return

            # Start date is 2 days from now
            start_date = timezone.now().date() + timedelta(days=2)

            for ferry in ferries:
                for route in routes:
                    # Random departure time within route's preferred window or operating hours
                    start_hour = 6
                    end_hour = 20
                    hour = random.randint(start_hour, end_hour - 1)
                    minute = random.choice([0, 15, 30, 45])

                    departure_time = timezone.make_aware(datetime.combine(start_date, time(hour, minute)))
                    arrival_time = departure_time + route.estimated_duration + timedelta(
                        minutes=route.safety_buffer_minutes)

                    Schedule.objects.create(
                        ferry=ferry,
                        route=route,
                        departure_time=departure_time,
                        arrival_time=arrival_time,
                        estimated_duration=route.estimated_duration,
                        available_seats=ferry.capacity,
                        status='scheduled',
                        operational_day=start_date,
                        notes='Auto-generated schedule'
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f'Created schedule: {route} with ferry {ferry.name} on {start_date}'))

            self.stdout.write(self.style.SUCCESS('All schedules created successfully.'))
