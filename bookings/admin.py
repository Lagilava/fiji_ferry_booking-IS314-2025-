from django.contrib import admin
from .models import (
    Port, Cargo, Ferry, Route, WeatherCondition, Schedule,
    Booking, Passenger, Vehicle, AddOn, Payment, Ticket, MaintenanceLog, ServicePattern
)

@admin.register(Port)
class PortAdmin(admin.ModelAdmin):
    list_display = ('name', 'lat', 'lng', 'operating_hours_start', 'operating_hours_end', 'berths')
    list_filter = ('tide_sensitive', 'night_ops_allowed')
    search_fields = ('name',)
    list_per_page = 25
    ordering = ('name',)

@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ('booking', 'cargo_type', 'weight_kg', 'dimensions_cm', 'license_plate', 'price')
    list_filter = ('cargo_type',)
    search_fields = ('cargo_type', 'license_plate')
    raw_id_fields = ['booking']
    list_per_page = 25
    ordering = ('booking__booking_date',)

@admin.register(Ferry)
class FerryAdmin(admin.ModelAdmin):
    list_display = ('name', 'operator', 'capacity', 'is_active', 'home_port', 'cruise_speed_knots')
    list_filter = ('is_active', 'home_port')
    search_fields = ('name', 'operator')
    raw_id_fields = ['home_port']
    list_editable = ('is_active',)
    list_per_page = 25
    ordering = ('name',)

@admin.register(Route)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('departure_port', 'destination_port', 'distance_km', 'estimated_duration', 'base_fare', 'service_tier')
    list_filter = ('service_tier', 'departure_port', 'destination_port')
    search_fields = ('departure_port__name', 'destination_port__name')
    raw_id_fields = ['departure_port', 'destination_port']
    list_per_page = 25
    ordering = ('departure_port', 'destination_port')

@admin.register(WeatherCondition)
class WeatherConditionAdmin(admin.ModelAdmin):
    list_display = ('route', 'port', 'temperature', 'wind_speed', 'wave_height', 'condition', 'updated_at')
    list_filter = ('condition', 'port')
    search_fields = ('route__departure_port__name', 'route__destination_port__name', 'port__name')
    raw_id_fields = ['route', 'port']
    list_per_page = 25
    ordering = ('-updated_at',)

@admin.register(Schedule)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('ferry', 'route', 'departure_time', 'arrival_time', 'available_seats', 'status', 'operational_day')
    list_filter = ('status', 'ferry', 'route', 'operational_day')
    search_fields = ('ferry__name', 'route__departure_port__name', 'route__destination_port__name')
    date_hierarchy = 'departure_time'
    raw_id_fields = ['ferry', 'route']
    list_editable = ('status',)
    list_per_page = 25
    ordering = ('departure_time',)

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_email', 'schedule', 'booking_date', 'passenger_adults', 'passenger_children', 'passenger_infants', 'total_price', 'status')
    list_filter = ('status', 'schedule__route', 'booking_date')
    search_fields = ('user__email', 'guest_email', 'schedule__ferry__name')
    raw_id_fields = ['user', 'schedule']
    date_hierarchy = 'booking_date'
    list_editable = ('status',)
    list_per_page = 25
    ordering = ('-booking_date',)

    def user_email(self, obj):
        return obj.user.email if obj.user else obj.guest_email or 'Guest'
    user_email.short_description = 'User/Guest Email'

@admin.register(Passenger)
class PassengerAdmin(admin.ModelAdmin):
    list_display = ('booking', 'first_name', 'last_name', 'passenger_type', 'age', 'date_of_birth', 'linked_adult_display')
    list_filter = ('passenger_type',)
    search_fields = ('first_name', 'last_name', 'booking__id')
    raw_id_fields = ['booking', 'linked_adult']
    list_per_page = 25
    ordering = ('booking__booking_date', 'last_name')

    def linked_adult_display(self, obj):
        return obj.linked_adult.get_full_name() if obj.linked_adult else 'None'
    linked_adult_display.short_description = 'Linked Adult'

@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('booking', 'vehicle_type', 'dimensions', 'license_plate', 'price')
    list_filter = ('vehicle_type',)
    search_fields = ('license_plate', 'booking__id')
    raw_id_fields = ['booking']
    list_per_page = 25
    ordering = ('booking__booking_date',)

@admin.register(AddOn)
class AddOnAdmin(admin.ModelAdmin):
    list_display = ('booking', 'get_add_on_type_display', 'quantity', 'price')
    list_filter = ('add_on_type',)
    search_fields = ('booking__id', 'add_on_type')
    raw_id_fields = ['booking']
    list_per_page = 25
    ordering = ('booking__booking_date',)

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('booking', 'payment_method', 'amount', 'payment_status', 'payment_date')
    list_filter = ('payment_method', 'payment_status')
    search_fields = ('booking__id', 'transaction_id', 'session_id')
    raw_id_fields = ['booking']
    date_hierarchy = 'payment_date'
    list_per_page = 25
    ordering = ('-payment_date',)

@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('booking', 'passenger', 'ticket_status', 'issued_at', 'qr_token')
    list_filter = ('ticket_status',)
    search_fields = ('booking__id', 'passenger__first_name', 'passenger__last_name', 'qr_token')
    raw_id_fields = ['booking', 'passenger']
    date_hierarchy = 'issued_at'
    list_per_page = 25
    ordering = ('-issued_at',)

@admin.register(MaintenanceLog)
class MaintenanceLogAdmin(admin.ModelAdmin):
    list_display = ('ferry', 'maintenance_date', 'completed_at', 'maintenance_interval_days')
    list_filter = ('ferry', 'maintenance_date')
    search_fields = ('ferry__name',)
    raw_id_fields = ['ferry']
    date_hierarchy = 'maintenance_date'
    list_per_page = 25
    ordering = ('-maintenance_date',)

@admin.register(ServicePattern)
class ServicePatternAdmin(admin.ModelAdmin):
    list_display = ('route', 'get_weekday_display', 'window', 'target_departures')
    list_filter = ('weekday', 'route')
    search_fields = ('route__departure_port__name', 'route__destination_port__name')
    raw_id_fields = ['route']
    list_per_page = 25
    ordering = ('route', 'weekday')