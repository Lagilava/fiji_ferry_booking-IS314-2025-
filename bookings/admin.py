import uuid
import qrcode
from decimal import Decimal
from io import BytesIO
from django.core.files.base import ContentFile
from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html, escape
from django.db import models
from django.http import HttpResponse
import math
import csv
import requests
from django.conf import settings
from datetime import timedelta, time, datetime
from django.utils.safestring import mark_safe
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
import json

from qrcode.main import QRCode
from .models import (
    Ferry, Route, Schedule, Booking, Passenger, Payment, Ticket,
    Cargo, DocumentVerification, WeatherCondition, Port, MaintenanceLog, ServicePattern
)

# Predefined Fiji ports with realistic coordinates
FIJI_PORTS = [
    {'name': 'Suva', 'lat': -18.1248, 'lng': 178.4501},
    {'name': 'Natovi', 'lat': -17.6509, 'lng': 178.5874},
    {'name': 'Savusavu', 'lat': -16.7760, 'lng': 179.3390},
    {'name': 'Lautoka', 'lat': -17.6167, 'lng': 177.4500},
    {'name': 'Nadi', 'lat': -17.7765, 'lng': 177.4356},
    {'name': 'Yasawa Islands', 'lat': -16.9000, 'lng': 177.5000},
    {'name': 'Mamanuca Islands', 'lat': -17.6500, 'lng': 177.1000},
    {'name': 'Port Denarau', 'lat': -17.7700, 'lng': 177.4400},
    {'name': 'Nacula Island', 'lat': -16.8000, 'lng': 177.4200},
    {'name': 'Levuka', 'lat': -18.0667, 'lng': 179.3167},
]

# Known route durations based on real-world ferry data
KNOWN_DURATIONS = {
    ('Suva', 'Natovi'): timedelta(hours=2),
    ('Natovi', 'Suva'): timedelta(hours=2),
    ('Suva', 'Levuka'): timedelta(hours=2, minutes=30),
    ('Levuka', 'Suva'): timedelta(hours=2, minutes=30),
    ('Lautoka', 'Yasawa Islands'): timedelta(hours=4),
    ('Yasawa Islands', 'Lautoka'): timedelta(hours=4),
    ('Port Denarau', 'Mamanuca Islands'): timedelta(hours=1),
    ('Mamanuca Islands', 'Port Denarau'): timedelta(hours=1),
    ('Port Denarau', 'Nacula Island'): timedelta(hours=4, minutes=30),
    ('Nacula Island', 'Port Denarau'): timedelta(hours=4, minutes=30),
}

# Maintenance interval (days)
MAINTENANCE_INTERVAL = 14

# Utility function for Haversine distance
def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371  # Earth's radius in km
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

# Shared CSV export utility
def export_as_csv(modeladmin, request, queryset, fields, field_getters, filename):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(fields)
    for obj in queryset:
        writer.writerow([getter(obj) for getter in field_getters])
    return response

# ------------------- Port ------------------- #
@admin.register(Port)
class PortAdmin(admin.ModelAdmin):
    list_display = ('name', 'lat', 'lng', 'operating_hours', 'berths', 'tide_sensitive', 'night_ops_allowed', 'active_routes_count')
    search_fields = ('name',)
    list_filter = ('tide_sensitive', 'night_ops_allowed', 'name')
    actions = ['import_fiji_ports', 'create_all_routes']

    def operating_hours(self, obj):
        return f"{obj.operating_hours_start.strftime('%H:%M')}–{obj.operating_hours_end.strftime('%H:%M')}"
    operating_hours.short_description = 'Operating Hours'

    def active_routes_count(self, obj):
        return obj.departures.count() + obj.arrivals.count()
    active_routes_count.short_description = 'Active Routes'

    def import_fiji_ports(self, request, queryset=None):
        created_count = updated_count = 0
        for port_data in FIJI_PORTS:
            try:
                port, created = Port.objects.update_or_create(
                    name=port_data['name'],
                    defaults={
                        'lat': port_data['lat'],
                        'lng': port_data['lng'],
                        'operating_hours_start': time(6, 0),
                        'operating_hours_end': time(20, 0),
                        'berths': 2,
                        'tide_sensitive': port_data['name'] in ['Yasawa Islands', 'Mamanuca Islands', 'Nacula Island'],
                        'night_ops_allowed': port_data['name'] in ['Suva', 'Lautoka', 'Port Denarau']
                    }
                )
                if created:
                    created_count += 1
                else:
                    updated_count += 1
            except Exception as e:
                self.message_user(request, f"Error importing {port_data['name']}: {str(e)}", level=messages.ERROR)
        self.message_user(request, f"Created {created_count} and updated {updated_count} ports.", level=messages.SUCCESS)
    import_fiji_ports.short_description = "Import Fiji ports"

    def create_all_routes(self, request, queryset=None):
        ports = Port.objects.all()
        if not ports:
            self.message_user(request, "No ports available. Import ports first.", level=messages.ERROR)
            return

        created_count = skipped_count = 0
        routes_to_create = []

        for departure in ports:
            for destination in ports:
                if departure == destination:
                    continue
                if Route.objects.filter(
                    departure_port=departure,
                    destination_port=destination
                ).exists():
                    skipped_count += 1
                    continue

                distance_km = haversine_distance(
                    departure.lat, departure.lng,
                    destination.lat, destination.lng
                )
                duration_key = (departure.name, destination.name)
                duration = KNOWN_DURATIONS.get(duration_key, timedelta(hours=max(1, distance_km / 25.0)))
                base_fare = round(float(distance_km) * 2.0, 2)
                service_tier = 'major' if duration <= timedelta(hours=2, minutes=30) else 'regional' if duration <= timedelta(hours=4) else 'remote'
                min_weekly_services = 14 if service_tier == 'major' else 7 if service_tier == 'regional' else 3
                preferred_windows = ["06:00-08:00", "12:00-14:00"] if service_tier == 'major' else ["08:00-10:00"] if service_tier == 'regional' else ["09:00-11:00"]

                routes_to_create.append(
                    Route(
                        departure_port=departure,
                        destination_port=destination,
                        distance_km=distance_km,
                        estimated_duration=duration,
                        base_fare=base_fare,
                        service_tier=service_tier,
                        min_weekly_services=min_weekly_services,
                        preferred_departure_windows=preferred_windows,
                        safety_buffer_minutes=30 if departure.tide_sensitive or destination.tide_sensitive else 15
                    )
                )

        Route.objects.bulk_create(routes_to_create, ignore_conflicts=True)
        created_count = len(routes_to_create)
        self.message_user(
            request,
            f"Created {created_count} routes. Skipped {skipped_count} existing routes.",
            level=messages.SUCCESS
        )
    create_all_routes.short_description = "Create all port routes"

