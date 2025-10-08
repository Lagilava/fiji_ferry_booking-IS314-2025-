from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Sum, F, Avg, Max
from django.utils import timezone
from django.db.models import ExpressionWrapper, FloatField
from django.db.models.functions import Round, Coalesce, ExtractWeekDay
from django.core.cache import cache
from datetime import timedelta
from django.contrib.admin.models import LogEntry
from .models import (
    Port, Cargo, Ferry, Route, WeatherCondition, Schedule,
    Booking, Passenger, Vehicle, AddOn, Payment, Ticket, MaintenanceLog, ServicePattern
)
from accounts.models import User
import logging
from collections import defaultdict
from django.utils.html import format_html

# Set up logging
logger = logging.getLogger(__name__)

# Define custom admin site
class CustomAdminSite(admin.AdminSite):
    site_header = "Fiji Ferry Booking Admin"
    site_title = "Fiji Ferry Admin"
    index_title = "Dashboard"

    def get_alerts(self, current_time):
        """Generate dynamic alerts for low availability, delays, and maintenance."""
        alerts = []
        low_availability_schedules = Schedule.objects.filter(
            available_seats__lt=10,
            departure_time__gte=current_time,
            departure_time__lte=current_time + timedelta(days=1)
        ).select_related('route')[:3]
        for schedule in low_availability_schedules:
            alerts.append({
                'message': f"Low availability ({schedule.available_seats} seats) on {schedule.route} at {schedule.departure_time.strftime('%H:%M %d %b')}",
                'link': f"/admin/bookings/schedule/{schedule.id}/change/"
            })
        delayed_schedules = Schedule.objects.filter(
            status='delayed',
            departure_time__gte=current_time - timedelta(hours=12),
            departure_time__lte=current_time + timedelta(hours=12)
        ).select_related('route')[:3]
        for schedule in delayed_schedules:
            alerts.append({
                'message': f"Delay on {schedule.route} at {schedule.departure_time.strftime('%H:%M %d %b')}",
                'link': f"/admin/bookings/schedule/{schedule.id}/change/"
            })
        recent_maintenance = MaintenanceLog.objects.filter(
            maintenance_date__gte=current_time - timedelta(days=7),
            completed_at__isnull=True
        ).select_related('ferry')[:3]
        for log in recent_maintenance:
            alerts.append({
                'message': f"Pending maintenance for {log.ferry} scheduled on {log.maintenance_date.strftime('%d %b')}",
                'link': f"/admin/bookings/maintenancelog/{log.id}/change/"
            })
        if not alerts:
            alerts.append({
                'message': f"All systems operational as of {current_time.strftime('%H:%M %d %b %Y')}",
                'link': None
            })
        return alerts

    def index(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}
        current_time = timezone.now()  # Use real-time

        # Fetch analytics data
        analytics_data = self.analytics_data_view(request)

        # Performance metrics
        total_bookings = Booking.objects.count()
        active_ferries = Ferry.objects.filter(is_active=True).count()
        pending_payments = Payment.objects.filter(payment_status='pending').count()
        total_revenue = Booking.objects.aggregate(total=Sum('total_price'))['total'] or 0
        registered_users = User.objects.count()
        average_booking_value = Booking.objects.aggregate(avg=Avg('total_price'))['avg'] or 0

        # Recent bookings
        recent_bookings = [
            {
                'id': booking.id,
                'user_email': booking.user.email if booking.user else booking.guest_email or 'Guest',
                'schedule': str(booking.schedule),
                'booking_date': booking.booking_date.isoformat(),
                'status': booking.status
            }
            for booking in Booking.objects.select_related('user', 'schedule').order_by('-booking_date')[:10]
        ]

        # Recent activities (consolidated)
        recent_logs = LogEntry.objects.select_related('user', 'content_type').filter(
            action_time__gte=current_time - timedelta(days=7)
        ).order_by('-action_time')[:10]
        consolidated_activities = defaultdict(lambda: {'count': 0, 'timestamp': None, 'operator': None, 'action': None, 'resource': None})
        for log in recent_logs:
            action = log.get_change_message()
            resource = f"{log.content_type} ({log.object_repr})"
            key = (action, resource)
            if key in consolidated_activities:
                consolidated_activities[key]['count'] += 1
            else:
                consolidated_activities[key]['count'] = 1
                consolidated_activities[key]['timestamp'] = log.action_time
                consolidated_activities[key]['operator'] = log.user.username
                consolidated_activities[key]['action'] = action
                consolidated_activities[key]['resource'] = resource
        recent_activities = [
            {
                'timestamp': v['timestamp'].isoformat(),
                'operator': v['operator'],
                'action': v['action'],
                'resource': v['resource'],
                'count': v['count']
            }
            for v in consolidated_activities.values()
        ]

        # Fleet status
        fleet_status = [
            {
                'name': ferry.name,
                'status': 'Active' if ferry.is_active else 'Inactive',
                'capacity': ferry.capacity,
                'last_maintenance': MaintenanceLog.objects.filter(ferry=ferry).order_by('-maintenance_date').first().maintenance_date.isoformat() if MaintenanceLog.objects.filter(ferry=ferry).exists() else None
            }
            for ferry in Ferry.objects.all()[:5]
        ]

        # Weather conditions
        weather_conditions = [
            {
                'port': weather['port__name'],
                'condition': weather['condition'],
                'temperature': weather['temperature'],
                'wind_speed': weather['wind_speed'],
                'wave_height': weather['wave_height'],
                'updated_at': weather['updated_at'].isoformat()
            }
            for weather in WeatherCondition.objects.values('port__name', 'condition', 'temperature', 'wind_speed', 'wave_height', 'updated_at').annotate(latest=Max('updated_at')).order_by('-updated_at')[:5]
        ]

        # Alerts
        alerts = self.get_alerts(current_time)

        extra_context.update({
            'bookings_per_route': analytics_data.get('bookings_per_route', []),
            'ferry_utilization': analytics_data.get('ferry_utilization', []),
            'revenue_over_time': analytics_data.get('revenue_over_time', []),
            'bookings_over_time': analytics_data.get('bookings_over_time', []),
            'payment_status': analytics_data.get('payment_status', []),
            'user_growth': analytics_data.get('user_growth', []),
            'top_customers': analytics_data.get('top_customers', []),
            'recent_bookings': recent_bookings,
            'recent_activities': recent_activities,
            'fleet_status': fleet_status,
            'weather_conditions': weather_conditions,
            'total_bookings': total_bookings,
            'active_ferries': active_ferries,
            'pending_payments': pending_payments,
            'total_revenue': round(float(total_revenue), 2),
            'registered_users': registered_users,
            'average_booking_value': round(float(average_booking_value), 2),
            'alerts': alerts,
            'current_time': current_time.isoformat(),
            'charts_initialized': False
        })
        request.session['charts_initialized'] = False
        return super().index(request, extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('analytics-data/', staff_member_required(self.analytics_data_view), name='analytics-data'),
        ]
        return custom_urls + urls

    def analytics_data_view(self, request):
        days = request.GET.get('days', '30')
        chart_type = request.GET.get('chart_type', None)
        cache_key = f'analytics_data_{chart_type or "full"}_{days}'  # Avoid cache collisions
        data = cache.get(cache_key)
        if not data:
            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=int(days)) if days != 'all' else None
            current_time = timezone.now()  # Use real-time

            logger.info(f"Fetching analytics data for chart {chart_type} with days: {days}, start_date: {start_date}, end_date: {end_date}")

            data = {}
            if chart_type in [None, 'bookings_per_route']:
                bookings_per_route = (
                    Booking.objects.filter(booking_date__date__gte=start_date, booking_date__date__lte=end_date)
                    if start_date else Booking.objects.all()
                ).select_related('schedule__route__departure_port', 'schedule__route__destination_port').values(
                    'schedule__route__id', 'schedule__route__departure_port__name',
                    'schedule__route__destination_port__name', 'schedule__route__service_tier'
                ).annotate(total_bookings=Count('id')).order_by('-total_bookings')[:10]
                data['bookings_per_route'] = [
                    {
                        'route': f"{item['schedule__route__departure_port__name']} to {item['schedule__route__destination_port__name']}",
                        'count': item['total_bookings'],
                        'route_type': item['schedule__route__service_tier'] or 'standard'
                    }
                    for item in bookings_per_route
                ] if bookings_per_route else [{'route': 'No Data', 'count': 0, 'route_type': 'standard'}]
                logger.debug(f"Bookings per route data: {data['bookings_per_route']}")

            if chart_type in [None, 'ferry_utilization']:
                schedules = (
                    Schedule.objects.filter(
                        departure_time__date__gte=start_date,
                        departure_time__date__lte=end_date,
                        ferry__capacity__gt=0,
                        available_seats__isnull=False
                    ) if start_date else Schedule.objects.filter(
                        ferry__capacity__gt=0, available_seats__isnull=False
                    )
                ).select_related('ferry').annotate(
                    seats_filled=ExpressionWrapper(
                        F('ferry__capacity') - Coalesce(F('available_seats'), 0),
                        output_field=FloatField()
                    ),
                    week_day=ExtractWeekDay('departure_time')
                ).values('ferry__name', 'week_day').annotate(
                    utilization=Round(
                        Avg(
                            ExpressionWrapper(
                                F('seats_filled') * 100.0 / F('ferry__capacity'),
                                output_field=FloatField()
                            )
                        ), 2
                    )
                ).order_by('ferry__name', 'week_day')
                logger.info(f"Ferry Utilization Query Result: {list(schedules)}")
                data['ferry_utilization'] = [
                    {
                        'ferry': item['ferry__name'] or 'Unknown Ferry',
                        'utilization': float(item['utilization'] or 0),
                        'day_of_week': ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'][item['week_day'] - 1]
                    }
                    for item in schedules
                ] if schedules else [{'ferry': 'No Data', 'utilization': 0, 'day_of_week': 'Monday'}]
                if not schedules:
                    logger.warning(f"No ferry utilization data found for {start_date or 'all time'} to {end_date}. Check Schedule objects, ferry__capacity, available_seats, and departure_time.")

            if chart_type in [None, 'revenue_over_time']:
                revenue_data = (
                    Booking.objects.filter(booking_date__date__gte=start_date, booking_date__date__lte=end_date)
                    if start_date else Booking.objects.all()
                ).values('booking_date__date').annotate(total_revenue=Sum('total_price')).order_by('booking_date__date')
                data['revenue_over_time'] = [
                    {'date': item['booking_date__date'].strftime('%Y-%m-%d'), 'revenue': float(item['total_revenue'] or 0)}
                    for item in revenue_data
                ] if revenue_data else [{'date': end_date.strftime('%Y-%m-%d'), 'revenue': 0}]
                logger.debug(f"Revenue over time data: {data['revenue_over_time']}")

            if chart_type in [None, 'bookings_over_time']:
                bookings_over_time = (
                    Booking.objects.filter(booking_date__date__gte=start_date, booking_date__date__lte=end_date)
                    if start_date else Booking.objects.all()
                ).values('booking_date__date').annotate(count=Count('id')).order_by('booking_date__date')
                data['bookings_over_time'] = [
                    {'date': item['booking_date__date'].strftime('%Y-%m-%d'), 'count': item['count']}
                    for item in bookings_over_time
                ] if bookings_over_time else [{'date': end_date.strftime('%Y-%m-%d'), 'count': 0}]
                logger.debug(f"Bookings over time data: {data['bookings_over_time']}")

            if chart_type in [None, 'payment_status']:
                payment_status = (
                    Payment.objects.filter(payment_date__date__gte=start_date, payment_date__date__lte=end_date)
                    if start_date else Payment.objects.all()
                ).values('payment_status').annotate(count=Count('id'), amount=Sum('amount'))
                data['payment_status'] = [
                    {'status': item['payment_status'].capitalize(), 'count': item['count'], 'amount': float(item['amount'] or 0)}
                    for item in payment_status
                ] if payment_status else [{'status': 'No Data', 'count': 0, 'amount': 0}]
                logger.debug(f"Payment status data: {data['payment_status']}")

            if chart_type in [None, 'user_growth']:
                user_growth = (
                    User.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
                    if start_date else User.objects.all()
                ).values('created_at__date').annotate(count=Count('id')).order_by('created_at__date')
                data['user_growth'] = [
                    {'date': item['created_at__date'].strftime('%Y-%m-%d'), 'count': item['count']}
                    for item in user_growth
                ] if user_growth else [{'date': end_date.strftime('%Y-%m-%d'), 'count': 0}]
                logger.debug(f"User growth data: {data['user_growth']}")

            if chart_type in [None, 'top_customers']:
                top_customers = (
                    Booking.objects.filter(booking_date__date__gte=start_date, booking_date__date__lte=end_date)
                    if start_date else Booking.objects.all()
                ).values('user__email').annotate(count=Count('id')).order_by('-count')[:5]
                data['top_customers'] = [
                    {'user': item['user__email'] or 'Guest', 'count': item['count']}
                    for item in top_customers
                ] if top_customers else [{'user': 'No Data', 'count': 0}]
                logger.debug(f"Top customers data: {data['top_customers']}")

            if chart_type in [None, 'recent_bookings']:
                data['recent_bookings'] = [
                    {
                        'id': booking.id,
                        'user_email': booking.user.email if booking.user else booking.guest_email or 'Guest',
                        'schedule': str(booking.schedule),
                        'booking_date': booking.booking_date.isoformat(),
                        'status': booking.status
                    }
                    for booking in Booking.objects.select_related('user', 'schedule').order_by('-booking_date')[:10]
                ]
                logger.debug(f"Recent bookings data: {data['recent_bookings']}")

            if chart_type in [None, 'recent_activities']:
                recent_logs = LogEntry.objects.select_related('user', 'content_type').filter(
                    action_time__gte=current_time - timedelta(days=7)
                ).order_by('-action_time')[:10]
                consolidated_activities = defaultdict(lambda: {'count': 0, 'timestamp': None, 'operator': None, 'action': None, 'resource': None})
                for log in recent_logs:
                    action = log.get_change_message()
                    resource = f"{log.content_type} ({log.object_repr})"
                    key = (action, resource)
                    if key in consolidated_activities:
                        consolidated_activities[key]['count'] += 1
                    else:
                        consolidated_activities[key]['count'] = 1
                        consolidated_activities[key]['timestamp'] = log.action_time
                        consolidated_activities[key]['operator'] = log.user.username
                        consolidated_activities[key]['action'] = action
                        consolidated_activities[key]['resource'] = resource
                data['recent_activities'] = [
                    {
                        'timestamp': v['timestamp'].isoformat(),
                        'operator': v['operator'],
                        'action': v['action'],
                        'resource': v['resource'],
                        'count': v['count']
                    }
                    for v in consolidated_activities.values()
                ]
                logger.debug(f"Recent activities data: {data['recent_activities']}")

            if chart_type in [None, 'fleet_status']:
                data['fleet_status'] = [
                    {
                        'name': ferry.name,
                        'status': 'Active' if ferry.is_active else 'Inactive',
                        'capacity': ferry.capacity,
                        'last_maintenance': MaintenanceLog.objects.filter(ferry=ferry).order_by('-maintenance_date').first().maintenance_date.isoformat() if MaintenanceLog.objects.filter(ferry=ferry).exists() else None
                    }
                    for ferry in Ferry.objects.select_related('home_port').all()[:5]
                ]
                logger.debug(f"Fleet status data: {data['fleet_status']}")

            if chart_type in [None, 'weather_conditions']:
                data['weather_conditions'] = [
                    {
                        'port': weather['port__name'],
                        'condition': weather['condition'],
                        'temperature': weather['temperature'],
                        'wind_speed': weather['wind_speed'],
                        'wave_height': weather['wave_height'],
                        'updated_at': weather['updated_at'].isoformat()
                    }
                    for weather in WeatherCondition.objects.values('port__name', 'condition', 'temperature', 'wind_speed', 'wave_height', 'updated_at').annotate(latest=Max('updated_at')).order_by('-updated_at')[:5]
                ]
                logger.debug(f"Weather conditions data: {data['weather_conditions']}")

            if chart_type in [None, 'alerts']:
                data['alerts'] = self.get_alerts(current_time)
                logger.debug(f"Alerts data: {data['alerts']}")

            # Sanitize sensitive data if user lacks permission
            if not request.user.has_perm('bookings.view_sensitive_data'):
                for booking in data.get('recent_bookings', []):
                    booking['user_email'] = 'Restricted'
                for customer in data.get('top_customers', []):
                    customer['user'] = 'Restricted'

            cache.set(cache_key, data, timeout=300)  # Cache for 5 minutes

        # Return JSON for AJAX requests, dict for internal calls
        if request.path.endswith('analytics-data/'):
            return JsonResponse(data)
        return data

