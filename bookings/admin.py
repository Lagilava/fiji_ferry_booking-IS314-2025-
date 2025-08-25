from django.contrib import admin, messages
from django.utils import timezone
from django.utils.html import format_html
from django.db import models
from .models import (
    Ferry, Route, Schedule, Booking, Passenger, Payment, Ticket,
    Cargo, DocumentVerification, WeatherCondition, Port
)
import math
import csv
import requests
from django.conf import settings
from datetime import timedelta

# Predefined Fiji ports
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

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two points using Haversine formula."""
    R = 6371  # km
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

# Known route durations based on Fiji ferry data
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

# Maintenance interval for ferries (every 14 days)
MAINTENANCE_INTERVAL = 14

# ------------------- Port ------------------- #
@admin.register(Port)
class PortAdmin(admin.ModelAdmin):
    list_display = ('name', 'lat', 'lng')
    search_fields = ('name',)
    actions = ['import_fiji_ports', 'create_all_routes']

    def import_fiji_ports(self, request, queryset=None):
        created_count = 0
        updated_count = 0
        for port_data in FIJI_PORTS:
            port, created = Port.objects.update_or_create(
                name=port_data['name'],
                defaults={'lat': port_data['lat'], 'lng': port_data['lng']}
            )
            if created:
                created_count += 1
            else:
                updated_count += 1
        self.message_user(request, f"Created {created_count} and updated {updated_count} Fiji ports.")
    import_fiji_ports.short_description = "Import predefined Fiji ferry ports"

    def create_all_routes(self, request, queryset=None):
        """Create routes for all unique pairs of ports."""
        ports = Port.objects.all()
        if not ports:
            self.message_user(request, "No ports available. Please import or create ports first.", level=messages.ERROR)
            return

        created_count = 0
        skipped_count = 0
        routes_to_create = []

        for departure_port in ports:
            for destination_port in ports:
                if departure_port == destination_port:
                    continue  # Skip same-port routes
                # Check if route already exists
                if Route.objects.filter(
                    departure_port=departure_port,
                    destination_port=destination_port
                ).exists():
                    skipped_count += 1
                    continue

                # Calculate distance and duration
                distance_km = haversine_distance(
                    departure_port.lat, departure_port.lng,
                    destination_port.lat, destination_port.lng
                )
                # Use known duration if available, else calculate
                duration_key = (departure_port.name, destination_port.name)
                estimated_duration = KNOWN_DURATIONS.get(duration_key, timedelta(hours=distance_km / 25.0))
                base_fare = round(distance_km * 2.0, 2)  # $2 per km

                routes_to_create.append(
                    Route(
                        departure_port=departure_port,
                        destination_port=destination_port,
                        distance_km=distance_km,
                        estimated_duration=estimated_duration,
                        base_fare=base_fare
                    )
                )

        # Bulk create routes
        Route.objects.bulk_create(routes_to_create, ignore_conflicts=True)
        created_count = len(routes_to_create)
        self.message_user(
            request,
            f"Created {created_count} new routes. Skipped {skipped_count} existing routes.",
            level=messages.SUCCESS
        )
    create_all_routes.short_description = "Create routes for all port combinations"

# ------------------- WeatherCondition ------------------- #
@admin.register(WeatherCondition)
class WeatherConditionAdmin(admin.ModelAdmin):
    list_display = ('route', 'port', 'temperature', 'wind_speed', 'wave_height', 'condition', 'updated_at', 'expires_at', 'is_expired_display')
    list_filter = ('port__name', 'condition')
    search_fields = ('port__name', 'route__departure_port__name', 'route__destination_port__name')
    actions = ['refresh_weather_data', 'clear_expired_weather']
    autocomplete_fields = ['port']

    def is_expired_display(self, obj):
        return obj.is_expired()
    is_expired_display.short_description = 'Expired'
    is_expired_display.boolean = True

    def refresh_weather_data(self, request, queryset):
        updated_count = 0
        for weather in queryset:
            try:
                url = f"http://api.weatherapi.com/v1/current.json?key={settings.WEATHER_API_KEY}&q={weather.port.lat},{weather.port.lng}"
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()
                weather.temperature = data['current']['temp_c']
                weather.wind_speed = data['current']['wind_kph']
                weather.wave_height = 'N/A'  # Free API limit
                weather.condition = data['current']['condition']['text']
                weather.expires_at = timezone.now() + timedelta(minutes=30)
                weather.save()
                updated_count += 1
            except Exception as e:
                self.message_user(request, f"Error updating weather for {weather.port.name}: {str(e)}", level=messages.ERROR)
        self.message_user(request, f"Refreshed weather data for {updated_count} records.")
    refresh_weather_data.short_description = "Refresh weather data from API"

    def clear_expired_weather(self, request, queryset):
        expired_count = queryset.filter(expires_at__lt=timezone.now()).delete()[0]
        self.message_user(request, f"Cleared {expired_count} expired weather records.")
    clear_expired_weather.short_description = "Clear expired weather records"

# ------------------- Cargo ------------------- #
@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ('booking', 'cargo_type', 'weight_kg', 'price')
    list_filter = ('cargo_type',)
    search_fields = ('booking__id',)
    actions = ['update_cargo_prices']

    def update_cargo_prices(self, request, queryset):
        for cargo in queryset:
            cargo.price = cargo.weight_kg * 5.0
        Cargo.objects.bulk_update(queryset, ['price'])
        self.message_user(request, f"Updated prices for {queryset.count()} cargo items.")
    update_cargo_prices.short_description = "Update cargo prices based on weight"

# ------------------- Ferry ------------------- #
@admin.register(Ferry)
class FerryAdmin(admin.ModelAdmin):
    list_display = ('name', 'operator', 'capacity', 'is_active')
    search_fields = ('name', 'operator')
    list_filter = ('is_active',)
    actions = ['activate_ferries', 'deactivate_ferries', 'export_ferry_details']

    def activate_ferries(self, request, queryset):
        updated_count = queryset.update(is_active=True)
        self.message_user(request, f"Activated {updated_count} ferries.")
    activate_ferries.short_description = "Activate selected ferries"

    def deactivate_ferries(self, request, queryset):
        updated_count = queryset.update(is_active=False)
        self.message_user(request, f"Deactivated {updated_count} ferries.")
    deactivate_ferries.short_description = "Deactivate selected ferries"

    def export_ferry_details(self, request, queryset):
        response = self._export_csv(queryset, ['Name', 'Operator', 'Capacity', 'Is Active'],
                                    lambda f: [f.name, f.operator, f.capacity, f.is_active],
                                    'ferry_details.csv')
        return response
    export_ferry_details.short_description = "Export ferry details to CSV"

    def _export_csv(self, queryset, header, row_func, filename):
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        writer.writerow(header)
        for obj in queryset:
            writer.writerow(row_func(obj))
        return response

# ------------------- Route ------------------- #
@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('departure_port', 'destination_port', 'distance_km', 'estimated_duration')
    search_fields = ('departure_port__name', 'destination_port__name')
    autocomplete_fields = ['departure_port', 'destination_port']
    actions = ['recalculate_distances']

    def recalculate_distances(self, request, queryset):
        for route in queryset:
            route.distance_km = haversine_distance(
                route.departure_port.lat, route.departure_port.lng,
                route.destination_port.lat, route.destination_port.lng
            )
        Route.objects.bulk_update(queryset, ['distance_km'])
        self.message_user(request, f"Recalculated distances for {queryset.count()} routes.")
    recalculate_distances.short_description = "Recalculate route distances"

# ------------------- Schedule ------------------- #
@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('ferry', 'route', 'departure_time', 'arrival_time', 'available_seats', 'status')
    list_filter = ('status', 'departure_time')
    search_fields = ('ferry__name', 'route__departure_port__name', 'route__destination_port__name')
    actions = ['cancel_schedules', 'reset_seats', 'export_schedules', 'create_schedules_for_routes']
    autocomplete_fields = ['route']

    def cancel_schedules(self, request, queryset):
        updated_count = queryset.update(status='cancelled')
        self.message_user(request, f"Cancelled {updated_count} schedules.")
    cancel_schedules.short_description = "Cancel selected schedules"

    def reset_seats(self, request, queryset):
        queryset.update(available_seats=models.F('ferry__capacity'))
        self.message_user(request, f"Reset seats for {queryset.count()} schedules.")
    reset_seats.short_description = "Reset available seats to ferry capacity"

    def export_schedules(self, request, queryset):
        return FerryAdmin._export_csv(self, queryset,
                                      ['Ferry', 'Route', 'Departure Time', 'Arrival Time', 'Available Seats', 'Status'],
                                      lambda s: [s.ferry.name, f"{s.route.departure_port} to {s.route.destination_port}", s.departure_time, s.arrival_time, s.available_seats, s.status],
                                      'schedules.csv')
    export_schedules.short_description = "Export schedules to CSV"

    def create_schedules_for_routes(self, request, queryset=None):
        """Create schedules for all routes with realistic durations and turnaround time."""
        routes = Route.objects.all()
        ferries = Ferry.objects.filter(is_active=True)
        if not routes:
            self.message_user(request, "No routes available. Please create routes first.", level=messages.ERROR)
            return
        if not ferries:
            self.message_user(request, "No active ferries available. Please create or activate ferries.", level=messages.ERROR)
            return

        created_count = 0
        skipped_count = 0
        schedules_to_create = []
        start_date = (timezone.now() + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)  # Start at 6 AM tomorrow
        turnaround_time = timedelta(hours=8)  # Minimum 8-hour turnaround

        # Track last arrival time for each ferry to enforce turnaround
        ferry_last_arrival = {ferry.id: start_date - turnaround_time for ferry in ferries}

        for route in routes:
            # Use known duration if available, else use route's estimated_duration
            duration_key = (route.departure_port.name, route.destination_port.name)
            duration = KNOWN_DURATIONS.get(duration_key, route.estimated_duration)

            # Create schedules for the next 3 days
            for day_offset in range(3):
                schedule_date = start_date + timedelta(days=day_offset)
                # Skip maintenance days (every 14 days from a fixed date, e.g., 2025-08-14)
                days_since_epoch = (schedule_date.date() - timezone.datetime(2025, 8, 14).date()).days
                if days_since_epoch % MAINTENANCE_INTERVAL == 0:
                    continue  # Skip maintenance day

                # Major routes get twice-daily schedules
                is_major_route = duration_key in KNOWN_DURATIONS
                times = [schedule_date] if not is_major_route else [
                    schedule_date,
                    schedule_date + timedelta(hours=6)  # Second departure at noon
                ]

                for dep_time in times:
                    for ferry in ferries:
                        # Check turnaround time
                        if dep_time < ferry_last_arrival[ferry.id] + turnaround_time:
                            skipped_count += 1
                            continue

                        # Check for existing schedule
                        if Schedule.objects.filter(
                            ferry=ferry,
                            route=route,
                            departure_time=dep_time
                        ).exists():
                            skipped_count += 1
                            continue

                        arrival_time = dep_time + duration
                        schedules_to_create.append(
                            Schedule(
                                ferry=ferry,
                                route=route,
                                departure_time=dep_time,
                                arrival_time=arrival_time,
                                available_seats=ferry.capacity,
                                status='scheduled'
                            )
                        )
                        # Update ferry's last arrival time
                        ferry_last_arrival[ferry.id] = max(ferry_last_arrival[ferry.id], arrival_time)

        # Bulk create schedules
        Schedule.objects.bulk_create(schedules_to_create, ignore_conflicts=True)
        created_count = len(schedules_to_create)
        self.message_user(
            request,
            f"Created {created_count} new schedules. Skipped {skipped_count} due to turnaround or existing schedules.",
            level=messages.SUCCESS
        )
    create_schedules_for_routes.short_description = "Create schedules for all routes"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'ferry', 'route', 'route__departure_port', 'route__destination_port'
        )

# ------------------- Booking ------------------- #
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user_email', 'schedule', 'booking_date',
        'total_passengers', 'total_price', 'status',
        'is_unaccompanied_minor', 'is_group_booking', 'is_emergency',
    )
    list_filter = (
        'status', 'booking_date', 'is_unaccompanied_minor',
        'is_group_booking', 'is_emergency',
    )
    search_fields = ('user__email', 'guest_email', 'schedule__ferry__name')
    actions = ['generate_manifest', 'approve_emergency_booking', 'cancel_bookings']
    readonly_fields = ('booking_date',)
    date_hierarchy = 'booking_date'

    def user_email(self, obj):
        return obj.user.email if obj.user else obj.guest_email or 'N/A'
    user_email.short_description = 'User/Guest Email'

    def total_passengers(self, obj):
        return obj.passengers.count()
    total_passengers.short_description = 'Total Passengers'

    def generate_manifest(self, request, queryset):
        for booking in queryset:
            passengers = booking.passengers.all()
            manifest = ", ".join([f"{p.first_name} {p.last_name} ({p.passenger_type})" for p in passengers])
            self.message_user(request, f"Manifest for Booking {booking.id}: {manifest}")
    generate_manifest.short_description = "Generate passenger manifest"

    def approve_emergency_booking(self, request, queryset):
        for booking in queryset:
            booking.status = 'emergency'
            booking.is_emergency = True
            booking.save()
            passengers_to_update = []
            verifications = []
            for passenger in booking.passengers.all():
                if passenger.document:
                    verifications.append(DocumentVerification(
                        passenger=passenger,
                        document=passenger.document,
                        verification_status='temporary',
                        verified_by=request.user,
                        verified_at=timezone.now(),
                        expires_at=booking.schedule.departure_time + timedelta(days=1)
                    ))
                    passenger.verification_status = 'temporary'
                    passengers_to_update.append(passenger)
            DocumentVerification.objects.bulk_create(verifications, ignore_conflicts=True)
            Passenger.objects.bulk_update(passengers_to_update, ['verification_status'])
        self.message_user(request, f"{queryset.count()} bookings approved for emergency travel.")
    approve_emergency_booking.short_description = "Approve emergency travel"

    def cancel_bookings(self, request, queryset):
        updated_count = queryset.update(status='cancelled')
        self.message_user(request, f"Cancelled {updated_count} bookings.")
    cancel_bookings.short_description = "Cancel selected bookings"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'schedule__ferry', 'schedule__route',
            'schedule__route__departure_port', 'schedule__route__destination_port'
        ).prefetch_related('passengers')

# ------------------- Passenger ------------------- #
@admin.register(Passenger)
class PassengerAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'booking', 'passenger_type', 'age', 'document_link', 'verification_status', 'linked_adult')
    list_filter = ('passenger_type', 'verification_status')
    search_fields = ('first_name', 'last_name', 'booking__id')
    actions = ['verify_documents', 'reject_documents']

    def document_link(self, obj):
        return format_html('<a href="{}" target="_blank">View Document</a>', obj.document.url) if obj.document else 'No Document'
    document_link.short_description = 'Document'

    def verify_documents(self, request, queryset):
        verifications = []
        for passenger in queryset:
            if passenger.document:
                verifications.append(DocumentVerification(
                    passenger=passenger,
                    document=passenger.document,
                    verification_status='verified',
                    verified_by=request.user,
                    verified_at=timezone.now()
                ))
                passenger.verification_status = 'verified'
        DocumentVerification.objects.bulk_create(verifications, ignore_conflicts=True)
        Passenger.objects.bulk_update(queryset, ['verification_status'])
        self.message_user(request, f"{queryset.count()} passengers verified.")
    verify_documents.short_description = "Verify passenger documents"

    def reject_documents(self, request, queryset):
        verifications = []
        for passenger in queryset:
            if passenger.document:
                verifications.append(DocumentVerification(
                    passenger=passenger,
                    document=passenger.document,
                    verification_status='rejected',
                    verified_by=request.user,
                    verified_at=timezone.now()
                ))
                passenger.verification_status = 'missing'
        DocumentVerification.objects.bulk_create(verifications, ignore_conflicts=True)
        Passenger.objects.bulk_update(queryset, ['verification_status'])
        self.message_user(request, f"{queryset.count()} passenger documents rejected.")
    reject_documents.short_description = "Reject passenger documents"

# ------------------- DocumentVerification ------------------- #
@admin.register(DocumentVerification)
class DocumentVerificationAdmin(admin.ModelAdmin):
    list_display = ('passenger', 'document_link', 'verification_status', 'verified_by', 'verified_at', 'expires_at')
    list_filter = ('verification_status',)
    search_fields = ('passenger__first_name', 'passenger__last_name')

    def document_link(self, obj):
        return format_html('<a href="{}" target="_blank">View Document</a>', obj.document.url) if obj.document else 'No Document'
    document_link.short_description = 'Document'

# ------------------- Payment ------------------- #
@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('booking', 'payment_method', 'amount', 'payment_status', 'payment_date')
    list_filter = ('payment_method', 'payment_status')
    search_fields = ('booking__id', 'transaction_id')
    actions = ['mark_as_completed', 'issue_refunds']

    def mark_as_completed(self, request, queryset):
        updated_count = queryset.update(payment_status='completed')
        self.message_user(request, f"Marked {updated_count} payments as completed.")
    mark_as_completed.short_description = "Mark payments as completed"

    def issue_refunds(self, request, queryset):
        updated_count = queryset.update(payment_status='refunded')
        self.message_user(request, f"Issued refunds for {updated_count} payments.")
    issue_refunds.short_description = "Issue refunds for selected payments"

# ------------------- Ticket ------------------- #
@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('booking', 'passenger', 'ticket_status', 'issued_at')
    list_filter = ('ticket_status',)
    search_fields = ('booking__id', 'passenger__first_name', 'passenger__last_name')
    actions = ['reissue_tickets']

    def reissue_tickets(self, request, queryset):
        for ticket in queryset:
            ticket.ticket_status = 'reissued'
            ticket.issued_at = timezone.now()
        Ticket.objects.bulk_update(queryset, ['ticket_status', 'issued_at'])
        self.message_user(request, f"Reissued {queryset.count()} tickets.")
    reissue_tickets.short_description = "Reissue selected tickets"