# ------------------- WeatherCondition ------------------- #
@admin.register(WeatherCondition)
class WeatherConditionAdmin(admin.ModelAdmin):
    list_display = ('route', 'port', 'temperature', 'wind_speed', 'condition', 'updated_at', 'is_expired_display')
    list_filter = ('port__name', 'condition', 'expires_at')
    search_fields = ('port__name', 'route__departure_port__name', 'route__destination_port__name')
    actions = ['force_refresh_weather_data', 'clear_expired_weather']
    autocomplete_fields = ['port', 'route']
    readonly_fields = ('updated_at', 'expires_at')

    def is_expired_display(self, obj):
        return obj.is_expired()
    is_expired_display.short_description = 'Expired'
    is_expired_display.boolean = True

    def force_refresh_weather_data(self, request, queryset):
        updated_count = 0
        for weather in queryset:
            try:
                url = f"https://api.weatherapi.com/v1/current.json?key={settings.WEATHER_API_KEY}&q={weather.port.lat},{weather.port.lng}"
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                data = response.json()
                weather.temperature = data['current']['temp_c']
                weather.wind_speed = data['current']['wind_kph']
                weather.condition = data['current']['condition']['text']
                weather.precipitation_probability = data['current'].get('precip_mm', 0) * 100
                weather.expires_at = timezone.now() + timedelta(minutes=30)
                weather.save()
                updated_count += 1
            except requests.RequestException as e:
                self.message_user(request, f"Error updating weather for {weather.port.name}: {str(e)}", level=messages.WARNING)
        self.message_user(request, f"Force refreshed weather for {updated_count} records.", level=messages.SUCCESS)
    force_refresh_weather_data.short_description = "Force refresh weather data"

    def clear_expired_weather(self, request, queryset):
        expired_count = WeatherCondition.objects.filter(expires_at__lt=timezone.now()).delete()[0]
        self.message_user(request, f"Cleared {expired_count} expired weather records.", level=messages.SUCCESS)
    clear_expired_weather.short_description = "Clear expired weather"

# ------------------- Ferry ------------------- #
@admin.register(Ferry)
class FerryAdmin(admin.ModelAdmin):
    list_display = ('name', 'operator', 'capacity', 'home_port', 'cruise_speed_knots', 'is_active', 'last_maintenance', 'next_maintenance')
    list_filter = ('is_active', 'operator', 'home_port')
    search_fields = ('name', 'operator')
    actions = ['activate_ferries', 'deactivate_ferries', 'export_ferry_details', 'schedule_maintenance']
    readonly_fields = ('last_maintenance', 'next_maintenance')
    autocomplete_fields = ['home_port']

    def last_maintenance(self, obj):
        latest = obj.maintenance_logs.order_by('-maintenance_date').first()
        return latest.maintenance_date if latest else 'N/A'
    last_maintenance.short_description = 'Last Maintenance'

    def next_maintenance(self, obj):
        latest = obj.maintenance_logs.order_by('-maintenance_date').first()
        custom_interval = latest.maintenance_interval_days if latest and latest.maintenance_interval_days else MAINTENANCE_INTERVAL
        if latest:
            return latest.maintenance_date + timedelta(days=custom_interval)
        return 'N/A'
    next_maintenance.short_description = 'Next Maintenance'

    def activate_ferries(self, request, queryset):
        updated_count = queryset.update(is_active=True)
        self.message_user(request, f"Activated {updated_count} ferries.", level=messages.SUCCESS)
    activate_ferries.short_description = "Activate ferries"

    def deactivate_ferries(self, request, queryset):
        updated_count = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {updated_count} ferries.", level=messages.SUCCESS)
    deactivate_ferries.short_description = "Deactivate ferries"

    def schedule_maintenance(self, request, queryset):
        maintenance_logs = []
        for ferry in queryset:
            custom_interval = ferry.maintenance_logs.order_by('-maintenance_date').first()
            custom_interval = custom_interval.maintenance_interval_days if custom_interval else MAINTENANCE_INTERVAL
            maintenance_logs.append(
                MaintenanceLog(
                    ferry=ferry,
                    maintenance_date=timezone.now().date(),
                    notes="Scheduled maintenance via admin",
                    maintenance_interval_days=custom_interval
                )
            )
            ferry.is_active = False
        MaintenanceLog.objects.bulk_create(maintenance_logs)
        queryset.update(is_active=False)
        self.message_user(request, f"Scheduled maintenance for {queryset.count()} ferries.", level=messages.SUCCESS)
    schedule_maintenance.short_description = "Schedule maintenance"

    def export_ferry_details(self, request, queryset):
        return export_as_csv(
            self, request, queryset,
            ['Name', 'Operator', 'Capacity', 'Home Port', 'Cruise Speed (knots)', 'Active', 'Last Maintenance'],
            lambda f: [f.name, f.operator, f.capacity, f.home_port.name if f.home_port else 'N/A', f.cruise_speed_knots, f.is_active, self.last_maintenance(f)],
            'ferry_details.csv'
        )
    export_ferry_details.short_description = "Export ferry details"