# Instantiate admin_site before decorators
admin_site = CustomAdminSite(name='custom_admin')

# Register models with custom admin site
@admin.register(Port, site=admin_site)
class PortAdmin(admin.ModelAdmin):
    list_display = ('name', 'lat', 'lng', 'operating_hours_start', 'operating_hours_end', 'berths')
    list_filter = ('tide_sensitive', 'night_ops_allowed')
    search_fields = ('name',)
    list_per_page = 25
    ordering = ('name',)
    icon_name = 'anchor'
    list_display_links = ('name',)

@admin.register(Cargo, site=admin_site)
class CargoAdmin(admin.ModelAdmin):
    list_display = ('booking', 'cargo_type', 'weight_kg', 'dimensions_cm', 'license_plate', 'price')
    list_filter = ('cargo_type',)
    search_fields = ('cargo_type', 'license_plate')
    autocomplete_fields = ['booking']
    list_per_page = 25
    ordering = ('booking__booking_date',)
    icon_name = 'box'
    list_display_links = ('booking',)
    fieldsets = (
        ('General Info', {'fields': ('booking', 'cargo_type')}),
        ('Details', {'fields': ('weight_kg', 'dimensions_cm', 'license_plate', 'price')}),
    )

@admin.register(Ferry, site=admin_site)
class FerryAdmin(admin.ModelAdmin):
    list_display = ('name', 'operator', 'capacity', 'is_active', 'home_port', 'cruise_speed_knots')
    list_filter = ('is_active', 'home_port')
    search_fields = ('name', 'operator')
    autocomplete_fields = ['home_port']
    list_editable = ('is_active',)
    list_per_page = 25
    ordering = ('name',)
    icon_name = 'ship'
    list_display_links = ('name',)
    fieldsets = (
        ('General Info', {'fields': ('name', 'operator', 'home_port')}),
        ('Specifications', {'fields': ('capacity', 'cruise_speed_knots')}),
        ('Status', {'fields': ('is_active',)}),
    )

