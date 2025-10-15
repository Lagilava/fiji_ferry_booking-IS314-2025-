# bookings/admin_enhancements.py
"""
Advanced Admin Enhancements for Fiji Ferry System
Provides WebSocket integration, real-time notifications, advanced analytics,
and enhanced admin functionality.
"""
import csv
import json
import asyncio
import uuid
from datetime import datetime, timedelta
from django.contrib import admin
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.urls import path
from django.db import transaction
from django.db.models import Q, Case, When, IntegerField
from django.utils import timezone
from django.core.cache import cache
from django.core.mail import send_mail
from django.conf import settings
from channels.layers import get_channel_layer
from channels.db import database_sync_to_async
from asgiref.sync import async_to_sync
import logging
from .models import (
    Booking, Schedule, Ferry, Payment, Ticket, WeatherCondition,
    MaintenanceLog, Route, Port
)
from accounts.models import User

logger = logging.getLogger(__name__)


class AdminEnhancements:
    """Enhanced admin functionality with real-time features."""

    @staticmethod
    def clear_specific_cache_keys(keys):
        """Clear specific cache keys efficiently."""
        cleared = 0
        for key in keys:
            if cache.delete(key):
                cleared += 1
        logger.info(f"Cleared {cleared} specific cache keys")
        return cleared

    @staticmethod
    @database_sync_to_async
    def get_realtime_bookings():
        """Get real-time booking updates for WebSocket."""
        now = timezone.now()
        bookings = Booking.objects.select_related(
            'user', 'schedule__route__departure_port',
            'schedule__route__destination_port', 'schedule__ferry'
        ).filter(
            booking_date__gte=now - timedelta(hours=2),
            status__in=['confirmed', 'boarding', 'active']
        ).order_by('-booking_date')[:20]

        return [
            {
                'id': b.id,
                'user_email': b.user.email if b.user else b.guest_email or 'Guest',
                'route': f"{b.schedule.route.departure_port.name} → {b.schedule.route.destination_port.name}",
                'ferry': b.schedule.ferry.name,
                'departure': b.schedule.departure_time.isoformat(),
                'status': b.status,
                'total_price': float(b.total_price or 0),
                'passengers': (b.passenger_adults or 0) + (b.passenger_children or 0),
                'timestamp': b.booking_date.isoformat()
            }
            for b in bookings
        ]

    @staticmethod
    @database_sync_to_async
    def get_realtime_schedules():
        """Get real-time schedule updates."""
        now = timezone.now()
        schedules = Schedule.objects.select_related(
            'ferry', 'route__departure_port', 'route__destination_port'
        ).filter(
            departure_time__gte=now - timedelta(hours=1),
            departure_time__lte=now + timedelta(hours=4)
        ).order_by('departure_time')

        return [
            {
                'id': s.id,
                'ferry': s.ferry.name,
                'route': f"{s.route.departure_port.name} → {s.route.destination_port.name}",
                'departure': s.departure_time.isoformat(),
                'arrival': s.arrival_time.isoformat() if s.arrival_time else None,
                'available_seats': s.available_seats or 0,
                'status': s.status,
                'utilization': round(((s.ferry.capacity - (s.available_seats or 0)) / s.ferry.capacity * 100), 1)
            }
            for s in schedules
        ]

    @staticmethod
    @database_sync_to_async
    def get_critical_alerts():
        """Get critical operational alerts."""
        now = timezone.now()
        alerts = []

        # Low availability alerts
        low_seats = Schedule.objects.filter(
            available_seats__lt=5,
            departure_time__gte=now,
            departure_time__lte=now + timedelta(hours=24)
        ).select_related('ferry', 'route__departure_port', 'route__destination_port')

        for s in low_seats:
            alerts.append({
                'type': 'low_availability',
                'severity': 'high',
                'message': f"CRITICAL: Only {s.available_seats} seats left on {s.ferry.name} "
                           f"({s.route.departure_port.name} → {s.route.destination_port.name}) "
                           f"at {s.departure_time.strftime('%H:%M')}",
                'schedule_id': s.id,
                'timestamp': now.isoformat()
            })

        # Delayed schedules
        delayed = Schedule.objects.filter(
            status='delayed',
            departure_time__gte=now - timedelta(hours=2)
        )
        for s in delayed:
            alerts.append({
                'type': 'delay',
                'severity': 'medium',
                'message': f"DELAYED: {s.ferry.name} departure postponed "
                           f"({s.route.departure_port.name} → {s.route.destination_port.name})",
                'schedule_id': s.id,
                'timestamp': now.isoformat()
            })

        # Weather warnings
        weather_warnings = WeatherCondition.objects.filter(
            Q(wind_speed__gt=25) | Q(precipitation_probability__gt=70)
        ).order_by('-updated_at')[:5]

        for w in weather_warnings:
            severity = 'high' if (w.wind_speed and w.wind_speed > 30) else 'medium'
            alerts.append({
                'type': 'weather',
                'severity': severity,
                'message': f"WEATHER ALERT: {w.condition} at {w.port.name} "
                           f"(Wind: {w.wind_speed}km/h, Precip: {w.precipitation_probability}%)",
                'port_id': w.port.id,
                'timestamp': w.updated_at.isoformat()
            })

        return sorted(alerts, key=lambda x: x['severity'], reverse=True)[:10]

    @staticmethod
    @database_sync_to_async
    def get_realtime_payments():
        """Get recent payment updates."""
        recent_payments = Payment.objects.select_related('booking').filter(
            payment_date__gte=timezone.now() - timedelta(minutes=30),
            payment_status='completed'
        ).order_by('-payment_date')[:10]

        return [
            {
                'id': p.id,
                'booking_id': p.booking.id,
                'amount': float(p.amount),
                'method': p.payment_method,
                'timestamp': p.payment_date.isoformat(),
                'status': p.payment_status
            }
            for p in recent_payments
        ]