# ------------------- Schedule Inline ------------------- #
class ScheduleInline(admin.TabularInline):
    model = Schedule
    fields = ('ferry', 'departure_time', 'arrival_time', 'available_seats', 'status', 'operational_day')
    readonly_fields = ('ferry', 'available_seats')
    extra = 0
    max_num = 10
    can_delete = False

# ------------------- Route ------------------- #
@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('departure_port', 'destination_port', 'distance_km', 'estimated_duration', 'base_fare', 'service_tier', 'min_weekly_services', 'active_schedules')
    list_filter = ('service_tier', 'departure_port', 'destination_port')
    search_fields = ('departure_port__name', 'destination_port__name')
    list_editable = ('estimated_duration', 'base_fare', 'min_weekly_services', 'service_tier')
    autocomplete_fields = ['departure_port', 'destination_port']
    actions = ['recalculate_distances', 'update_fares']
    inlines = [ScheduleInline]

    def active_schedules(self, obj):
        return obj.schedules.filter(status='scheduled').count()
    active_schedules.short_description = 'Active Schedules'

    def recalculate_distances(self, request, queryset):
        updated_count = 0
        for route in queryset:
            route.distance_km = haversine_distance(
                route.departure_port.lat, route.departure_port.lng,
                route.destination_port.lat, route.destination_port.lng
            )
            route.base_fare = round(float(route.distance_km) * 2.0, 2)
            route.save()
            updated_count += 1
        self.message_user(request, f"Updated distances and fares for {updated_count} routes.", level=messages.SUCCESS)
    recalculate_distances.short_description = "Recalculate distances and fares"

    def update_fares(self, request, queryset):
        updated_count = 0
        for route in queryset:
            route.base_fare = round(float(route.distance_km) * 2.0, 2)
            route.save()
            updated_count += 1
        self.message_user(request, f"Updated fares for {updated_count} routes.", level=messages.SUCCESS)
    update_fares.short_description = "Update fares based on distance"

