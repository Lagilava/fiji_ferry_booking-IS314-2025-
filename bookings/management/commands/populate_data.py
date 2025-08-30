from django.core.management.base import BaseCommand
from django.utils import timezone
from bookings.models import Port, Route, Schedule, Ferry
import random
import math
from datetime import timedelta, datetime, time
from django.db import transaction

class Command(BaseCommand):
    help = 'Populates Port, Route, and Schedule models with data, ensuring unique routes and one schedule per route.'

    def haversine(self, lat1, lon1, lat2, lon2):
        """Calculate distance between two points using the Haversine formula."""
        R = 6371  # Earth's radius in km
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return R * c

    def add_arguments(self, parser):
        parser.add_argument('--num_ports', type=int, default=5, help='Number of ports to create')
        parser.add_argument('--num_routes', type=int, default=5, help='Number of routes to create')

    def handle(self, *args, **options):
        num_ports = options['num_ports']
        num_routes = min(options['num_routes'], num_ports * (num_ports - 1))  # Max possible unique routes

        with transaction.atomic():
            # Create a default ferry if none exists
            if not Ferry.objects.exists():
                Ferry.objects.create(
                    name="Fiji Star",
                    operator="Fiji Ferries",
                    capacity=200,
                    description="Standard ferry for regional routes",
                    is_active=True,
                    cruise_speed_knots=25.0,
                    turnaround_minutes=480,
                    max_daily_hours=12.0,
                    overnight_allowed=False
                )
                self.stdout.write(self.style.SUCCESS('Created default ferry: Fiji Star'))

            # Create ports if none exist
            if not Port.objects.exists():
                port_names = [
                    'Suva', 'Lautoka', 'Nadi', 'Levuka', 'Savusavu',
                    'Labasa', 'Taveuni', 'Kadavu', 'Rotuma', 'Vanua Levu'
                ]
                random.shuffle(port_names)
                for i in range(min(num_ports, len(port_names))):
                    lat = random.uniform(-21.0, -16.0)
                    lng = random.uniform(176.0, 181.0)
                    Port.objects.create(
                        name=port_names[i],
                        lat=lat,
                        lng=lng,
                        operating_hours_start=time(6, 0),
                        operating_hours_end=time(20, 0),
                        berths=random.randint(1, 3),
                        tide_sensitive=random.choice([True, False]),
                        night_ops_allowed=random.choice([True, False])
                    )
                self.stdout.write(self.style.SUCCESS(f'Created {num_ports} ports'))

            # Create routes if none exist
            if not Route.objects.exists():
                ports = list(Port.objects.all())
                if len(ports) < 2:
                    self.stdout.write(self.style.ERROR('Need at least 2 ports to create routes'))
                    return

                # Generate all possible unique routes
                possible_routes = []
                for i, dep_port in enumerate(ports):
                    for dest_port in ports[i + 1:]:
                        if dep_port != dest_port:
                            distance = self.haversine(
                                dep_port.lat, dep_port.lng, dest_port.lat, dest_port.lng
                            )
                            possible_routes.append((dep_port, dest_port, distance))

                # Sort routes by distance (longest to shortest)
                possible_routes.sort(key=lambda x: x[2], reverse=True)
                selected_routes = possible_routes[:num_routes]

                for dep_port, dest_port, distance in selected_routes:
                    # Estimate duration based on average ferry speed (25 knots = ~46.3 km/h)
                    hours = distance / 46.3
                    duration = timedelta(hours=hours)
                    base_fare = round(distance * 0.5, 2)  # Simplified fare calculation
                    Route.objects.create(
                        departure_port=dep_port,
                        destination_port=dest_port,
                        distance_km=distance,
                        estimated_duration=duration,
                        base_fare=base_fare,
                        service_tier=random.choice(['major', 'regional', 'remote']),
                        min_weekly_services=7,
                        preferred_departure_windows=['06:00-08:00', '12:00-14:00'],
                        safety_buffer_minutes=15,
                        waypoints=[]
                    )
                self.stdout.write(self.style.SUCCESS(f'Created {len(selected_routes)} routes'))

            # Create schedules, one per route, with random routes
            routes = list(Route.objects.all())
            if not routes:
                self.stdout.write(self.style.ERROR('No routes available to create schedules'))
                return

            ferry = Ferry.objects.first()
            used_routes = set()
            today = timezone.now().date()

            for route in random.sample(routes, min(len(routes), num_routes)):
                if route.id not in used_routes:
                    # Random departure time within operating hours (06:00-20:00)
                    start_hour = 6
                    end_hour = 20
                    hour = random.randint(start_hour, end_hour - 1)
                    minute = random.choice([0, 15, 30, 45])
                    departure_time = timezone.make_aware(
                        datetime.combine(today, time(hour, minute))
                    )
                    arrival_time = departure_time + route.estimated_duration + timedelta(minutes=route.safety_buffer_minutes)

                    Schedule.objects.create(
                        ferry=ferry,
                        route=route,
                        departure_time=departure_time,
                        arrival_time=arrival_time,
                        estimated_duration=str(route.estimated_duration),
                        available_seats=ferry.capacity,
                        status='scheduled',
                        operational_day=today,
                        notes='Auto-generated schedule'
                    )
                    used_routes.add(route.id)
                    self.stdout.write(self.style.SUCCESS(f'Created schedule for {route}'))

            self.stdout.write(self.style.SUCCESS('Data population completed'))