@admin.register(Route, site=admin_site)
class RouteAdmin(admin.ModelAdmin):
    list_display = ('departure_port', 'destination_port', 'distance_km', 'estimated_duration', 'base_fare', 'service_tier')
    list_filter = ('service_tier', 'departure_port', 'destination_port')
    search_fields = ('departure_port__name', 'destination_port__name')
    autocomplete_fields = ['departure_port', 'destination_port']
    list_per_page = 25
    ordering = ('departure_port', 'destination_port')
    icon_name = 'route'
    list_display_links = ('departure_port', 'destination_port')

@admin.register(WeatherCondition, site=admin_site)
class WeatherConditionAdmin(admin.ModelAdmin):
    list_display = ('route', 'port', 'temperature', 'wind_speed', 'wave_height', 'condition', 'updated_at')
    list_filter = ('condition', 'port')
    search_fields = ('route__departure_port__name', 'route__destination_port__name', 'port__name')
    autocomplete_fields = ['route', 'port']
    list_per_page = 25
    ordering = ('-updated_at',)
    icon_name = 'cloud'
    list_display_links = ('route', 'port')

@admin.register(Schedule, site=admin_site)
class ScheduleAdmin(admin.ModelAdmin):
    list_display = ('ferry', 'route', 'departure_time', 'arrival_time', 'available_seats', 'status', 'operational_day')
    list_filter = ('status', 'ferry', 'route', 'operational_day')
    search_fields = ('ferry__name', 'route__departure_port__name', 'route__destination_port__name')
    date_hierarchy = 'departure_time'
    autocomplete_fields = ['ferry', 'route']
    list_editable = ('status',)
    list_per_page = 25
    ordering = ('departure_time',)
    icon_name = 'calendar-alt'
    list_display_links = ('ferry', 'route')
    fieldsets = (
        ('Schedule Info', {'fields': ('ferry', 'route', 'departure_time', 'arrival_time')}),
        ('Details', {'fields': ('available_seats', 'status', 'operational_day')}),
    )