# ------------------- Schedule ------------------- #
@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('ferry', 'route', 'departure_time', 'arrival_time', 'available_seats', 'status', 'is_maintenance_day', 'created_by_auto')
    list_filter = ('status', 'ferry', 'route__departure_port', 'route__destination_port', 'operational_day')
    search_fields = ('ferry__name', 'route__departure_port__name', 'route__destination_port__name')
    actions = ['cancel_schedules', 'reset_seats', 'export_schedules', 'create_schedules_for_routes', 'mark_as_delayed', 'validate_schedules']
    autocomplete_fields = ['ferry', 'route']
    list_per_page = 50

    def is_maintenance_day(self, obj):
        return MaintenanceLog.objects.filter(
            ferry=obj.ferry,
            maintenance_date=obj.operational_day
        ).exists()
    is_maintenance_day.short_description = 'Maintenance Day'
    is_maintenance_day.boolean = True

    def cancel_schedules(self, request, queryset):
        updated_count = queryset.update(status='cancelled')
        self.message_user(request, f"Cancelled {updated_count} schedules.", level=messages.SUCCESS)
    cancel_schedules.short_description = "Cancel schedules"

    def reset_seats(self, request, queryset):
        updated_count = 0
        for schedule in queryset:
            schedule.available_seats = schedule.ferry.capacity
            schedule.save()
            updated_count += 1
        self.message_user(request, f"Reset seats for {updated_count} schedules.", level=messages.SUCCESS)
    reset_seats.short_description = "Reset seats to ferry capacity"

    def mark_as_delayed(self, request, queryset):
        updated_count = queryset.update(status='delayed')
        self.message_user(request, f"Marked {updated_count} schedules as delayed.", level=messages.SUCCESS)
    mark_as_delayed.short_description = "Mark schedules as delayed"

    def export_schedules(self, request, queryset):
        return export_as_csv(
            self, request, queryset,
            ['Ferry', 'Route', 'Departure', 'Arrival', 'Seats', 'Status', 'Operational Day'],
            lambda s: [s.ferry.name, str(s.route), s.departure_time, s.arrival_time, s.available_seats, s.status, s.operational_day],
            'schedules.csv'
        )
    export_schedules.short_description = "Export schedules"

    def validate_schedules(self, request, queryset):
        errors = {'clashes': 0, 'curfew_violations': 0, 'berth_conflicts': 0, 'ferry_overuse': 0}
        for schedule in queryset:
            # Clash check
            if Schedule.objects.filter(
                ferry=schedule.ferry,
                departure_time__range=(
                    schedule.departure_time - timedelta(minutes=30),
                    schedule.arrival_time + timedelta(minutes=30)
                )
            ).exclude(id=schedule.id).exists():
                errors['clashes'] += 1
                continue

            # Curfew check
            dep_time = schedule.departure_time.time()
            arr_time = schedule.arrival_time.time()
            dep_port = schedule.route.departure_port
            arr_port = schedule.route.destination_port
            if not (
                (dep_port.night_ops_allowed or (dep_port.operating_hours_start <= dep_time <= dep_port.operating_hours_end)) and
                (arr_port.night_ops_allowed or (arr_port.operating_hours_start <= arr_time <= arr_port.operating_hours_end))
            ):
                errors['curfew_violations'] += 1
                continue

            # Berth check
            for port, time in [(dep_port, schedule.departure_time), (arr_port, schedule.arrival_time)]:
                time_start = time - timedelta(minutes=5)
                time_end = time + timedelta(minutes=5)
                if Schedule.objects.filter(
                    Q(route__departure_port=port, departure_time__range=(time_start, time_end)) |
                    Q(route__destination_port=port, arrival_time__range=(time_start, time_end))
                ).exclude(id=schedule.id).count() >= port.berths:
                    errors['berth_conflicts'] += 1
                    break

            # Ferry overuse check
            day_schedules = Schedule.objects.filter(
                ferry=schedule.ferry,
                operational_day=schedule.operational_day
            ).exclude(id=schedule.id)
            total_hours = sum(
                (s.arrival_time - s.departure_time).total_seconds() / 3600
                for s in day_schedules
            ) + (schedule.arrival_time - schedule.departure_time).total_seconds() / 3600
            if total_hours > schedule.ferry.max_daily_hours:
                errors['ferry_overuse'] += 1

        error_summary = "<br>".join([f"{key.replace('_', ' ').title()}: {value}" for key, value in errors.items()])
        self.message_user(
            request,
            mark_safe(f"Validation complete. Issues found:<br>{error_summary}"),
            level=messages.WARNING if any(errors.values()) else messages.SUCCESS
        )
    validate_schedules.short_description = "Validate schedules"

    def create_schedules_for_routes(self, request, queryset=None):
        import logging
        logger = logging.getLogger(__name__)

        # Ensure we always work with Route objects
        if queryset is None:
            routes = Route.objects.all()
        else:
            first_obj = queryset.first()
            if isinstance(first_obj, Schedule):
                routes = Route.objects.filter(id__in=queryset.values_list('route_id', flat=True))
            else:
                routes = queryset

        ferries = Ferry.objects.filter(is_active=True)
        if not routes:
            self.message_user(request, "No routes available.", level=messages.ERROR)
            return
        if not ferries:
            self.message_user(request, "No active ferries available.", level=messages.ERROR)
            return

        created_count = 0
        skipped_count = {
            'maintenance': 0, 'turnaround': 0, 'curfew': 0, 'berth': 0,
            'quota': 0, 'duplicate': 0, 'spacing': 0, 'ferry_overuse': 0
        }
        schedules_to_create = []

        # Pre-fetch existing schedules and maintenance logs
        start_date = (timezone.now() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=7)
        existing_schedules = set(
            Schedule.objects.filter(
                departure_time__range=(start_date, end_date)
            ).values_list('ferry_id', 'route_id', 'departure_time')
        )
        maintenance_dates = {
            log.ferry_id: log.maintenance_date
            for log in MaintenanceLog.objects.filter(
                maintenance_date__range=(start_date.date(), end_date.date())
            )
        }

        # Pre-compute port occupancy
        port_occupancy = {}
        for port in Port.objects.all():
            port_schedules = Schedule.objects.filter(
                Q(route__departure_port=port) | Q(route__destination_port=port),
                departure_time__range=(start_date, end_date)
            )
            occupancy = {}
            for schedule in port_schedules:
                for time in [schedule.departure_time, schedule.arrival_time]:
                    minute_bucket = time.replace(second=0, microsecond=0)
                    occupancy[minute_bucket] = occupancy.get(minute_bucket, 0) + 1
            port_occupancy[port.id] = occupancy

        ferry_last_arrival = {ferry.id: start_date - timedelta(minutes=ferry.turnaround_minutes) for ferry in ferries}
        ferry_daily_hours = {ferry.id: {start_date.date() + timedelta(days=d): 0 for d in range(7)} for ferry in
                             ferries}
        route_weekly_counts = {route.id: 0 for route in routes}

        for route in routes:
            duration_hours = float(route.distance_km / Decimal('25.0'))
            duration = KNOWN_DURATIONS.get(
                (route.departure_port.name, route.destination_port.name),
                timedelta(hours=max(1, duration_hours))
            ) + timedelta(minutes=route.safety_buffer_minutes)

            windows = route.preferred_departure_windows
            target_days = list(range(7)) if route.service_tier == 'major' else [0, 2, 4,
                                                                                6] if route.service_tier == 'regional' else [
                0, 3, 6]

            for day_offset in target_days:
                if route_weekly_counts[route.id] >= route.min_weekly_services:
                    skipped_count['quota'] += 1
                    continue
                schedule_date = start_date + timedelta(days=day_offset)
                service_windows = ServicePattern.objects.filter(route=route, weekday=schedule_date.weekday())
                if service_windows.exists():
                    windows = [sp.window for sp in service_windows]

                for window in windows:
                    start_hour, end_hour = map(lambda x: int(x.split(':')[0]), window.split('-'))
                    for hour in range(start_hour, end_hour + 1):
                        dep_time = schedule_date.replace(hour=hour, minute=0)

                        # Curfew check
                        if not (route.departure_port.night_ops_allowed or
                                route.departure_port.operating_hours_start <= dep_time.time() <= route.departure_port.operating_hours_end):
                            skipped_count['curfew'] += 1
                            logger.debug(f"{route}: Dep_time {dep_time} blocked by departure curfew")
                            continue

                        arr_time = dep_time + duration
                        if not (route.destination_port.night_ops_allowed or
                                route.destination_port.operating_hours_start <= arr_time.time() <= route.destination_port.operating_hours_end):
                            skipped_count['curfew'] += 1
                            logger.debug(f"{route}: Dep_time {dep_time} blocked by destination curfew")
                            continue

                        # Rotate ferries with fallback to all active ferries
                        candidate_ferries = sorted(
                            [f for f in ferries if
                             f.home_port_id == route.departure_port_id or not f.home_port] or list(ferries),
                            key=lambda f: haversine_distance(
                                f.home_port.lat if f.home_port else route.departure_port.lat,
                                f.home_port.lng if f.home_port else route.departure_port.lng,
                                route.departure_port.lat, route.departure_port.lng
                            )
                        )
                        if not candidate_ferries:
                            logger.debug(f"{route}: No candidate ferries available")
                            continue

                        assigned = False
                        for ferry in candidate_ferries:
                            if maintenance_dates.get(ferry.id) == dep_time.date():
                                skipped_count['maintenance'] += 1
                                continue
                            if dep_time < ferry_last_arrival[ferry.id] + timedelta(minutes=ferry.turnaround_minutes):
                                skipped_count['turnaround'] += 1
                                continue
                            if (ferry.id, route.id, dep_time) in existing_schedules:
                                skipped_count['duplicate'] += 1
                                continue
                            trip_hours = duration.total_seconds() / 3600
                            if ferry_daily_hours[ferry.id][dep_time.date()] + trip_hours > ferry.max_daily_hours:
                                skipped_count['ferry_overuse'] += 1
                                continue

                            # Berth check
                            berth_ok = True
                            for port, time in [(route.departure_port, dep_time), (route.destination_port, arr_time)]:
                                minute_bucket = time.replace(second=0, microsecond=0)
                                current_occupancy = port_occupancy.get(port.id, {}).get(minute_bucket, 0)
                                if current_occupancy >= port.berths:
                                    skipped_count['berth'] += 1
                                    berth_ok = False
                                    logger.debug(f"{route}: Dep_time {dep_time} blocked by berth at {port}")
                                    break
                            if not berth_ok:
                                continue

                            # Spacing check
                            same_route_schedules = Schedule.objects.filter(
                                route=route,
                                operational_day=dep_time.date(),
                                departure_time__range=(dep_time - timedelta(hours=3), dep_time + timedelta(hours=3))
                            )
                            if same_route_schedules.exists():
                                skipped_count['spacing'] += 1
                                logger.debug(f"{route}: Dep_time {dep_time} blocked by spacing check")
                                continue

                            # Weather check
                            status = 'scheduled'
                            weather = WeatherCondition.objects.filter(route=route,
                                                                      expires_at__gt=timezone.now()).order_by(
                                '-updated_at').first()
                            if weather and weather.wind_speed > 30:
                                status = 'delayed'

                            schedules_to_create.append(
                                Schedule(
                                    ferry=ferry,
                                    route=route,
                                    departure_time=dep_time,
                                    arrival_time=arr_time,
                                    available_seats=ferry.capacity,
                                    status=status,
                                    operational_day=dep_time.date(),
                                    created_by_auto=True
                                )
                            )
                            ferry_last_arrival[ferry.id] = arr_time
                            ferry_daily_hours[ferry.id][dep_time.date()] += trip_hours
                            route_weekly_counts[route.id] += 1
                            port_occupancy.setdefault(route.departure_port.id, {})[
                                dep_time.replace(second=0, microsecond=0)] = port_occupancy.get(route.departure_port.id,
                                                                                                {}).get(
                                dep_time.replace(second=0, microsecond=0), 0) + 1
                            port_occupancy.setdefault(route.destination_port.id, {})[
                                arr_time.replace(second=0, microsecond=0)] = port_occupancy.get(
                                route.destination_port.id, {}).get(arr_time.replace(second=0, microsecond=0), 0) + 1
                            created_count += 1
                            assigned = True
                            break  # Move to next window after assigning a ferry

                        if not assigned:
                            logger.debug(f"{route}: No ferry could be assigned for dep_time {dep_time}")

        Schedule.objects.bulk_create(schedules_to_create, batch_size=500)

        weekly_coverage = []
        for route in routes:
            achieved = Schedule.objects.filter(route=route,
                                               operational_day__range=(start_date.date(), end_date.date())).count()
            weekly_coverage.append(f"{route}: {achieved}/{route.min_weekly_services}")

        summary = (
            f"Created {created_count} schedules.<br>"
            f"Skipped: {sum(skipped_count.values())} ("
            f"Maintenance: {skipped_count['maintenance']}, "
            f"Turnaround: {skipped_count['turnaround']}, "
            f"Curfew: {skipped_count['curfew']}, "
            f"Berth: {skipped_count['berth']}, "
            f"Quota: {skipped_count['quota']}, "
            f"Duplicate: {skipped_count['duplicate']}, "
            f"Spacing: {skipped_count['spacing']}, "
            f"Ferry Overuse: {skipped_count['ferry_overuse']})<br>"
            f"Weekly Coverage:<br>{'<br>'.join(weekly_coverage)}"
        )
        self.message_user(request, mark_safe(summary), level=messages.SUCCESS)

    create_schedules_for_routes.short_description = "Create schedules for routes"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'ferry', 'route', 'route__departure_port', 'route__destination_port'
        ).order_by('-departure_time')