# WebSocket consumer for admin dashboard
from channels.generic.websocket import AsyncWebsocketConsumer
import json


class AdminDashboardConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time admin dashboard updates."""

    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_anonymous or not self.user.is_staff:
            await self.close()
            return

        self.group_name = 'admin_dashboard'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"Admin WebSocket connected: {self.user.username}")

        # Send initial data
        await self.send_initial_data()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"Admin WebSocket disconnected: {self.user.username}")

    async def send_initial_data(self):
        """Send initial real-time data to connected clients."""
        from .admin import clear_analytics_cache

        data = {
            'type': 'initial_data',
            'bookings': await AdminEnhancements.get_realtime_bookings(),
            'schedules': await AdminEnhancements.get_realtime_schedules(),
            'alerts': await AdminEnhancements.get_critical_alerts(),
            'payments': await AdminEnhancements.get_realtime_payments(),
            'timestamp': timezone.now().isoformat()
        }
        await self.send(text_data=json.dumps(data))

    async def receive(self, text_data):
        """Handle WebSocket messages from admin clients."""
        try:
            data = json.loads(text_data)
            action = data.get('action')

            if action == 'refresh_weather':
                await self.broadcast_weather_update()
            elif action == 'force_cache_clear':
                await self.clear_analytics_cache()
            elif action == 'get_specific_data':
                await self.send_specific_data(data.get('data_type'))

        except Exception as e:
            logger.error(f"WebSocket receive error: {str(e)}")

    async def broadcast_weather_update(self):
        """Broadcast weather updates to all admin clients."""
        weather_data = await AdminEnhancements.get_critical_alerts()
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'weather_update',
                'weather_alerts': weather_data,
                'timestamp': timezone.now().isoformat()
            }
        )

    async def clear_analytics_cache(self):
        """Clear analytics cache and notify clients."""
        from .admin import clear_analytics_cache
        clear_analytics_cache()
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'cache_cleared',
                'message': 'Analytics cache cleared',
                'timestamp': timezone.now().isoformat()
            }
        )

    async def send_specific_data(self, data_type):
        """Send specific data types to client."""
        if data_type == 'bookings':
            data = {'type': 'booking_update', 'data': await AdminEnhancements.get_realtime_bookings()}
        elif data_type == 'schedules':
            data = {'type': 'schedule_update', 'data': await AdminEnhancements.get_realtime_schedules()}
        else:
            data = {'type': 'error', 'message': 'Unknown data type'}

        await self.send(text_data=json.dumps(data))

    async def weather_update(self, event):
        """Handle weather update broadcast."""
        await self.send(text_data=json.dumps({
            'type': 'weather_alerts',
            'weather_alerts': event['weather_alerts'],
            'timestamp': event['timestamp']
        }))

    async def cache_cleared(self, event):
        """Handle cache cleared notification."""
        await self.send(text_data=json.dumps({
            'type': 'cache_cleared',
            'message': event['message'],
            'timestamp': event['timestamp']
        }))


# Real-time notification system
class RealTimeNotifications:
    """Handle real-time notifications for admin users."""

    @staticmethod
    @database_sync_to_async
    def check_for_notifications(user):
        """Check for notifications relevant to specific admin user."""
        now = timezone.now()
        notifications = []

        # Check for high-priority bookings
        high_value_bookings = Booking.objects.filter(
            total_price__gt=1000,
            booking_date__gte=now - timedelta(hours=1),
            status='confirmed'
        ).count()

        if high_value_bookings > 0:
            notifications.append({
                'type': 'high_value_booking',
                'title': f'{high_value_bookings} High-Value Bookings',
                'message': f'New high-value bookings detected in last hour',
                'severity': 'info',
                'timestamp': now.isoformat(),
                'count': high_value_bookings
            })

        # Check for payment issues
        failed_payments = Payment.objects.filter(
            payment_status='failed',
            payment_date__gte=now - timedelta(hours=1)
        ).count()

        if failed_payments > 0:
            notifications.append({
                'type': 'payment_failed',
                'title': f'{failed_payments} Failed Payments',
                'message': 'Payment processing issues detected',
                'severity': 'warning',
                'timestamp': now.isoformat(),
                'count': failed_payments
            })

        return notifications

    @staticmethod
    async def broadcast_notification(notification):
        """Broadcast notification to all admin clients."""
        channel_layer = get_channel_layer()
        await channel_layer.group_send(
            'admin_dashboard',
            {
                'type': 'admin_notification',
                'notification': notification
            }
        )


# Enhanced analytics endpoints
@require_http_methods(["GET"])
@csrf_exempt
def realtime_dashboard_data(request):
    """Provide real-time dashboard data for WebSocket fallback."""
    data = {
        'bookings': AdminEnhancements.get_realtime_bookings(),
        'schedules': AdminEnhancements.get_realtime_schedules(),
        'alerts': AdminEnhancements.get_critical_alerts(),
        'payments': AdminEnhancements.get_realtime_payments(),
        'timestamp': timezone.now().isoformat()
    }
    return JsonResponse(data)


@require_http_methods(["POST"])
@csrf_exempt
def trigger_cache_refresh(request):
    """Trigger cache refresh via admin action."""
    try:
        from .admin import clear_analytics_cache
        clear_analytics_cache()

        # Broadcast via WebSocket
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'admin_dashboard',
            {
                'type': 'cache_cleared',
                'message': 'Manual cache refresh triggered by admin',
                'timestamp': timezone.now().isoformat()
            }
        )

        return JsonResponse({'status': 'success', 'message': 'Cache refreshed'})
    except Exception as e:
        logger.error(f"Cache refresh error: {str(e)}")
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@require_http_methods(["GET"])
def admin_health_check(request):
    """Admin health check endpoint."""
    from django.db import connection

    # Database connection check
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"

    # Cache status
    cache_status = "healthy" if cache.get('health_check') is not None else "unhealthy"
    cache.set('health_check', 'ok', 60)

    data = {
        'timestamp': timezone.now().isoformat(),
        'database': db_status,
        'cache': cache_status,
        'websocket': 'available' if get_channel_layer() else 'unavailable',
        'memory_usage': 'N/A',  # Could integrate psutil
        'uptime': 'N/A'
    }

    return JsonResponse(data)


# Bulk operations with real-time feedback
@transaction.atomic
def bulk_reschedule_schedules(schedules, new_departure_time):
    """Bulk reschedule schedules with real-time notifications."""
    updated = 0
    for schedule in schedules:
        schedule.departure_time = new_departure_time
        schedule.status = 'rescheduled'
        schedule.save()
        updated += 1

    # Clear cache and notify
    from .admin import clear_analytics_cache
    clear_analytics_cache()

    # WebSocket notification
    notification = {
        'type': 'bulk_operation',
        'title': 'Bulk Reschedule Completed',
        'message': f'{updated} schedules rescheduled successfully',
        'severity': 'success',
        'timestamp': timezone.now().isoformat()
    }

    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)('admin_dashboard', {
        'type': 'admin_notification',
        'notification': notification
    })

    return updated


# Export enhancements
def enhanced_booking_export(format_type='csv', filters=None):
    """Enhanced booking export with advanced filtering and formatting."""
    queryset = Booking.objects.select_related(
        'user', 'schedule__route__departure_port',
        'schedule__route__destination_port', 'schedule__ferry'
    ).prefetch_related('passengers', 'vehicles', 'add_ons', 'payments')

    if filters:
        if filters.get('status'):
            queryset = queryset.filter(status=filters['status'])
        if filters.get('date_from'):
            queryset = queryset.filter(booking_date__gte=filters['date_from'])
        if filters.get('date_to'):
            queryset = queryset.filter(booking_date__lte=filters['date_to'])

    if format_type == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="enhanced_bookings_export.csv"'
        writer = csv.writer(response)
        # Enhanced headers with more fields
        writer.writerow([
            'ID', 'User Email', 'Guest Email', 'Ferry', 'Route', 'Departure',
            'Status', 'Total Price', 'Payment Status', 'Adult Passengers',
            'Child Passengers', 'Vehicle Count', 'AddOns Count', 'Booking Date'
        ])

        for booking in queryset:
            writer.writerow([
                booking.id,
                booking.user.email if booking.user else '',
                booking.guest_email or '',
                booking.schedule.ferry.name if booking.schedule and booking.schedule.ferry else '',
                f"{booking.schedule.route.departure_port.name} → {booking.schedule.route.destination_port.name}" if booking.schedule and booking.schedule.route else '',
                booking.schedule.departure_time.isoformat() if booking.schedule else '',
                booking.status,
                f"{booking.total_price:.2f}" if booking.total_price else '0.00',
                booking.payments.first().payment_status if booking.payments.exists() else 'N/A',
                booking.passenger_adults or 0,
                booking.passenger_children or 0,
                booking.vehicles.count(),
                booking.add_ons.count(),
                booking.booking_date.isoformat() if booking.booking_date else ''
            ])

        return response

    elif format_type == 'json':
        data = []
        for booking in queryset:
            data.append({
                'id': booking.id,
                'user_email': booking.user.email if booking.user else None,
                'guest_email': booking.guest_email,
                'ferry': booking.schedule.ferry.name if booking.schedule and booking.schedule.ferry else None,
                'route': {
                    'departure': booking.schedule.route.departure_port.name if booking.schedule and booking.schedule.route else None,
                    'destination': booking.schedule.route.destination_port.name if booking.schedule and booking.schedule.route else None
                },
                'status': booking.status,
                'total_price': float(booking.total_price or 0),
                'passengers': {
                    'adults': booking.passenger_adults or 0,
                    'children': booking.passenger_children or 0
                }
            })
        response = JsonResponse(data, safe=False)
        response['Content-Disposition'] = 'attachment; filename="enhanced_bookings_export.json"'
        return response


# Admin action enhancements
class EnhancedAdminActions:
    """Enhanced bulk admin actions with real-time feedback."""

    @staticmethod
    def smart_ticket_validation(queryset):
        """Smart ticket validation with QR code generation and status tracking."""
        updated = 0
        now = timezone.now()

        for ticket in queryset:
            modified = False

            if ticket.ticket_status == 'active':
                # Generate QR code if missing
                if not ticket.qr_token:
                    ticket.qr_token = str(uuid.uuid4())
                    modified = True

                # Ensure schedule exists before time checks
                if ticket.booking and ticket.booking.schedule:
                    departure = ticket.booking.schedule.departure_time
                    boarding_window = departure - timedelta(minutes=30)

                    if boarding_window <= now <= departure:
                        if ticket.ticket_status != 'boarding':
                            ticket.ticket_status = 'boarding'
                            modified = True

                    elif now > departure + timedelta(hours=2):
                        if ticket.ticket_status != 'used':
                            ticket.ticket_status = 'used'
                            modified = True

                if modified:
                    ticket.save()
                    updated += 1

        return updated


# URL patterns for enhancements
def get_enhanced_admin_urls():
    """Get URL patterns for enhanced admin functionality."""
    return [
        path('ws/admin/dashboard/', AdminDashboardConsumer.as_asgi()),
        path('realtime-data/', realtime_dashboard_data, name='realtime_data'),
        path('trigger-cache-refresh/', trigger_cache_refresh, name='trigger_cache_refresh'),
        path('health-check/', admin_health_check, name='admin_health_check'),
        path('enhanced-export/<str:format_type>/', enhanced_booking_export, name='enhanced_export'),
    ]


# Integration with existing admin
def integrate_with_admin_site(admin_site):
    """Integrate enhancements with existing admin site."""
    # Add custom URLs
    admin_site.get_urls = lambda: get_enhanced_admin_urls() + admin_site.get_urls()

    # Add real-time notification middleware
    # This would need to be configured in settings.py as well
    logger.info("Enhanced admin features integrated successfully")

    return admin_site


# Signal handlers for real-time updates
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


@receiver([post_save, post_delete], sender=Booking)
@receiver([post_save, post_delete], sender=Payment)
@receiver([post_save, post_delete], sender=Schedule)
def trigger_realtime_updates(sender, instance, **kwargs):
    """Trigger real-time updates when models are modified."""
    if get_channel_layer():
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            'admin_dashboard',
            {
                'type': 'data_update',
                'model': sender.__name__.lower(),
                'action': 'save' if 'post_save' in sender.__class__.__name__.lower() else 'delete',
                'timestamp': timezone.now().isoformat()
            }
        )


# Background task for periodic updates
import asyncio
from django.utils import timezone


async def periodic_admin_updates():
    """Periodic background tasks for admin updates."""
    while True:
        try:
            # Check for new notifications
            channel_layer = get_channel_layer()
            if channel_layer:
                # Broadcast any critical updates
                alerts = await AdminEnhancements.get_critical_alerts()
                if alerts:
                    await channel_layer.group_send(
                        'admin_dashboard',
                        {
                            'type': 'critical_alerts',
                            'alerts': alerts[:3],  # Top 3 critical alerts
                            'timestamp': timezone.now().isoformat()
                        }
                    )

            # Clear old cache entries
            cache.delete_pattern('temp_*')

        except Exception as e:
            logger.error(f"Periodic update error: {str(e)}")

        await asyncio.sleep(300)  # Run every 5 minutes


# Start background tasks
def start_admin_background_tasks():
    """Start background tasks for admin enhancements."""
    loop = asyncio.get_event_loop()
    if loop.is_running():
        asyncio.create_task(periodic_admin_updates())
    else:
        loop.run_until_complete(periodic_admin_updates())


# Export for use in main admin.py
__all__ = [
    'AdminEnhancements', 'AdminDashboardConsumer', 'RealTimeNotifications',
    'realtime_dashboard_data', 'trigger_cache_refresh', 'admin_health_check',
    'enhanced_booking_export', 'get_enhanced_admin_urls', 'integrate_with_admin_site',
    'start_admin_background_tasks'
]