@admin.register(Booking, site=admin_site)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_email', 'schedule', 'booking_date', 'passenger_adults', 'passenger_children', 'passenger_infants', 'total_price', 'status')
    list_filter = ('status', 'schedule__route', 'booking_date')
    search_fields = ('user__email', 'guest_email', 'schedule__ferry__name')
    autocomplete_fields = ['user', 'schedule']
    date_hierarchy = 'booking_date'
    list_editable = ('status',)
    list_per_page = 25
    ordering = ('-booking_date',)
    icon_name = 'ticket-alt'
    list_display_links = ('id', 'user_email')
    readonly_fields = ('total_price', 'booking_date')
    fieldsets = (
        ('General Info', {'fields': ('user', 'guest_email', 'schedule', 'booking_date')}),
        ('Passenger Details', {'fields': ('passenger_adults', 'passenger_children', 'passenger_infants')}),
        ('Status and Pricing', {'fields': ('status', 'total_price')}),
    )

    def user_email(self, obj):
        email = obj.user.email if obj.user else obj.guest_email or 'Guest'
        return format_html('<span aria-label="User or guest email">{}</span>', email)

    user_email.short_description = 'User/Guest Email'

@admin.register(Passenger, site=admin_site)
class PassengerAdmin(admin.ModelAdmin):
    list_display = ('booking', 'first_name', 'last_name', 'passenger_type', 'age', 'date_of_birth', 'linked_adult_display')
    list_filter = ('passenger_type',)
    search_fields = ('first_name', 'last_name', 'booking__id')
    autocomplete_fields = ['booking', 'linked_adult']
    list_per_page = 25
    ordering = ('booking__booking_date', 'last_name')
    icon_name = 'user'
    list_display_links = ('booking', 'first_name')
    fieldsets = (
        ('General Info', {'fields': ('booking', 'first_name', 'last_name')}),
        ('Details', {'fields': ('passenger_type', 'age', 'date_of_birth', 'linked_adult')}),
    )

    def linked_adult_display(self, obj):
        name = obj.linked_adult.get_full_name() if obj.linked_adult else 'None'
        return format_html('<span aria-label="Linked adult name">{}</span>', name)

    linked_adult_display.short_description = 'Linked Adult'