# ------------------- Booking ------------------- #
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user_email', 'schedule', 'booking_date', 'total_passengers',
        'total_price', 'status', 'is_unaccompanied_minor', 'is_group_booking', 'is_emergency'
    )
    list_filter = (
        'status', 'is_unaccompanied_minor', 'is_group_booking', 'is_emergency',
        ('booking_date', admin.DateFieldListFilter),
        ('schedule__departure_time', admin.DateFieldListFilter)
    )
    search_fields = ('user__email', 'guest_email', 'schedule__ferry__name', 'id')
    actions = ['generate_manifest', 'approve_emergency_booking', 'cancel_bookings', 'send_booking_confirmation']
    readonly_fields = ('booking_date', 'stripe_session_id', 'payment_intent_id')
    autocomplete_fields = ['schedule', 'user', 'group_leader']
    list_per_page = 50

    def user_email(self, obj):
        return obj.user.email if obj.user else obj.guest_email or 'N/A'
    user_email.short_description = 'Email'

    def total_passengers(self, obj):
        return obj.passengers.count()
    total_passengers.short_description = 'Passengers'

    def generate_manifest(self, request, queryset):
        for booking in queryset:
            passengers = booking.passengers.all()
            manifest = ", ".join([f"{p.first_name} {p.last_name} ({p.passenger_type})" for p in passengers])
            self.message_user(request, f"Booking {booking.id} manifest: {manifest}", level=messages.INFO)
    generate_manifest.short_description = "Generate passenger manifest"

    def approve_emergency_booking(self, request, queryset):
        updated_count = 0
        verifications = []
        passengers_to_update = []
        for booking in queryset.filter(status='pending'):
            if not booking.passengers.exists():
                self.message_user(request, f"Booking {booking.id} has no passengers.", level=messages.WARNING)
                continue
            booking.status = 'emergency'
            booking.is_emergency = True
            booking.save()
            for passenger in booking.passengers.all():
                if passenger.document and passenger.verification_status != 'verified':
                    verifications.append(
                        DocumentVerification(
                            passenger=passenger,
                            document=passenger.document,
                            verification_status='temporary',
                            verified_by=request.user,
                            verified_at=timezone.now(),
                            expires_at=booking.schedule.departure_time + timedelta(days=1)
                        )
                    )
                    passenger.verification_status = 'temporary'
                    passengers_to_update.append(passenger)
            updated_count += 1
        DocumentVerification.objects.bulk_create(verifications, batch_size=100)
        Passenger.objects.bulk_update(passengers_to_update, ['verification_status'], batch_size=100)
        self.message_user(request, f"Approved {updated_count} emergency bookings.", level=messages.SUCCESS)
    approve_emergency_booking.short_description = "Approve emergency bookings"

    def cancel_bookings(self, request, queryset):
        updated_count = 0
        for booking in queryset.exclude(status='cancelled'):
            booking.status = 'cancelled'
            booking.save()
            updated_count += 1
        self.message_user(request, f"Cancelled {updated_count} bookings.", level=messages.SUCCESS)
    cancel_bookings.short_description = "Cancel bookings"

    def send_booking_confirmation(self, request, queryset):
        from django.core.mail import send_mail
        sent_count = 0
        for booking in queryset.filter(status='confirmed'):
            email = booking.user.email if booking.user else booking.guest_email
            if not email:
                self.message_user(request, f"Booking {booking.id} has no email.", level=messages.WARNING)
                continue
            try:
                send_mail(
                    subject='Fiji Ferry Booking Confirmation',
                    message=f"Your booking {booking.id} for {booking.schedule} is confirmed.",
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[email],
                    fail_silently=False
                )
                sent_count += 1
            except Exception as e:
                self.message_user(request, f"Error sending email for Booking {booking.id}: {str(e)}", level=messages.WARNING)
        self.message_user(request, f"Sent confirmation emails for {sent_count} bookings.", level=messages.SUCCESS)
    send_booking_confirmation.short_description = "Send confirmation emails"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'schedule__ferry', 'schedule__route',
            'schedule__route__departure_port', 'schedule__route__destination_port'
        ).prefetch_related('passengers')

