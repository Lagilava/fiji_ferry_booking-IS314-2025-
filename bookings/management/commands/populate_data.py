from typing import Optional, Dict, List
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Count
from bookings.models import Port, Route, Schedule, Ferry
import random
import math
import json
from decimal import Decimal
from datetime import timedelta, datetime, time, date
from django.core.exceptions import ValidationError
from collections import defaultdict, Counter
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = """
    DEVELOPMENT TOOL: Generate realistic Fiji ferry test data.

    ⚠️  WARNING: For development/testing only. NOT production data.
    - Based on approximate real routes and operators (Goundar, Patterson, etc.)
    - Frequencies and fares are estimates from public sources
    - No weather, maintenance, or regulatory modeling
    - Use real operator APIs/data for production systems
    """

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Full reset of all data')
        parser.add_argument('--reset-schedules', action='store_true', help='Reset auto-generated schedules only')
        parser.add_argument('--days-ahead', type=int, default=30, help='Schedule horizon')
        parser.add_argument('--relaxed', action='store_true', help='Skip strict validation')
        parser.add_argument('--debug', action='store_true', help='Verbose debugging')
        parser.add_argument('--bidirectional', action='store_true', default=True, help='Create return routes')
        parser.add_argument('--realistic-fares', action='store_true', default=True, help='Use realistic fare structure')
        parser.add_argument('--analytics', action='store_true', help='Generate usage analytics')
        parser.add_argument('--validate', action='store_true', help='Run data validation checks')

    def haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate great-circle distance between two points in km."""
        R = 6371  # Earth radius in km
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        return 6371 * 2 * math.asin(math.sqrt(a))

    def parse_time_window(self, window_str: str) -> tuple:
        """Parse time window string with robust error handling."""
        try:
            start_str, end_str = window_str.split('-')
            start_hour = int(start_str.split(':')[0])
            end_hour = int(end_str.split(':')[0])
            return max(0, min(23, start_hour)), max(0, min(23, end_hour))
        except Exception:
            logger.warning(f"Invalid time window '{window_str}', using default 06:00-08:00")
            return 6, 8

    def format_duration_safely(self, duration: timedelta) -> str:
        """Format duration string safely within CharField(max_length=50) limit."""
        total_seconds = int(duration.total_seconds())
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        duration_str = f"{hours}h"
        if minutes > 0:
            duration_str += f" {minutes}m"
        return duration_str[:50]

    def realistic_route_configs(self) -> List[Dict]:
        """Realistic Fiji ferry routes based on actual operators and published schedules."""
        # Sources: Goundar Shipping, Patterson Brothers, public announcements
        return [
            # Goundar Shipping: Suva-Natovi (main departure point)
            {
                "dep": "Suva", "dest": "Natovi", "tier": "major",
                "min_weekly": 7, "priority": 9, "base_fare": 25.0,
                "windows": ["06:00-08:00", "16:00-18:00"],
                "operator_preference": "Goundar Shipping",
                "notes": "Daily service via Goundar main route to connect with Levuka ferry"
            },
            # Patterson Brothers: Natovi-Levuka vehicle ferry
            {
                "dep": "Natovi", "dest": "Levuka", "tier": "major",
                "min_weekly": 4, "priority": 8, "base_fare": 35.0,
                "windows": ["12:00-14:00", "18:00-20:00"],
                "operator_preference": "Patterson Brothers Shipping",
                "notes": "Vehicle transport 4x weekly, essential lifeline"
            },
            # Suva-Kadavu regional service
            {
                "dep": "Suva", "dest": "Kadavu (Vunisea)", "tier": "regional",
                "min_weekly": 2, "priority": 6, "base_fare": 75.0,
                "windows": ["05:00-07:00"],
                "operator_preference": "Various",
                "notes": "Bi-weekly essential service to southern islands"
            },
            # Northern route connectivity
            {
                "dep": "Natovi", "dest": "Nabouwalu", "tier": "regional",
                "min_weekly": 3, "priority": 5, "base_fare": 50.0,
                "windows": ["06:00-08:00"],
                "operator_preference": "Various",
                "notes": "Regional connectivity 3x weekly for northern islands"
            },
            # Rotuma - monthly service only (realistic for remote)
            {
                "dep": "Suva", "dest": "Rotuma", "tier": "remote",
                "min_weekly": 0.25,  # ~1 per month
                "priority": 2, "base_fare": 300.0,
                "windows": ["04:00-06:00"],
                "operator_preference": "Interlink Shipping",
                "notes": "Monthly remote lifeline service, 2-3 day journey",
                "irregular": True
            }
        ]

    def realistic_fare_structure(self, route_key: str) -> Decimal:
        """Realistic fares based on actual Fiji ferry pricing from operator websites."""
        # Approximate fares from Goundar, Patterson Brothers announcements
        real_fares = {
            'Suva-Natovi': 25.0,
            'Natovi-Levuka': 35.0,
            'Suva-Kadavu': 75.0,
            'Natovi-Nabouwalu': 50.0,
            'Suva-Rotuma': 300.0,
        }
        return Decimal(str(real_fares.get(route_key, 50.0)))

    def classify_ferry_capabilities(self, ferry: Ferry) -> Dict:
        """Classify ferry capabilities using model fields."""
        speed = ferry.cruise_speed_knots
        capacity = ferry.capacity
        turnaround_h = ferry.turnaround_minutes / 60.0

        classification = {
            "is_fast": speed >= 20,
            "is_large": capacity >= 500,
            "is_vehicle_capable": turnaround_h <= 8.0,
            "is_overnight": ferry.overnight_allowed,
            "daily_trips_max": max(1, int(ferry.max_daily_hours / (turnaround_h + 2)))
        }

        # Simple type classification
        if speed >= 20 and capacity < 300:
            classification["type"] = "fast_catamaran"
        elif capacity >= 500:
            classification["type"] = "large_ro_ro"
        else:
            classification["type"] = "regional_ferry"

        return classification

    def find_available_departure_slot(self, port: Port, operational_day: date,
                                      preferred_windows: List[str], relaxed: bool = False) -> Optional[datetime]:
        """Find available departure slot respecting port capacity and operating hours."""
        # Check existing schedules for this port on this day
        schedules_today = Schedule.objects.filter(
            operational_day=operational_day,
            route__departure_port=port,
            status='scheduled'
        )

        occupied_hours = Counter()
        for sched in schedules_today:
            hour = sched.departure_time.hour
            occupied_hours[hour] += 1

        # Score preferred windows first
        best_slot = None
        best_score = 0

        for window in preferred_windows:
            start_h, end_h = self.parse_time_window(window)
            for hour in range(start_h, min(end_h + 1, 24)):
                if not self.validate_port_hours(port,
                                                timezone.make_aware(datetime.combine(operational_day, time(hour, 0)))):
                    continue

                conflicts = occupied_hours.get(hour, 0)
                capacity_ratio = conflicts / max(1, port.berths)

                # Score: prefer less conflicted slots in preferred windows during daytime
                score = (1.0 - capacity_ratio) * 0.8 + (0.2 if 6 <= hour <= 20 else 0.1)

                if score > best_score and capacity_ratio < 1.0:  # Berth available
                    best_score = score
                    minutes = random.choice([0, 30])
                    best_slot = timezone.make_aware(
                        datetime.combine(operational_day, time(hour, minutes))
                    )

        # Fallback to any available slot in operating hours
        if not best_slot and not relaxed:
            best_slot = self.fallback_slot(port, operational_day)

        return best_slot

    def fallback_slot(self, port: Port, operational_day: date) -> Optional[datetime]:
        """Fallback to first available slot within operating hours."""
        port_start = port.operating_hours_start
        port_end = port.operating_hours_end

        test_hour = port_start.hour
        while test_hour <= port_end.hour:
            test_time = timezone.make_aware(datetime.combine(operational_day, time(test_hour, 0)))
            if self.validate_port_hours(port, test_time):
                return test_time
            test_hour += 1
        return None

    def score_ferry_candidates(self, route: Route, candidate_ferries: List[Ferry]) -> Optional[Ferry]:
        """Score ferries based on route requirements and capabilities."""
        if not candidate_ferries:
            return None

        distance_km = float(route.distance_km)
        best_ferry = None
        best_score = -1

        for ferry in candidate_ferries:
            # Calculate trip time feasibility
            speed_kph = ferry.cruise_speed_knots * 1.852  # knots to kph
            est_hours = distance_km / max(speed_kph, 10)  # min 10 kph fallback

            if est_hours > ferry.max_daily_hours * 1.2:  # 20% buffer
                continue

            # Scoring: speed efficiency + capacity suitability + overnight capability
            speed_score = min(1.0, ferry.cruise_speed_knots / 20.0)
            capacity_score = min(1.0, ferry.capacity / 500.0)
            overnight_bonus = 0.2 if (distance_km > 150 and ferry.overnight_allowed) else 0

            score = (speed_score * 0.5 + capacity_score * 0.3 + overnight_bonus * 0.2)

            if score > best_score:
                best_score = score
                best_ferry = ferry

        return best_ferry or random.choice(candidate_ferries)

    def get_suitable_ferries(self, route: Route) -> List[Ferry]:
        """Filter ferries that can realistically service this route."""
        distance_km = float(route.distance_km)
        candidates = []

        for ferry in Ferry.objects.filter(is_active=True):
            speed_kph = ferry.cruise_speed_knots * 1.852
            est_hours = distance_km / max(speed_kph, 10)

            # Basic suitability check
            if est_hours <= ferry.max_daily_hours * 1.5:  # Generous buffer for testing
                candidates.append(ferry)

        return candidates if candidates else list(Ferry.objects.filter(is_active=True))

    def create_realistic_route(self, dep_port: Port, dest_port: Port, config: Dict,
                               is_return: bool = False) -> Optional[Route]:
        """Create route with realistic parameters matching model constraints."""
        route_key = f"{dep_port.name}-{dest_port.name}"

        if Route.objects.filter(
                departure_port=dep_port,
                destination_port=dest_port
        ).exists():
            return None

        distance = self.haversine(dep_port.lat, dep_port.lng, dest_port.lat, dest_port.lng)

        # Use realistic fares or fallback calculation
        if self.realistic_fares:
            base_fare = self.realistic_fare_structure(route_key)
        else:
            base_fare = max(Decimal('15.00'), Decimal(str(distance * 0.5)))

        if is_return:
            base_fare *= Decimal('0.90')  # 10% return discount
            config_min = max(1, config['min_weekly'] - 2)
            config['min_weekly'] = int(config_min)

        # Conservative duration estimate at 15 knots average speed
        avg_speed_kph = 15 * 1.852
        duration_hours = distance / avg_speed_kph
        estimated_duration = timedelta(hours=duration_hours)

        try:
            route = Route.objects.create(
                departure_port=dep_port,
                destination_port=dest_port,
                distance_km=Decimal(str(round(distance, 2))),
                estimated_duration=estimated_duration,
                base_fare=base_fare,
                service_tier=config['tier'],
                min_weekly_services=config['min_weekly'],
                preferred_departure_windows=config['windows'],
                safety_buffer_minutes=30 if config['tier'] == 'remote' else 15,
                waypoints=[],
            )

            direction = "RETURN" if is_return else "FORWARD"
            self.stdout.write(
                self.style.SUCCESS(
                    f"🛤️ {direction}: {dep_port.name}→{dest_port.name} "
                    f"({distance:.1f}km, FJD${base_fare}, ~{config['min_weekly']}x/wk)"
                )
            )
            return route

        except Exception as e:
            logger.error(f"Route creation failed for {route_key}: {e}")
            return None

    def create_realistic_schedule(self, route: Route, operational_day: date,
                                  relaxed: bool = False) -> Optional[Schedule]:
        """Create schedule with basic conflict checking and port validation."""
        ferries = self.get_suitable_ferries(route)
        if not ferries:
            if self.debug:
                self.stdout.write(self.style.WARNING(f"No suitable ferries for {route}"))
            return self.force_create_schedule(route, operational_day)

        # Find available departure slot
        dep_time = self.find_available_departure_slot(
            route.departure_port, operational_day,
            route.preferred_departure_windows, relaxed
        )

        if not dep_time and not relaxed:
            if self.debug:
                self.stdout.write(self.style.WARNING(f"No available slot for {route}"))
            return self.force_create_schedule(route, operational_day)

        if not dep_time:
            return None

        # Select best ferry
        ferry = self.score_ferry_candidates(route, ferries)

        # Calculate precise timing
        distance_km = float(route.distance_km)
        speed_kph = ferry.cruise_speed_knots * 1.852
        duration_hours = distance_km / speed_kph
        duration = timedelta(hours=duration_hours)
        arr_time = dep_time + duration + timedelta(minutes=route.safety_buffer_minutes)

        # Realistic capacity allocation (70% load factor for testing)
        available_seats = max(10, int(ferry.capacity * 0.7))

        # Final port hours validation
        if not relaxed and not self.validate_port_hours(route.departure_port, dep_time):
            if self.debug:
                self.stdout.write(self.style.WARNING(f"Port hours violation for {route}"))
            return self.force_create_schedule(route, operational_day)

        try:
            duration_str = self.format_duration_safely(duration)
            schedule = Schedule.objects.create(
                ferry=ferry,
                route=route,
                departure_time=dep_time,
                arrival_time=arr_time,
                estimated_duration=duration_str,
                available_seats=available_seats,
                status="scheduled",
                operational_day=operational_day,
                notes=f"Test schedule - {ferry.operator}",
                created_by_auto=True,
            )

            if self.debug:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"📅 {route}: {dep_time.strftime('%H:%M')}→{arr_time.strftime('%H:%M')} "
                        f"({ferry.name}, {available_seats} seats)"
                    )
                )
            return schedule

        except Exception as e:
            logger.error(f"Schedule creation failed: {e}")
            return self.force_create_schedule(route, operational_day)

    def validate_port_hours(self, port: Port, dep_time: datetime) -> bool:
        """Validate departure time against port operating hours."""
        if not dep_time:
            return False

        port_start = port.operating_hours_start
        port_end = port.operating_hours_end
        dep_time_obj = dep_time.time()

        # Handle overnight operations (end time before start time)
        if port_end < port_start:
            return dep_time_obj >= port_start or dep_time_obj <= port_end
        return port_start <= dep_time_obj <= port_end

    def force_create_schedule(self, route: Route, operational_day: date) -> Optional[Schedule]:
        """Fallback schedule creation when constraints can't be met."""
        ferries = list(Ferry.objects.filter(is_active=True))
        if not ferries:
            logger.error("No active ferries available")
            return None

        ferry = random.choice(ferries)

        # Default to morning departure
        dep_hour = 8
        dep_time = timezone.make_aware(datetime.combine(operational_day, time(dep_hour, 0)))

        distance_km = float(route.distance_km)
        speed_kph = max(ferry.cruise_speed_knots * 1.852, 10)  # Minimum 10 kph
        duration = timedelta(hours=distance_km / speed_kph)
        arr_time = dep_time + duration + timedelta(minutes=route.safety_buffer_minutes)

        try:
            schedule = Schedule.objects.create(
                ferry=ferry,
                route=route,
                departure_time=dep_time,
                arrival_time=arr_time,
                estimated_duration=self.format_duration_safely(duration),
                available_seats=ferry.capacity // 2,  # Conservative capacity
                status="scheduled",
                operational_day=operational_day,
                notes=f"Fallback test schedule - {ferry.operator}",
                created_by_auto=True,
            )
            self.stdout.write(self.style.WARNING(
                f"⚠️  Fallback: {route} on {operational_day} {dep_hour}:00"
            ))
            return schedule
        except Exception as e:
            logger.error(f"Fallback schedule creation failed: {e}")
            return None

    def ensure_minimum_services(self, route: Route, days_ahead: int) -> int:
        """Ensure minimum service levels are met for testing purposes."""
        weekly_target = route.min_weekly_services
        weeks = max(1, days_ahead // 7)
        total_target = int(weekly_target * weeks)

        # Count existing auto-generated schedules
        existing = Schedule.objects.filter(
            route=route,
            status='scheduled',
            created_by_auto=True
        ).count()

        needed = max(0, total_target - existing)
        if needed == 0:
            return 0

        created = 0
        start_date = timezone.now().date()

        if self.debug:
            self.stdout.write(f"🛡️  Ensuring {needed} minimum services for {route}")

        for i in range(needed):
            # Space out minimum services roughly weekly
            day_offset = i * 7 % days_ahead
            op_day = start_date + timedelta(days=day_offset)

            if not Schedule.objects.filter(
                    route=route,
                    operational_day=op_day,
                    status='scheduled'
            ).exists():
                schedule = self.create_realistic_schedule(route, op_day, relaxed=True)
                if schedule:
                    created += 1

        return created

    def deploy_realistic_fleet(self):
        """Deploy fleet based on real Fiji ferry operators with correct model field names."""
        if Ferry.objects.exists() and not self.reset:
            self.stdout.write(self.style.WARNING("⏭️ Fleet already deployed"))
            return

        fleet_configs = [
            {
                "name": "Lomaiviti Princess",
                "operator": "Goundar Shipping",
                "capacity": 800,
                "cruise_speed_knots": 17.5,
                "turnaround_minutes": 540,
                "max_daily_hours": 16.0,
                "overnight_allowed": True,
                "description": "Mainline Ro-Ro ferry for inter-island service",
                "is_active": True,
            },
            {
                "name": "Ovalau Express",
                "operator": "Patterson Brothers Shipping",
                "capacity": 300,
                "cruise_speed_knots": 15.0,
                "turnaround_minutes": 480,
                "max_daily_hours": 14.0,
                "overnight_allowed": True,
                "description": "Vehicle and passenger ferry for Levuka route",
                "is_active": True,
            },
            {
                "name": "Yasawa Flyer",
                "operator": "Awesome Adventures Fiji",
                "capacity": 250,
                "cruise_speed_knots": 25.0,
                "turnaround_minutes": 240,
                "max_daily_hours": 10.0,
                "overnight_allowed": False,
                "description": "High-speed tourist catamaran",
                "is_active": True,
            },
            {
                "name": "Northern Ranger",
                "operator": "Interlink Shipping",
                "capacity": 150,
                "cruise_speed_knots": 14.0,
                "turnaround_minutes": 720,
                "max_daily_hours": 18.0,
                "overnight_allowed": True,
                "description": "Cargo and passenger service to remote islands",
                "is_active": True,
            }
        ]

        deployed = 0
        for config in fleet_configs:
            if not Ferry.objects.filter(name=config["name"]).exists():
                try:
                    # Create without home_port first (ports created later)
                    ferry = Ferry.objects.create(**config)
                    deployed += 1
                    if self.debug:
                        self.stdout.write(self.style.SUCCESS(f"🚢 Deployed {config['name']}"))
                except Exception as e:
                    logger.error(f"Failed to create ferry {config['name']}: {e}")

        self.stdout.write(self.style.SUCCESS(f"🚢 Successfully deployed {deployed} vessels"))

    def deploy_realistic_ports(self):
        """Deploy Fiji ports with realistic operating parameters."""
        if Port.objects.exists() and not self.reset:
            self.stdout.write(self.style.WARNING("⏭️ Ports already deployed"))
            return

        port_data = [
            # Major hubs
            ("Suva", -18.1405, 178.4233, time(4, 0), time(23, 59), 6, False, True),
            ("Natovi", -17.9833, 178.3167, time(6, 0), time(21, 0), 3, True, False),
            # Island ports
            ("Levuka", -17.6833, 178.8333, time(7, 0), time(19, 0), 2, True, False),
            ("Nabouwalu", -16.6333, 178.9500, time(7, 0), time(18, 0), 2, True, False),
            ("Kadavu (Vunisea)", -19.0500, 178.2000, time(6, 0), time(19, 0), 1, True, False),
            # Remote
            ("Rotuma", -12.5167, 177.1333, time(8, 0), time(17, 0), 1, True, False)
        ]

        deployed = 0
        suva_port = None
        natovi_port = None

        for name, lat, lng, start_h, end_h, berths, tide, night in port_data:
            if not Port.objects.filter(name=name).exists():
                try:
                    port = Port.objects.create(
                        name=name,
                        lat=lat,
                        lng=lng,
                        operating_hours_start=start_h,
                        operating_hours_end=end_h,
                        berths=berths,
                        tide_sensitive=tide,
                        night_ops_allowed=night
                    )
                    deployed += 1

                    if name == "Suva":
                        suva_port = port
                    elif name == "Natovi":
                        natovi_port = port

                    if self.debug:
                        self.stdout.write(f"🏛️ Created {name} ({berths} berths)")
                except Exception as e:
                    logger.error(f"Failed to create port {name}: {e}")

        # Assign home ports to ferries after creation
        try:
            if suva_port:
                Ferry.objects.filter(operator__in=["Goundar Shipping", "Awesome Adventures Fiji"]).update(
                    home_port=suva_port
                )
                Ferry.objects.filter(name="Northern Ranger").update(home_port=suva_port)

            if natovi_port:
                Ferry.objects.filter(operator="Patterson Brothers Shipping").update(
                    home_port=natovi_port
                )
        except Exception as e:
            logger.warning(f"Could not assign home ports: {e}")

        self.stdout.write(self.style.SUCCESS(f"🏛️ Deployed {deployed} realistic ports"))

    def generate_realistic_routes(self, port_dict: Dict[str, Port], bidirectional: bool) -> List[Route]:
        """Generate routes based on realistic configurations."""
        configs = self.realistic_route_configs()
        created_routes = []

        for config in sorted(configs, key=lambda x: x.get('priority', 5), reverse=True):
            if config['dep'] not in port_dict or config['dest'] not in port_dict:
                if self.debug:
                    self.stdout.write(self.style.WARNING(
                        f"Skipping {config['dep']}→{config['dest']}: ports missing"
                    ))
                continue

            dep_port = port_dict[config['dep']]
            dest_port = port_dict[config['dest']]

            # Create forward route
            forward_route = self.create_realistic_route(dep_port, dest_port, config, False)
            if forward_route:
                created_routes.append(forward_route)

            # Create return route (high probability for bidirectional service)
            if bidirectional and random.random() < 0.9:
                return_route = self.create_realistic_route(dest_port, dep_port, config, True)
                if return_route:
                    created_routes.append(return_route)

        self.stdout.write(self.style.SUCCESS(f"🛤️ Generated {len(created_routes)} realistic routes"))
        return created_routes

    def validate_generated_data(self):
        """Basic validation of generated test data."""
        issues = []

        # Check for implausibly short distances (ferries don't do <10km)
        for route in Route.objects.all():
            if float(route.distance_km) < 10:
                issues.append(f"Implausibly short route: {route} ({route.distance_km}km)")

        # Check schedule feasibility
        for schedule in Schedule.objects.filter(created_by_auto=True):
            try:
                est_hours = (float(schedule.route.distance_km) /
                             (schedule.ferry.cruise_speed_knots * 1.852))
                if est_hours > schedule.ferry.max_daily_hours * 2:  # Very generous for testing
                    issues.append(f"Potentially unfeasible: {schedule.ferry.name} on {schedule.route} "
                                  f"({est_hours:.1f}h vs {schedule.ferry.max_daily_hours}h limit)")
            except Exception:
                pass  # Skip complex validations for test data

        if issues:
            self.stdout.write(self.style.ERROR("⚠️  VALIDATION WARNINGS:"))
            for issue in issues:
                self.stdout.write(f"  • {issue}")
        else:
            self.stdout.write(self.style.SUCCESS("✅ Data validation passed"))

        return len(issues) == 0

    def generate_analytics(self):
        """Generate basic operational analytics for test data."""
        analytics = {
            "generation_timestamp": timezone.now().isoformat(),
            "test_data_stats": {
                "ports": Port.objects.count(),
                "active_ferries": Ferry.objects.filter(is_active=True).count(),
                "routes": Route.objects.count(),
                "total_schedules": Schedule.objects.count(),
                "scheduled_services": Schedule.objects.filter(status='scheduled').count()
            },
            "route_summary": {},
            "port_utilization": {}
        }

        # Route analytics
        for route in Route.objects.all():
            schedules = Schedule.objects.filter(route=route, status='scheduled').count()
            analytics["route_summary"][f"{route.departure_port.name}_{route.destination_port.name}"] = {
                "distance_km": float(route.distance_km),
                "base_fare_fjd": float(route.base_fare),
                "service_tier": route.service_tier,
                "min_weekly_services": route.min_weekly_services,
                "schedules_created": schedules,
                "operator_preference": getattr(route, 'notes', 'N/A')
            }

        # Port utilization
        for port in Port.objects.all():
            departures = Schedule.objects.filter(
                route__departure_port=port, status='scheduled'
            ).count()
            arrivals = Schedule.objects.filter(
                route__destination_port=port, status='scheduled'
            ).count()
            analytics["port_utilization"][port.name] = {
                "berths": port.berths,
                "departures": departures,
                "arrivals": arrivals,
                "total_movements": departures + arrivals,
                "utilization_rate": min(1.0, (departures + arrivals) / (port.berths * 10))
            }

        timestamp = timezone.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ferry_test_analytics_{timestamp}.json"
        try:
            with open(filename, 'w') as f:
                json.dump(analytics, f, indent=2, default=str)
            self.stdout.write(self.style.SUCCESS(f"📊 Test analytics exported: {filename}"))
        except Exception as e:
            logger.warning(f"Analytics export failed: {e}")

    def handle(self, *args, **options):
        """Main orchestration method for test data generation."""
        # Set instance attributes from options
        self.reset = options.get('reset', False)
        self.reset_schedules = options.get('reset_schedules', False)
        self.days_ahead = options.get('days-ahead', 30)
        self.relaxed = options.get('relaxed', False)
        self.debug = options.get('debug', False)
        self.bidirectional = options.get('bidirectional', True)
        self.realistic_fares = options.get('realistic-fares', True)
        self.analytics = options.get('analytics', False)
        self.validate = options.get('validate', False)

        self.stdout.write(self.style.WARNING(
            "⚠️  DEVELOPMENT MODE: Generating TEST DATA only - NOT for production!"
        ))
        self.stdout.write(self.style.WARNING(
            "💡 For production, integrate with real operator APIs (Goundar, Patterson, etc.)"
        ))

        try:
            with transaction.atomic():
                # Phase 1: Reset if requested
                if self.reset:
                    self.stdout.write("🔄 Full test data reset...")
                    models_to_clear = [Schedule, Route, Ferry, Port]
                    for model in models_to_clear:
                        count = model.objects.count()
                        if count > 0:
                            model.objects.all().delete()
                            self.stdout.write(f"🗑️  Cleared {count} {model.__name__} records")

                if self.reset_schedules and not self.reset:
                    deleted_count = Schedule.objects.filter(created_by_auto=True).delete()[0]
                    if deleted_count > 0:
                        self.stdout.write(self.style.SUCCESS(
                            f"🗑️ Reset {deleted_count} auto-generated schedules"
                        ))

                # Phase 2: Deploy infrastructure
                self.deploy_realistic_fleet()
                self.deploy_realistic_ports()

                # Phase 3: Generate routes
                port_dict = {p.name: p for p in Port.objects.all()}
                routes = self.generate_realistic_routes(port_dict, self.bidirectional)

                if not routes:
                    self.stdout.write(self.style.ERROR("❌ No routes generated - check port data"))
                    return

                # Phase 4: Generate schedules
                self.stdout.write(f"\n📅 Generating {self.days_ahead}-day test schedule horizon...")
                total_schedules = 0
                start_date = timezone.now().date()

                for route in routes:
                    self.stdout.write(f"🛳️  Processing route: {route}")

                    created_for_route = 0

                    # Create regular schedules based on frequency
                    for day_offset in range(self.days_ahead):
                        op_day = start_date + timedelta(days=day_offset)

                        # Skip if already scheduled
                        if Schedule.objects.filter(
                                route=route,
                                operational_day=op_day,
                                status='scheduled'
                        ).exists():
                            continue

                        # For irregular routes (monthly), only schedule occasionally
                        if route.min_weekly_services < 1 and day_offset % 28 != 0:
                            continue

                        schedule = self.create_realistic_schedule(route, op_day, self.relaxed)
                        if schedule:
                            created_for_route += 1
                            total_schedules += 1

                    # Ensure minimum service levels
                    min_created = self.ensure_minimum_services(route, self.days_ahead)
                    created_for_route += min_created
                    total_schedules += min_created

                    self.stdout.write(f"  📊 Created {created_for_route} schedules for route")

                # Phase 5: Validation and analytics
                if self.validate:
                    self.validate_generated_data()

                if self.analytics:
                    self.generate_analytics()

                # Final summary
                final_stats = {
                    'total_schedules': total_schedules,
                    'routes': len(routes),
                    'ferries': Ferry.objects.filter(is_active=True).count(),
                    'ports': Port.objects.count()
                }

                self.stdout.write(self.style.SUCCESS(f"""
✅ TEST DATA GENERATION COMPLETE!

📈 {final_stats['total_schedules']} test schedules created
🗺️  {final_stats['routes']} realistic routes
🚢 {final_stats['ferries']} active vessels  
🏛️  {final_stats['ports']} ports configured
📅 {self.days_ahead}-day test horizon established

⚠️  IMPORTANT REMINDERS:
• This is TEST DATA for development only
• Frequencies/fares are approximate estimates
• No real-time weather, maintenance, or cancellations
• Production requires operator API integration
• Run with --validate to check data quality

🎯 Ready for application testing!
                """))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Test data generation failed: {str(e)}"))
            logger.error("Test data generation failed", exc_info=True)
            raise

    def close(self, *args, **kwargs):
        """Ensure proper cleanup."""
        super().close(*args, **kwargs)



# # Full test data generation
# python manage.py populate_data --reset --validate
#
# # Generate with analytics
# python manage.py populate_data --reset --analytics --days-ahead=60
#
# # Reset schedules only (keep routes/ports)
# python manage.py populate_data --reset-schedules
#
# # Debug mode with validation
# python manage.py populate_data --debug --validate --days-ahead=14