@admin.register(Vehicle, site=admin_site)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('booking', 'vehicle_type', 'dimensions', 'license_plate', 'price')
    list_filter = ('vehicle_type',)
    search_fields = ('license_plate', 'booking__id')
    autocomplete_fields = ['booking']
    list_per_page = 25
    ordering = ('booking__booking_date',)
    icon_name = 'car'
    list_display_links = ('booking',)
    fieldsets = (
        ('General Info', {'fields': ('booking', 'vehicle_type')}),
        ('Details', {'fields': ('dimensions', 'license_plate', 'price')}),
    )

@admin.register(AddOn, site=admin_site)
class AddOnAdmin(admin.ModelAdmin):
    list_display = ('booking', 'get_add_on_type_display', 'quantity', 'price')
    list_filter = ('add_on_type',)
    search_fields = ('booking__id', 'add_on_type')
    autocomplete_fields = ['booking']
    list_per_page = 25
    ordering = ('booking__booking_date',)
    icon_name = 'plus-circle'
    list_display_links = ('booking',)
    fieldsets = (
        ('General Info', {'fields': ('booking', 'add_on_type')}),
        ('Details', {'fields': ('quantity', 'price')}),
    )

@admin.register(Payment, site=admin_site)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('booking', 'payment_method', 'amount', 'payment_status', 'payment_date')
    list_filter = ('payment_method', 'payment_status')
    search_fields = ('booking__id', 'transaction_id', 'session_id')
    autocomplete_fields = ['booking']
    date_hierarchy = 'payment_date'
    list_per_page = 25
    ordering = ('-payment_date',)
    icon_name = 'credit-card'
    list_display_links = ('booking',)
    readonly_fields = ('amount', 'payment_date')
    fieldsets = (
        ('General Info', {'fields': ('booking', 'payment_method')}),
        ('Details', {'fields': ('amount', 'payment_status', 'payment_date', 'transaction_id', 'session_id')}),
    )