# ------------------- DocumentVerification Inline ------------------- #
class DocumentVerificationInline(admin.TabularInline):
    model = DocumentVerification
    fields = ('document', 'verification_status', 'verified_by', 'verified_at', 'expires_at')
    readonly_fields = ('verified_at', 'expires_at')
    extra = 0
    max_num = 5
    can_delete = True

# ------------------- Passenger ------------------- #
@admin.register(Passenger)
class PassengerAdmin(admin.ModelAdmin):
    list_display = (
        'first_name', 'last_name', 'booking', 'passenger_type', 'age',
        'document_link', 'verification_status', 'linked_adult', 'is_group_leader'
    )
    list_filter = ('passenger_type', 'verification_status', 'is_group_leader')
    search_fields = ('first_name', 'last_name', 'booking__id')
    actions = ['verify_documents', 'reject_documents', 'export_passenger_list']
    autocomplete_fields = ['booking', 'linked_adult']
    inlines = [DocumentVerificationInline]
    list_per_page = 50

    def document_link(self, obj):
        return format_html('<a href="{}" target="_blank">View</a>', escape(obj.document.url)) if obj.document else 'No Document'
    document_link.short_description = 'Document'

    def verify_documents(self, request, queryset):
        verifications = []
        passengers_to_update = []
        for passenger in queryset.filter(document__isnull=False):
            if passenger.verification_status != 'verified':
                verifications.append(
                    DocumentVerification(
                        passenger=passenger,
                        document=passenger.document,
                        verification_status='verified',
                        verified_by=request.user,
                        verified_at=timezone.now()
                    )
                )
                passenger.verification_status = 'verified'
                passengers_to_update.append(passenger)
        DocumentVerification.objects.bulk_create(verifications, batch_size=100)
        Passenger.objects.bulk_update(passengers_to_update, ['verification_status'], batch_size=100)
        self.message_user(request, f"Verified {len(passengers_to_update)} passengers.", level=messages.SUCCESS)
    verify_documents.short_description = "Verify documents"

    def reject_documents(self, request, queryset):
        verifications = []
        passengers_to_update = []
        for passenger in queryset.filter(document__isnull=False):
            if passenger.verification_status != 'rejected':
                verifications.append(
                    DocumentVerification(
                        passenger=passenger,
                        document=passenger.document,
                        verification_status='rejected',
                        verified_by=request.user,
                        verified_at=timezone.now()
                    )
                )
                passenger.verification_status = 'missing'
                passengers_to_update.append(passenger)
        DocumentVerification.objects.bulk_create(verifications, batch_size=100)
        Passenger.objects.bulk_update(passengers_to_update, ['verification_status'], batch_size=100)
        self.message_user(request, f"Rejected documents for {len(passengers_to_update)} passengers.", level=messages.SUCCESS)
    reject_documents.short_description = "Reject documents"

    def export_passenger_list(self, request, queryset):
        return export_as_csv(
            self, request, queryset,
            ['First Name', 'Last Name', 'Booking ID', 'Type', 'Age', 'Verification'],
            lambda p: [p.first_name, p.last_name, p.booking.id, p.passenger_type, p.age, p.verification_status],
            'passenger_list.csv'
        )
    export_passenger_list.short_description = "Export passenger list"

# ------------------- DocumentVerification ------------------- #
@admin.register(DocumentVerification)
class DocumentVerificationAdmin(admin.ModelAdmin):
    list_display = ('passenger', 'document_link', 'verification_status', 'verified_by', 'verified_at', 'expires_at')
    list_filter = ('verification_status', 'verified_at')
    search_fields = ('passenger__first_name', 'passenger__last_name')
    autocomplete_fields = ['passenger', 'verified_by']
    readonly_fields = ('verified_at', 'expires_at')
    list_per_page = 50

    def document_link(self, obj):
        return format_html('<a href="{}" target="_blank">View</a>', escape(obj.document.url)) if obj.document else 'No Document'
    document_link.short_description = 'Document'

# ------------------- Payment ------------------- #
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('booking', 'payment_method', 'amount', 'payment_status', 'payment_date', 'transaction_id')
    list_filter = ('payment_method', 'payment_status', 'payment_date')
    search_fields = ('booking__id', 'transaction_id', 'session_id')
    actions = ['mark_as_completed', 'issue_refunds', 'verify_payments']
    readonly_fields = ('payment_date', 'session_id', 'payment_intent_id')
    autocomplete_fields = ['booking']
    list_per_page = 50

    def verify_payments(self, request, queryset):
        from stripe.error import StripeError
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        updated_count = 0
        for payment in queryset.filter(payment_method='stripe', payment_status='pending'):
            try:
                intent = stripe.PaymentIntent.retrieve(payment.payment_intent_id)
                if intent.status == 'succeeded':
                    payment.payment_status = 'completed'
                    payment.save()
                    updated_count += 1
                elif intent.status == 'requires_payment_method':
                    payment.payment_status = 'failed'
                    payment.save()
            except StripeError as e:
                self.message_user(request, f"Error verifying payment {payment.id}: {str(e)}", level=messages.WARNING)
        self.message_user(request, f"Verified {updated_count} Stripe payments.", level=messages.SUCCESS)
    verify_payments.short_description = "Verify Stripe payments"

    def mark_as_completed(self, request, queryset):
        updated_count = queryset.filter(payment_status='pending').update(payment_status='completed')
        self.message_user(request, f"Marked {updated_count} payments as completed.", level=messages.SUCCESS)
    mark_as_completed.short_description = "Mark payments completed"

    def issue_refunds(self, request, queryset):
        from stripe.error import StripeError
        import stripe
        stripe.api_key = settings.STRIPE_SECRET_KEY
        updated_count = 0
        for payment in queryset.filter(payment_method='stripe', payment_status='completed'):
            try:
                stripe.Refund.create(payment_intent=payment.payment_intent_id)
                payment.payment_status = 'refunded'
                payment.save()
                updated_count += 1
            except StripeError as e:
                self.message_user(request, f"Error refunding payment {payment.id}: {str(e)}", level=messages.WARNING)
        self.message_user(request, f"Issued refunds for {updated_count} payments.", level=messages.SUCCESS)
    issue_refunds.short_description = "Issue refunds"