@admin.register(Ticket, site=admin_site)
class TicketAdmin(admin.ModelAdmin):
    list_display = ('booking', 'passenger', 'ticket_status', 'issued_at', 'qr_token')
    list_filter = ('ticket_status',)
    search_fields = ('booking__id', 'passenger__first_name', 'passenger__last_name', 'qr_token')
    autocomplete_fields = ['booking', 'passenger']
    date_hierarchy = 'issued_at'
    list_per_page = 25
    ordering = ('-issued_at',)
    icon_name = 'ticket-alt'
    list_display_links = ('booking', 'passenger')
    readonly_fields = ('issued_at', 'qr_token')  # Mark non-editable fields as readonly
    fieldsets = (
        ('General Info', {'fields': ('booking', 'passenger')}),
        ('Details', {'fields': ('ticket_status', 'issued_at', 'qr_code', 'qr_token')}),
    )

@admin.register(MaintenanceLog, site=admin_site)
class MaintenanceLogAdmin(admin.ModelAdmin):
    list_display = ('ferry', 'maintenance_date', 'completed_at', 'maintenance_interval_days')
    list_filter = ('ferry', 'maintenance_date')
    search_fields = ('ferry__name',)
    autocomplete_fields = ['ferry']
    date_hierarchy = 'maintenance_date'
    list_per_page = 25
    ordering = ('-maintenance_date',)
    icon_name = 'tools'
    list_display_links = ('ferry',)
    fieldsets = (
        ('General Info', {'fields': ('ferry', 'maintenance_date')}),
        ('Details', {'fields': ('completed_at', 'maintenance_interval_days')}),
    )

@admin.register(ServicePattern, site=admin_site)
class ServicePatternAdmin(admin.ModelAdmin):
    list_display = ('route', 'get_weekday_display', 'window', 'target_departures')
    list_filter = ('weekday', 'route')
    search_fields = ('route__departure_port__name', 'route__destination_port__name')
    autocomplete_fields = ['route']
    list_per_page = 25
    ordering = ('route', 'weekday')
    icon_name = 'clock'
    list_display_links = ('route',)