# ------------------- Ticket ------------------- #
@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('booking', 'passenger', 'ticket_status', 'issued_at', 'qr_code_link')
    list_filter = ('ticket_status', 'issued_at')
    search_fields = ('booking__id', 'passenger__first_name', 'passenger__last_name', 'qr_token')
    actions = ['reissue_tickets', 'mark_tickets_used']
    autocomplete_fields = ['booking', 'passenger']
    readonly_fields = ('issued_at', 'qr_token')
    list_per_page = 50

    def qr_code_link(self, obj):
        return format_html('<a href="{}" target="_blank">View</a>', escape(obj.qr_code.url)) if obj.qr_code else 'No QR Code'
    qr_code_link.short_description = 'QR Code'

    def reissue_tickets(self, request, queryset):
        updated_count = 0
        for ticket in queryset.exclude(ticket_status='cancelled'):
            ticket.ticket_status = 'active'
            ticket.issued_at = timezone.now()
            ticket.qr_token = uuid.uuid4().hex
            ticket.save()
            updated_count += 1
        self.message_user(request, f"Reissued {updated_count} tickets.", level=messages.SUCCESS)
    reissue_tickets.short_description = "Reissue tickets"

    def mark_tickets_used(self, request, queryset):
        updated_count = queryset.exclude(ticket_status='cancelled').update(
            ticket_status='used',
            issued_at=timezone.now()
        )
        self.message_user(request, f"Marked {updated_count} tickets as used.", level=messages.SUCCESS)
    mark_tickets_used.short_description = "Mark tickets as used"

# ------------------- Cargo ------------------- #
@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ('booking', 'cargo_type', 'weight_kg', 'price', 'qr_code_link')
    list_filter = ('cargo_type',)
    search_fields = ('booking__id', 'cargo_type')
    actions = ['update_cargo_prices', 'generate_cargo_qr_codes']
    autocomplete_fields = ['booking']
    list_per_page = 50

    def qr_code_link(self, obj):
        return format_html('<a href="{}" target="_blank">View</a>', escape(obj.qr_code.url)) if obj.qr_code else 'No QR Code'
    qr_code_link.short_description = 'QR Code'

    def update_cargo_prices(self, request, queryset):
        updated_count = 0
        for cargo in queryset:
            cargo.price = float(cargo.weight_kg) * 5.0
            cargo.save()
            updated_count += 1
        self.message_user(request, f"Updated prices for {updated_count} cargo items.", level=messages.SUCCESS)
    update_cargo_prices.short_description = "Update cargo prices"

    def generate_cargo_qr_codes(self, request, queryset):
        updated_count = 0
        for cargo in queryset:
            if cargo.qr_code:
                continue
            qr = QRCode()
            qr.add_data(f"Cargo: {cargo.id} - {cargo.cargo_type} - Booking: {cargo.booking.id}")
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            filename = f"cargo_{cargo.id}.png"
            cargo.qr_code.save(filename, ContentFile(buffer.getvalue()), save=True)
            updated_count += 1
        self.message_user(request, f"Generated QR codes for {updated_count} cargo items.", level=messages.SUCCESS)
    generate_cargo_qr_codes.short_description = "Generate cargo QR codes"

# ------------------- ServicePattern ------------------- #
@admin.register(ServicePattern)
class ServicePatternAdmin(admin.ModelAdmin):
    list_display = ('route', 'weekday', 'window', 'target_departures')
    list_filter = ('weekday', 'route')
    search_fields = ('route__departure_port__name', 'route__destination_port__name')
    autocomplete_fields = ['route']
    list_per_page = 50