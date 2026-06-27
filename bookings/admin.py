# bookings/admin.py
from django.contrib import admin, messages
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
from django.urls import path, reverse
from django.db.models import Count, Sum, F, Avg, Max, Q
from django.utils import timezone
from django.db.models import ExpressionWrapper, FloatField
from django.db.models.functions import Round, Coalesce, ExtractWeekDay, TruncWeek
from django.core.cache import cache
from datetime import datetime, timedelta
from django.contrib.admin.models import LogEntry
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from django.db import transaction
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import (
    Port, Cargo, Ferry, Route, WeatherCondition, Schedule,
    Booking, Passenger, Vehicle, AddOn, Payment, Ticket, MaintenanceLog, ServicePattern
)
from accounts.models import User
import logging
import json
import csv
from collections import defaultdict
from django.utils.html import format_html
from django.contrib.admin import SimpleListFilter
from django.core.exceptions import ObjectDoesNotExist
import uuid
import re
import asyncio

# Set up logging
logger = logging.getLogger(__name__)


# Admin Enhancements class for database operations
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

        # Delayed bookings
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

    @staticmethod
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
    @transaction.atomic
    def bulk_reschedule_schedules(schedules, new_departure_time):
        """Bulk reschedule bookings with real-time notifications."""
        updated = 0
        for schedule in schedules:
            schedule.departure_time = new_departure_time
            schedule.status = 'rescheduled'
            schedule.save()
            updated += 1

        # Clear cache and notify
        clear_analytics_cache()

        # WebSocket notification
        if get_channel_layer():
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'admin_notification',
                    'notification': {
                        'type': 'bulk_operation',
                        'title': 'Bulk Reschedule Completed',
                        'message': f'{updated} bookings rescheduled successfully',
                        'severity': 'success',
                        'timestamp': timezone.now().isoformat()
                    }
                }
            )

        return updated

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


def clear_analytics_cache():
    """Safely clear analytics cache keys without relying on delete_pattern"""
    try:
        # Try to use delete_pattern if backend supports it (Redis, Memcached)
        cache.delete_pattern('analytics_data_*')
        logger.info("Cache cleared using delete_pattern method")
    except AttributeError:
        # Fallback for LocMemCache - manually clear known keys
        try:
            known_keys = [
                'analytics_data_full',
                'analytics_data_bookings_per_route',
                'analytics_data_ferry_utilization',
                'analytics_data_revenue_over_time',
                'analytics_data_bookings_over_time',
                'analytics_data_payment_status',
                'analytics_data_user_growth',
                'analytics_data_top_customers',
                'analytics_data_recent_bookings',
                'analytics_data_fleet_status',
                'analytics_data_weather_conditions',
                'analytics_data_alerts',
            ]

            # Clear known keys
            cleared_count = 0
            for key in known_keys:
                if cache.delete(key):
                    cleared_count += 1

            # Additional pattern matching for LocMemCache
            try:
                all_keys = list(cache._cache.keys())
                pattern = re.compile(r'^analytics_data_.*')
                for key in all_keys:
                    if isinstance(key, str) and pattern.match(key):
                        if cache.delete(key):
                            cleared_count += 1
                logger.info(f"Manually cleared {cleared_count} analytics cache keys")
            except Exception as e:
                logger.warning(f"Could not perform pattern matching on cache: {str(e)}")

        except Exception as e:
            # Last resort: clear entire cache
            try:
                cache.clear()
                logger.warning("Cleared entire cache due to backend limitations")
            except Exception as clear_error:
                logger.error(f"Failed to clear cache entirely: {str(clear_error)}")
    except Exception as e:
        logger.error(f"Error in clear_analytics_cache: {str(e)}")


# Custom filter for Ticket status
class TicketStatusFilter(SimpleListFilter):
    title = 'Ticket Status'
    parameter_name = 'ticket_status'

    def lookups(self, request, model_admin):
        return (
            ('active', 'Active'),
            ('used', 'Used'),
            ('cancelled', 'Cancelled'),
        )

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(ticket_status=self.value())
        return queryset


# Define custom admin site class with enhanced functionality
class CustomAdminSite(admin.AdminSite):
    site_header = "Fiji Ferry Control Hub"
    site_title = "Fiji Ferry Admin"
    index_title = "Dashboard"

    def export_changelist(self, request, app_label=None, model_name=None):
        """Export selected items from change list"""
        if request.method != 'POST':
            return JsonResponse({'error': 'POST only'}, status=405)

        try:
            ids_str = request.POST.get('ids', '[]')
            ids = json.loads(ids_str)

            if not ids:
                return JsonResponse({'error': 'No items selected'}, status=400)

            from django.apps import apps
            model = apps.get_model(app_label, model_name)

            # Get selected objects
            queryset = model.objects.filter(id__in=ids)

            # Generate CSV
            import csv
            from io import StringIO
            output = StringIO()
            writer = csv.writer(output)

            # Header
            fields = [field.name for field in model._meta.fields if field.name != 'id']
            header = ['ID'] + [model._meta.get_field(f).verbose_name for f in fields]
            writer.writerow(header)

            # Rows
            for obj in queryset:
                row = [obj.id] + [getattr(obj, f, '') for f in fields]
                writer.writerow(row)

            response = HttpResponse(output.getvalue(), content_type='text/csv')
            response[
                'Content-Disposition'] = f'attachment; filename="{model_name}_export_{timezone.now().strftime("%Y%m%d")}.csv"'

            return response

        except Exception as e:
            logger.error(f"Export error: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)

    def get_changelist_context(self, cl):
        """Get safe, serializable context for WebSocket change list"""
        try:
            return {
                'model_name': cl.model._meta.model_name,
                'app_label': cl.model._meta.app_label,
                'verbose_name': str(cl.model._meta.verbose_name),
                'verbose_name_plural': str(cl.opts.verbose_name_plural),
                'list_display': getattr(cl.model_admin, 'list_display', []),
                'search_fields': getattr(cl.model_admin, 'search_fields', []),
                'has_filters': bool(cl.has_filters),
                'result_count': cl.result_count,
                'full_result_count': cl.full_result_count,
                'page_num': cl.page_num,
                'num_pages': cl.paginator.num_pages if cl.paginator else 1,
                'list_filter': getattr(cl.model_admin, 'list_filter', []),
                'date_hierarchy': getattr(cl.model_admin, 'date_hierarchy', None)
            }
        except Exception as e:
            logger.error(f"Error creating changelist context: {str(e)}")
            return {
                'error': str(e),
                'model_name': cl.model._meta.model_name,
                'app_label': cl.model._meta.app_label
            }

    def get_alerts(self, current_time):
        """Generate dynamic alerts for low availability, delays, and maintenance."""
        alerts = AdminEnhancements.get_critical_alerts()
        if not alerts:
            alerts.append({
                'message': f"All systems operational as of {current_time.strftime('%H:%M %d %b %Y')}",
                'link': None
            })
        return alerts

    def get_widget_data(self, request, widget_name):
        """Provide data for Jazzmin dashboard widgets."""
        try:
            now = timezone.now()
            if widget_name == "performance_metrics":
                total_bookings = Booking.objects.filter(status="confirmed").count()
                active_ferries = Ferry.objects.filter(is_active=True).count()
                pending_payments = Payment.objects.filter(payment_status="pending").count()
                data = {
                    "total_bookings": total_bookings,
                    "active_ferries": active_ferries,
                    "pending_payments": pending_payments,
                    "updated_at": now.isoformat()
                }
                logger.info(f"Performance metrics data: {data}")
                return JsonResponse(data)
            elif widget_name == "weather_alerts":
                # Fetch full analytics data to get weather_conditions
                analytics_data = self.analytics_data_view(request)
                weather_data = analytics_data.get('weather_conditions', [])
                data = {
                    "weather_alerts": weather_data,
                    "message": "No weather data available" if not weather_data else None
                }
                logger.info(f"Weather alerts data: {data}")
                return JsonResponse(data)
            elif widget_name == "recent_activity":
                current_time = timezone.now()
                recent_logs = LogEntry.objects.select_related('user', 'content_type').filter(
                    action_time__gte=current_time - timedelta(days=7)
                ).order_by('-action_time')[:10]
                consolidated_activities = defaultdict(
                    lambda: {'count': 0, 'timestamp': None, 'operator': None, 'action': None, 'resource': None})
                for log in recent_logs:
                    action = log.get_change_message()
                    resource = f"{log.content_type} ({log.object_repr})"
                    key = (action, resource)
                    if key in consolidated_activities:
                        consolidated_activities[key]['count'] += 1
                    else:
                        consolidated_activities[key]['count'] = 1
                        consolidated_activities[key]['timestamp'] = log.action_time.isoformat()
                        consolidated_activities[key]['operator'] = log.user.username
                        consolidated_activities[key]['action'] = action
                        consolidated_activities[key]['resource'] = resource
                data = {
                    "recent_activities": [
                        {
                            'timestamp': v['timestamp'],
                            'operator': v['operator'],
                            'action': v['action'],
                            'resource': v['resource'],
                            'count': v['count']
                        }
                        for v in consolidated_activities.values()
                    ]
                }
                logger.info(f"Recent activity data: {data}")
                return JsonResponse(data)
            elif widget_name == "weather_forecast":
                from .views import weather_forecast_view
                return weather_forecast_view(request)
            elif widget_name == "stripe_insights":
                from .views import stripe_insights_view
                return stripe_insights_view(request)
            else:
                logger.error(f"Unknown widget: {widget_name}")
                return JsonResponse({"error": "Unknown widget"}, status=400)
        except Exception as e:
            logger.error(f"Error fetching widget data for {widget_name}: {str(e)}")
            return JsonResponse({"error": str(e)}, status=500)

    def scan_qr_code(self, request):
        """Validate QR code and update ticket status."""
        try:
            if request.method != 'POST':
                logger.error("Invalid request method for QR scan: %s", request.method)
                return JsonResponse({"error": "Only POST method allowed"}, status=405)

            data = json.loads(request.body)
            qr_token = data.get('qr_token')
            new_status = data.get('ticket_status')

            if not qr_token:
                logger.warning("No QR token provided in request")
                return JsonResponse({"error": "QR token is required"}, status=400)

            # Extract token from full URL if needed
            if qr_token.startswith('http'):
                parts = qr_token.split('/view_ticket/')
                if len(parts) > 1:
                    qr_token = parts[1].split('/')[0].rstrip('/')
                    logger.info("Extracted QR token from URL: %s", qr_token)
                else:
                    logger.warning("Invalid QR code URL format: %s", qr_token)
                    return JsonResponse({"error": "Invalid QR code URL format"}, status=400)

            # Find ticket by QR token
            ticket = Ticket.objects.select_related(
                'booking__schedule__route__departure_port',
                'booking__schedule__route__destination_port',
                'passenger'
            ).filter(qr_token=qr_token).first()

            if not ticket:
                logger.warning("Ticket not found for QR token: %s", qr_token)
                return JsonResponse({"error": "Invalid QR code - ticket not found"}, status=404)

            # Prepare base response data with robust checks
            route_info = 'N/A'
            booking_date = None
            booking_id = None
            passenger_name = 'N/A'

            if ticket.booking:
                booking_id = ticket.booking.id
                if ticket.booking.schedule and ticket.booking.schedule.route:
                    route = ticket.booking.schedule.route
                    if route.departure_port and route.destination_port:
                        route_info = f"{route.departure_port.name} to {route.destination_port.name}"
                if ticket.booking.booking_date:
                    booking_date = ticket.booking.booking_date.isoformat()

            if ticket.passenger:
                passenger_name = f"{ticket.passenger.first_name} {ticket.passenger.last_name}".strip() or 'N/A'

            response_data = {
                'ticket_id': ticket.id,
                'booking_id': booking_id,
                'passenger': passenger_name,
                'route': route_info,
                'booking_date': booking_date,
                'status': ticket.ticket_status,
            }

            # Update status if requested and valid
            if new_status:
                valid_statuses = ['active', 'used', 'cancelled']
                if new_status not in valid_statuses:
                    logger.warning("Invalid ticket status requested: %s", new_status)
                    return JsonResponse({"error": f"Invalid ticket status: {new_status}"}, status=400)

                try:
                    with transaction.atomic():
                        old_status = ticket.ticket_status
                        ticket.ticket_status = new_status
                        ticket.save()
                        response_data['status'] = new_status

                        # SAFE CACHE CLEARING
                        clear_analytics_cache()

                        # WebSocket notification
                        if get_channel_layer():
                            channel_layer = get_channel_layer()
                            async_to_sync(channel_layer.group_send)(
                                'admin_dashboard',
                                {
                                    'type': 'ticket_update',
                                    'ticket_id': ticket.id,
                                    'old_status': old_status,
                                    'new_status': new_status,
                                    'timestamp': timezone.now().isoformat()
                                }
                            )

                        logger.info(
                            "Ticket %s status changed from %s to %s by %s",
                            ticket.id, old_status, new_status, request.user.username
                        )
                except Exception as e:
                    logger.error("Error updating ticket %s status to %s: %s", ticket.id, new_status, str(e))
                    return JsonResponse({"error": f"Failed to update ticket status: {str(e)}"}, status=500)

            logger.info("QR code validated successfully for ticket %s", ticket.id)
            return JsonResponse(response_data)

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in request body: %s", str(e))
            return JsonResponse({"error": "Invalid JSON data"}, status=400)
        except Exception as e:
            logger.error("Error processing QR scan: %s", str(e), exc_info=True)
            return JsonResponse({"error": f"Server error: {str(e)}"}, status=500)

    def bulk_reschedule_view(self, request):
        """Bulk reschedule bookings via AJAX."""
        if request.method != 'POST':
            return JsonResponse({'error': 'POST required'}, status=405)

        try:
            data = json.loads(request.body)
            schedule_ids = data.get('schedule_ids', [])
            new_departure_time_str = data.get('new_departure_time')

            if not schedule_ids or not new_departure_time_str:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Schedule IDs and new departure time required'
                }, status=400)

            # Parse datetime
            try:
                new_departure_time = datetime.fromisoformat(new_departure_time_str)
            except ValueError:
                return JsonResponse({
                    'status': 'error',
                    'message': 'Invalid datetime format'
                }, status=400)

            schedules = Schedule.objects.filter(id__in=schedule_ids)
            updated_count = AdminEnhancements.bulk_reschedule_schedules(schedules, new_departure_time)

            logger.info(f"Bulk rescheduled {updated_count} bookings")
            return JsonResponse({
                'status': 'success',
                'message': f'Successfully rescheduled {updated_count} bookings',
                'updated_count': updated_count
            })

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Bulk reschedule error: {str(e)}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    def realtime_dashboard_data(self, request):
        """Real-time dashboard data endpoint."""
        try:
            data = {
                'bookings': AdminEnhancements.get_realtime_bookings(),
                'bookings': AdminEnhancements.get_realtime_schedules(),
                'alerts': AdminEnhancements.get_critical_alerts(),
                'payments': AdminEnhancements.get_realtime_payments(),
                'notifications': AdminEnhancements.check_for_notifications(request.user),
                'timestamp': timezone.now().isoformat()
            }
            return JsonResponse(data)
        except Exception as e:
            logger.error(f"Realtime data error: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)

    def trigger_cache_refresh(self, request):
        """Trigger cache refresh via admin action."""
        try:
            clear_analytics_cache()

            # WebSocket notification
            if get_channel_layer():
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

    def admin_health_check(self, request):
        """Admin health check endpoint."""
        from django.db import connection

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            db_status = "healthy"
        except Exception as e:
            db_status = f"unhealthy: {str(e)}"

        cache_status = "healthy" if cache.get('health_check') is not None else "unhealthy"
        cache.set('health_check', 'ok', 60)

        data = {
            'timestamp': timezone.now().isoformat(),
            'database': db_status,
            'cache': cache_status,
            'websocket': 'available' if get_channel_layer() else 'unavailable',
        }
        return JsonResponse(data)

    def enhanced_booking_export(self, request, format_type='csv'):
        """Enhanced booking export with filtering."""
        try:
            filters = request.GET.get('filters')
            filter_dict = json.loads(filters) if filters else {}

            queryset = Booking.objects.select_related(
                'user', 'schedule__route__departure_port',
                'schedule__route__destination_port', 'schedule__ferry'
            ).prefetch_related('passengers', 'vehicles', 'add_ons', 'payments')

            if filter_dict.get('status'):
                queryset = queryset.filter(status=filter_dict['status'])
            if filter_dict.get('date_from'):
                queryset = queryset.filter(booking_date__gte=filter_dict['date_from'])
            if filter_dict.get('date_to'):
                queryset = queryset.filter(booking_date__lte=filter_dict['date_to'])

            if format_type == 'csv':
                def generate_rows():
                    yield ['ID', 'User Email', 'Route', 'Ferry', 'Status', 'Total Price',
                           'Payment Status', 'Adults', 'Children', 'Booking Date']
                    for booking in queryset:
                        yield [
                            booking.id,
                            booking.user.email if booking.user else booking.guest_email or '',
                            f"{booking.schedule.route.departure_port.name} → {booking.schedule.route.destination_port.name}" if booking.schedule and booking.schedule.route else '',
                            booking.schedule.ferry.name if booking.schedule and booking.schedule.ferry else '',
                            booking.status,
                            f"{float(booking.total_price or 0):.2f}",
                            booking.payments.first().payment_status if booking.payments.exists() else 'N/A',
                            booking.passenger_adults or 0,
                            booking.passenger_children or 0,
                            booking.booking_date.isoformat() if booking.booking_date else ''
                        ]

                def csv_generator():
                    pseudo_buffer = (row for row in generate_rows())
                    writer = csv.writer(pseudo_buffer)
                    for row in pseudo_buffer:
                        yield writer.writerow(row)

                response = StreamingHttpResponse(
                    csv_generator(), content_type='text/csv'
                )
                response['Content-Disposition'] = 'attachment; filename="enhanced_bookings_export.csv"'
                clear_analytics_cache()
                return response

            elif format_type == 'json':
                data = []
                for booking in queryset:
                    data.append({
                        'id': booking.id,
                        'user_email': booking.user.email if booking.user else None,
                        'route': {
                            'departure': booking.schedule.route.departure_port.name if booking.schedule and booking.schedule.route else None,
                            'destination': booking.schedule.route.destination_port.name if booking.schedule and booking.schedule.route else None
                        },
                        'status': booking.status,
                        'total_price': float(booking.total_price or 0),
                    })
                response = JsonResponse(data, safe=False)
                response['Content-Disposition'] = 'attachment; filename="enhanced_bookings_export.json"'
                return response

        except Exception as e:
            logger.error(f"Enhanced export error: {str(e)}")
            return JsonResponse({'error': str(e)}, status=500)

    def analytics_data_view(self, request):
        """Provide analytics data for charts and widgets."""
        days = request.GET.get('days', '30')
        chart_type = request.GET.get('chart_type', None)
        cache_key = f'analytics_data_{chart_type or "full"}_{days}'
        data = cache.get(cache_key)
        if data:
            logger.debug(f"Cache hit for analytics_data: {cache_key}")
            return JsonResponse(data)

        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=int(days)) if days != 'all' else None
        current_time = timezone.now()

        logger.info(
            f"Fetching analytics data for chart {chart_type} with days: {days}, start_date: {start_date}, end_date: {end_date}")

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
                                         ] or [{'route': 'No Data', 'count': 0, 'route_type': 'standard'}]
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
            data['ferry_utilization'] = [
                                            {
                                                'ferry': item['ferry__name'] or 'Unknown Ferry',
                                                'utilization': float(item['utilization'] or 0),
                                                'day_of_week':
                                                    ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
                                                     'Saturday'][item['week_day'] - 1]
                                            }
                                            for item in schedules
                                        ] or [{'ferry': 'No Data', 'utilization': 0, 'day_of_week': 'Monday'}]
            logger.debug(f"Ferry utilization data: {data['ferry_utilization']}")

        if chart_type in [None, 'revenue_over_time']:
            revenue_data = (
                Booking.objects.filter(booking_date__date__gte=start_date, booking_date__date__lte=end_date)
                if start_date else Booking.objects.all()
            )
            if days == 'all':
                revenue_data = revenue_data.annotate(
                    week=TruncWeek('booking_date__date')
                ).values('week').annotate(total_revenue=Sum('total_price')).order_by('week')
                data['revenue_over_time'] = [
                                                {'date': item['week'].strftime('%Y-%m-%d'),
                                                 'revenue': float(item['total_revenue'] or 0)}
                                                for item in revenue_data
                                            ] or [{'date': end_date.strftime('%Y-%m-%d'), 'revenue': 0}]
            else:
                revenue_data = revenue_data.values('booking_date__date').annotate(
                    total_revenue=Sum('total_price')).order_by('booking_date__date')
                data['revenue_over_time'] = [
                                                {'date': item['booking_date__date'].strftime('%Y-%m-%d'),
                                                 'revenue': float(item['total_revenue'] or 0)}
                                                for item in revenue_data
                                            ] or [{'date': end_date.strftime('%Y-%m-%d'), 'revenue': 0}]
            logger.debug(f"Revenue over time data: {data['revenue_over_time']}")

        if chart_type in [None, 'bookings_over_time']:
            bookings_over_time = (
                Booking.objects.filter(booking_date__date__gte=start_date, booking_date__date__lte=end_date)
                if start_date else Booking.objects.all()
            )
            if days == 'all':
                bookings_over_time = bookings_over_time.annotate(
                    week=TruncWeek('booking_date__date')
                ).values('week').annotate(count=Count('id')).order_by('week')
                data['bookings_over_time'] = [
                                                 {'date': item['week'].strftime('%Y-%m-%d'), 'count': item['count']}
                                                 for item in bookings_over_time
                                             ] or [{'date': end_date.strftime('%Y-%m-%d'), 'count': 0}]
            else:
                bookings_over_time = bookings_over_time.values('booking_date__date').annotate(
                    count=Count('id')).order_by('booking_date__date')
                data['bookings_over_time'] = [
                                                 {'date': item['booking_date__date'].strftime('%Y-%m-%d'),
                                                  'count': item['count']}
                                                 for item in bookings_over_time
                                             ] or [{'date': end_date.strftime('%Y-%m-%d'), 'count': 0}]
            logger.debug(f"Bookings over time data: {data['bookings_over_time']}")

        if chart_type in [None, 'payment_status']:
            payment_status = (
                Payment.objects.filter(payment_date__date__gte=start_date, payment_date__date__lte=end_date)
                if start_date else Payment.objects.all()
            ).values('payment_status').annotate(count=Count('id'), amount=Sum('amount'))
            data['payment_status'] = [
                                         {'status': item['payment_status'].capitalize(), 'count': item['count'],
                                          'amount': float(item['amount'] or 0)}
                                         for item in payment_status
                                     ] or [{'status': 'No Data', 'count': 0, 'amount': 0}]
            logger.debug(f"Payment status data: {data['payment_status']}")

        if chart_type in [None, 'user_growth']:
            user_growth = (
                User.objects.filter(created_at__date__gte=start_date, created_at__date__lte=end_date)
                if start_date else User.objects.all()
            )
            if days == 'all':
                user_growth = user_growth.annotate(
                    week=TruncWeek('created_at__date')
                ).values('week').annotate(count=Count('id')).order_by('week')
                data['user_growth'] = [
                                          {'date': item['week'].strftime('%Y-%m-%d'), 'count': item['count']}
                                          for item in user_growth
                                      ] or [{'date': end_date.strftime('%Y-%m-%d'), 'count': 0}]
            else:
                user_growth = user_growth.values('created_at__date').annotate(count=Count('id')).order_by(
                    'created_at__date')
                data['user_growth'] = [
                                          {'date': item['created_at__date'].strftime('%Y-%m-%d'),
                                           'count': item['count']}
                                          for item in user_growth
                                      ] or [{'date': end_date.strftime('%Y-%m-%d'), 'count': 0}]
            logger.debug(f"User growth data: {data['user_growth']}")

        if chart_type in [None, 'top_customers']:
            top_customers = (
                Booking.objects.filter(booking_date__date__gte=start_date, booking_date__date__lte=end_date)
                if start_date else Booking.objects.all()
            ).values('user__email').annotate(count=Count('id')).order_by('-count')[:5]
            data['top_customers'] = [
                                        {'user': item['user__email'] or 'Guest', 'count': item['count']}
                                        for item in top_customers
                                    ] or [{'user': 'No Data', 'count': 0}]
            logger.debug(f"Top customers data: {data['top_customers']}")

        if chart_type in [None, 'recent_bookings']:
            data['recent_bookings'] = [
                {
                    'id': booking.id,
                    'user_email': booking.user.email if booking.user else booking.guest_email or 'Guest',
                    'route': f"{booking.schedule.route.departure_port.name} to {booking.schedule.route.destination_port.name}" if booking.schedule and booking.schedule.route else 'N/A',
                    'booking_date': booking.booking_date.isoformat() if booking.booking_date else None,
                    'status': booking.status,
                    'total_price': float(booking.total_price) if booking.total_price else 0.0,
                    'passengers': (booking.passenger_adults or 0) + (booking.passenger_children or 0) + (
                            booking.passenger_infants or 0)
                }
                for booking in Booking.objects.select_related('user', 'schedule__route__departure_port',
                                                              'schedule__route__destination_port').order_by(
                    '-booking_date')[:10]
            ]
            logger.debug(f"Recent bookings data: {data['recent_bookings']}")

        if chart_type in [None, 'fleet_status']:
            data['fleet_status'] = [
                {
                    'name': ferry.name,
                    'status': 'Active' if ferry.is_active else 'Inactive',
                    'capacity': ferry.capacity,
                    'last_maintenance': MaintenanceLog.objects.filter(ferry=ferry).order_by(
                        '-maintenance_date').first().maintenance_date.isoformat() if MaintenanceLog.objects.filter(
                        ferry=ferry).exists() else None
                }
                for ferry in Ferry.objects.select_related('home_port').all()[:5]
            ]
            logger.debug(f"Fleet status data: {data['fleet_status']}")

        if chart_type in [None, 'weather_conditions']:
            weather_qs = WeatherCondition.objects.select_related('port').order_by('-updated_at')[:5]

            data['weather_conditions'] = []

            for w in weather_qs:
                try:
                    temperature = float(w.temperature) if w.temperature is not None else None
                except (ValueError, TypeError):
                    temperature = None

                try:
                    wind_speed = float(w.wind_speed) if w.wind_speed is not None else None
                except (ValueError, TypeError):
                    wind_speed = None

                try:
                    precipitation_probability = float(
                        w.precipitation_probability) if w.precipitation_probability is not None else None
                except (ValueError, TypeError):
                    precipitation_probability = None

                # Collect warnings
                warnings = []
                if wind_speed is not None and wind_speed > 30:
                    warnings.append('High Wind')
                if precipitation_probability is not None and precipitation_probability > 70:
                    warnings.append('High Precip')

                data['weather_conditions'].append({
                    'port': getattr(w.port, 'name', 'Unknown'),
                    'condition': w.condition or 'Unknown',
                    'temperature': temperature,
                    'wind_speed': wind_speed,
                    'precipitation_probability': precipitation_probability,
                    'updated_at': w.updated_at.isoformat() if w.updated_at else None,
                    'warning': warnings or None
                })

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

        cache.set(cache_key, data, timeout=300)
        logger.info(f"Cached analytics data: {cache_key}")

        if request.path.endswith('analytics-data/'):
            return JsonResponse(data)
        return data

    def export_bookings(self, request):
        """Export selected bookings as CSV with additional fields."""
        try:
            queryset = Booking.objects.select_related('user', 'schedule__route__departure_port',
                                                      'schedule__route__destination_port').prefetch_related(
                'passengers', 'vehicles', 'add_ons')
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="bookings_export.csv"'
            writer = csv.writer(response)
            writer.writerow([
                'ID', 'User/Guest Email', 'Route', 'Booking Date', 'Status', 'Total Price',
                'Passengers', 'Vehicles', 'Add-Ons'
            ])
            for item in queryset:
                passengers = ", ".join([p.get_full_name() for p in item.passengers.all()]) or 'None'
                vehicles = ", ".join([f"{v.vehicle_type} ({v.license_plate})" for v in item.vehicles.all()]) or 'None'
                add_ons = ", ".join(
                    [f"{a.get_add_on_type_display()} (x{a.quantity})" for a in item.add_ons.all()]) or 'None'
                writer.writerow([
                    item.id,
                    item.user.email if item.user else item.guest_email or 'Guest',
                    f"{item.schedule.route.departure_port} to {item.schedule.route.destination_port}" if item.schedule and item.schedule.route else 'N/A',
                    item.booking_date.strftime('%Y-%m-%d %H:%M') if item.booking_date else 'N/A',
                    item.status,
                    f"{item.total_price:.2f}" if item.total_price else '0.00',
                    passengers,
                    vehicles,
                    add_ons
                ])
            logger.info(f"Exported {queryset.count()} bookings as CSV")
            clear_analytics_cache()
            return response
        except Exception as e:
            logger.error(f"Error exporting bookings: {str(e)}")
            return JsonResponse({"error": str(e)}, status=500)

    def index(self, request, extra_context=None):
        """Custom admin dashboard with analytics and widgets."""
        if extra_context is None:
            extra_context = {}
        current_time = timezone.now()

        # Fetch analytics data
        analytics_data = self.analytics_data_view(request)

        # Performance metrics
        total_bookings = Booking.objects.filter(status='confirmed').count()
        active_ferries = Ferry.objects.filter(is_active=True).count()
        pending_payments = Payment.objects.filter(payment_status='pending').count()
        total_revenue = Booking.objects.aggregate(total=Sum('total_price'))['total'] or 0
        registered_users = User.objects.count()
        average_booking_value = Booking.objects.aggregate(avg=Avg('total_price'))['avg'] or 0

        # Today's stats
        today = current_time.date()
        bookings_today = Booking.objects.filter(booking_date__date=today).count()
        revenue_today = Booking.objects.filter(
            booking_date__date=today, status='confirmed'
        ).aggregate(total=Sum('total_price'))['total'] or 0
        new_users_today = User.objects.filter(created_at__date=today).count()
        pending_bookings_count = Booking.objects.filter(status='pending').count()
        cancelled_today = Booking.objects.filter(booking_date__date=today, status='cancelled').count()

        # Today's departures (next 24 h)
        tomorrow = current_time + timedelta(hours=24)
        today_departures = [
            {
                'id': s.id,
                'ferry': s.ferry.name,
                'route': f"{s.route.departure_port.name} → {s.route.destination_port.name}",
                'departure': s.departure_time.isoformat(),
                'available_seats': s.available_seats,
                'capacity': s.ferry.capacity,
                'status': s.status,
            }
            for s in Schedule.objects.select_related(
                'ferry', 'route__departure_port', 'route__destination_port'
            ).filter(
                departure_time__gte=current_time,
                departure_time__lt=tomorrow,
            ).order_by('departure_time')[:12]
        ]

        # Pending bookings needing attention
        pending_bookings_list = [
            {
                'id': b.id,
                'user': b.user.email if b.user else b.guest_email or 'Guest',
                'route': f"{b.schedule.route.departure_port.name} → {b.schedule.route.destination_port.name}"
                         if b.schedule and b.schedule.route else 'N/A',
                'departure': b.schedule.departure_time.isoformat() if b.schedule else None,
                'total_price': float(b.total_price) if b.total_price else 0.0,
                'booking_date': b.booking_date.isoformat() if b.booking_date else None,
            }
            for b in Booking.objects.select_related(
                'user', 'schedule__route__departure_port', 'schedule__route__destination_port'
            ).filter(status='pending').order_by('-booking_date')[:8]
        ]

        # Recent user registrations
        recent_users = [
            {
                'id': u.id,
                'username': u.username,
                'email': u.email,
                'full_name': f"{u.first_name} {u.last_name}".strip() or u.username,
                'date_joined': u.created_at.isoformat(),
                'booking_count': Booking.objects.filter(user=u).count(),
            }
            for u in User.objects.order_by('-created_at')[:8]
        ]

        # Recent bookings
        recent_bookings = [
            {
                'id': booking.id,
                'user_email': booking.user.email if booking.user else booking.guest_email or 'Guest',
                'route': f"{booking.schedule.route.departure_port.name} to {booking.schedule.route.destination_port.name}" if booking.schedule and booking.schedule.route else 'N/A',
                'booking_date': booking.booking_date.isoformat() if booking.booking_date else None,
                'status': booking.status,
                'total_price': float(booking.total_price) if booking.total_price else 0.0,
                'passengers': (booking.passenger_adults or 0) + (booking.passenger_children or 0) + (
                        booking.passenger_infants or 0)
            }
            for booking in Booking.objects.select_related('user', 'schedule__route__departure_port',
                                                          'schedule__route__destination_port').order_by(
                '-booking_date')[:10]
        ]

        # Recent activities
        recent_logs = LogEntry.objects.select_related('user', 'content_type').filter(
            action_time__gte=current_time - timedelta(days=7)
        ).order_by('-action_time')[:10]
        consolidated_activities = defaultdict(
            lambda: {'count': 0, 'timestamp': None, 'operator': None, 'action': None, 'resource': None})
        for log in recent_logs:
            action = log.get_change_message()
            resource = f"{log.content_type} ({log.object_repr})"
            key = (action, resource)
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
                'last_maintenance': MaintenanceLog.objects.filter(ferry=ferry).order_by(
                    '-maintenance_date').first().maintenance_date.isoformat() if MaintenanceLog.objects.filter(
                    ferry=ferry).exists() else None
            }
            for ferry in Ferry.objects.select_related('home_port').all()[:5]
        ]

        # Weather conditions
        weather_conditions = [
            {
                'port': weather['port__name'],
                'condition': weather['condition'],
                'temperature': float(weather['temperature']) if weather['temperature'] else None,
                'wind_speed': float(weather['wind_speed']) if weather['wind_speed'] else None,
                'precipitation_probability': float(weather['precipitation_probability']) if weather[
                    'precipitation_probability'] else None,
                'updated_at': weather['updated_at'].isoformat()
            }
            for weather in WeatherCondition.objects.values('port__name', 'condition', 'temperature', 'wind_speed',
                                                           'precipitation_probability', 'updated_at').annotate(
                latest=Max('updated_at')).order_by('-updated_at')[:5]
        ]

        # Notifications
        notifications = AdminEnhancements.check_for_notifications(request.user)

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
            'notifications': notifications,
            'total_bookings': total_bookings,
            'active_ferries': active_ferries,
            'pending_payments': pending_payments,
            'total_revenue': round(float(total_revenue), 2),
            'registered_users': registered_users,
            'average_booking_value': round(float(average_booking_value), 2),
            'bookings_today': bookings_today,
            'revenue_today': round(float(revenue_today), 2),
            'new_users_today': new_users_today,
            'pending_bookings_count': pending_bookings_count,
            'cancelled_today': cancelled_today,
            'today_departures': today_departures,
            'pending_bookings_list': pending_bookings_list,
            'recent_users': recent_users,
            'alerts': self.get_alerts(current_time),
            'current_time': current_time.isoformat(),
            'charts_initialized': False
        })
        request.session['charts_initialized'] = False
        return super().index(request, extra_context)

    # ------------------------------------------------------------------ #
    # Agent dashboard — surfaces the offline automation + server monitor
    # daemons (bookings/automation.py, bookings/monitor.py) inside admin.
    # ------------------------------------------------------------------ #
    def _read_json_status(self, filename):
        """Safely read a status JSON file written by an in-process agent."""
        from django.conf import settings
        import os
        path = os.path.join(settings.BASE_DIR, "logs", filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f), None
        except FileNotFoundError:
            return None, "No status recorded yet — the agent has not run in this environment."
        except Exception as e:
            return None, f"Could not read status: {e}"

    def _tail_log(self, filename, lines=40):
        """Return the last N lines of an agent log file."""
        from django.conf import settings
        import os
        path = os.path.join(settings.BASE_DIR, "logs", filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return list(f)[-lines:]
        except Exception:
            return []

    def agent_dashboard_data(self, request):
        """JSON endpoint powering live refresh of the agent dashboard."""
        automation, automation_err = self._read_json_status("automation_status.json")
        monitor, monitor_err = self._read_json_status("server_status.json")
        security, security_err = self._read_json_status("security_status.json")
        return JsonResponse({
            "automation": automation,
            "automation_error": automation_err,
            "monitor": monitor,
            "monitor_error": monitor_err,
            "security": security,
            "security_error": security_err,
            "automation_log": self._tail_log("automation.log", 30),
            "monitor_log": self._tail_log("server_monitor.log", 30),
            "security_log": self._tail_log("security.log", 30),
            "fetched_at": timezone.now().isoformat(),
        })

    def agent_dashboard(self, request):
        """Render the agent monitoring dashboard within the admin shell."""
        from django.template.response import TemplateResponse
        automation, automation_err = self._read_json_status("automation_status.json")
        monitor, monitor_err = self._read_json_status("server_status.json")
        security, security_err = self._read_json_status("security_status.json")
        context = {
            **self.each_context(request),
            "title": "Agent Monitoring",
            "automation": automation,
            "automation_error": automation_err,
            "monitor": monitor,
            "monitor_error": monitor_err,
            "security": security,
            "security_error": security_err,
            "automation_log": self._tail_log("automation.log", 30),
            "monitor_log": self._tail_log("server_monitor.log", 30),
            "security_log": self._tail_log("security.log", 30),
        }
        return TemplateResponse(request, "admin/agent_dashboard.html", context)

    # ------------------------------------------------------------------ #
    # Departure manifest — printable/downloadable boarding list per schedule
    # ------------------------------------------------------------------ #
    def departure_manifest(self, request):
        from django.template.response import TemplateResponse
        schedule_id = request.GET.get('schedule_id', '').strip()
        schedule = None
        bookings = []
        schedules = Schedule.objects.select_related(
            'ferry', 'route__departure_port', 'route__destination_port'
        ).filter(departure_time__gte=timezone.now()).order_by('departure_time')[:60]

        if schedule_id:
            try:
                schedule = Schedule.objects.select_related(
                    'ferry', 'route__departure_port', 'route__destination_port'
                ).get(pk=schedule_id)
                bookings = Booking.objects.filter(
                    schedule=schedule, status='confirmed'
                ).select_related('user').prefetch_related(
                    'passengers', 'vehicles', 'cargo', 'add_ons', 'tickets'
                ).order_by('booking_date')
            except Schedule.DoesNotExist:
                messages.error(request, "Schedule not found.")

        context = {
            **self.each_context(request),
            'title': 'Departure Manifest',
            'schedule': schedule,
            'bookings': bookings,
            'schedules': schedules,
            'total_pax': sum(
                (b.passenger_adults or 0) + (b.passenger_children or 0) + (b.passenger_infants or 0)
                for b in bookings
            ),
            'total_vehicles': sum(b.vehicles.count() for b in bookings),
            'total_cargo': sum(b.cargo.count() for b in bookings),
            'unaccompanied_minors': [b for b in bookings if b.is_unaccompanied_minor],
            'emergency_bookings': [b for b in bookings if b.is_emergency],
        }
        return TemplateResponse(request, 'admin/bookings/departure_manifest.html', context)

    # ------------------------------------------------------------------ #
    # Bulk rebook — move all confirmed bookings from one schedule to another
    # ------------------------------------------------------------------ #
    def bulk_rebook_view(self, request):
        from django.template.response import TemplateResponse
        from bookings import services

        source_id = request.GET.get('schedule_id') or request.POST.get('source_schedule_id', '').strip()
        source = None
        source_bookings = []
        upcoming = Schedule.objects.select_related(
            'ferry', 'route__departure_port', 'route__destination_port'
        ).filter(departure_time__gte=timezone.now()).order_by('departure_time')[:60]

        if source_id:
            try:
                source = Schedule.objects.select_related(
                    'ferry', 'route__departure_port', 'route__destination_port'
                ).get(pk=source_id)
                source_bookings = list(Booking.objects.filter(
                    schedule=source, status='confirmed'
                ).select_related('user'))
            except Schedule.DoesNotExist:
                messages.error(request, "Source schedule not found.")

        if request.method == 'POST' and source:
            target_id = request.POST.get('target_schedule_id', '').strip()
            if not target_id:
                messages.error(request, "Please select a target schedule.")
            else:
                moved, skipped, errors = 0, 0, []
                for booking in source_bookings:
                    try:
                        services.rebook_booking(booking.pk, target_id, moved_by=request.user.email)
                        moved += 1
                    except Exception as e:
                        skipped += 1
                        errors.append(f"Booking {booking.pk}: {e}")
                if moved:
                    messages.success(request, f"{moved} booking(s) reBooked to new schedule.")
                if skipped:
                    messages.warning(request, f"{skipped} failed: " + "; ".join(errors[:3]))
                if moved:
                    from django.http import HttpResponseRedirect
                    return HttpResponseRedirect(
                        reverse('custom_admin:bulk_rebook') + f'?schedule_id={target_id}'
                    )

        context = {
            **self.each_context(request),
            'title': 'Bulk Rebook Passengers',
            'source': source,
            'source_bookings': source_bookings,
            'upcoming_schedules': upcoming,
        }
        return TemplateResponse(request, 'admin/bookings/bulk_rebook.html', context)

    # ------------------------------------------------------------------ #
    # Operations dashboard — failures, flags, stuck payments
    # ------------------------------------------------------------------ #
    def ops_dashboard(self, request):
        from django.template.response import TemplateResponse
        now = timezone.now()

        # Failed / stuck payments
        failed_payments = Payment.objects.filter(
            payment_status='failed'
        ).select_related('booking__user', 'booking__schedule__route__departure_port',
                         'booking__schedule__route__destination_port').order_by('-payment_date')[:30]

        # Pending bookings older than 30 min (stuck in checkout)
        stale_cutoff = now - timedelta(minutes=30)
        stale_pending = Booking.objects.filter(
            status='pending', booking_date__lt=stale_cutoff
        ).select_related('user', 'schedule__route__departure_port',
                         'schedule__route__destination_port').order_by('booking_date')[:30]

        # Unaccompanied minors with upcoming departures
        unaccompanied = Booking.objects.filter(
            is_unaccompanied_minor=True,
            status='confirmed',
            schedule__departure_time__gte=now,
        ).select_related('user', 'schedule__route__departure_port',
                         'schedule__route__destination_port').order_by('schedule__departure_time')[:20]

        # Emergency bookings upcoming
        emergency = Booking.objects.filter(
            is_emergency=True,
            status='confirmed',
            schedule__departure_time__gte=now,
        ).select_related('user', 'schedule__route__departure_port',
                         'schedule__route__destination_port').order_by('schedule__departure_time')[:20]

        # Passengers with unverified documents (pending/rejected) on confirmed upcoming bookings
        from bookings.models import Passenger
        unverified_docs = Passenger.objects.filter(
            verification_status__in=['pending', 'rejected'],
            booking__status='confirmed',
            booking__schedule__departure_time__gte=now,
        ).select_related('booking__user', 'booking__schedule__route__departure_port',
                         'booking__schedule__route__destination_port').order_by(
            'booking__schedule__departure_time')[:30]

        # Schedules with low seat availability (< 10%) departing in next 48 h
        capacity_alerts = []
        for s in Schedule.objects.select_related(
            'ferry', 'route__departure_port', 'route__destination_port'
        ).filter(status='scheduled', departure_time__gte=now,
                 departure_time__lt=now + timedelta(hours=48)):
            if s.ferry.capacity and s.available_seats / s.ferry.capacity < 0.10:
                capacity_alerts.append(s)

        # Cancellations in last 24 h with refund amounts
        cancelled_24h = Booking.objects.filter(
            status='cancelled',
            booking_date__gte=now - timedelta(hours=24),
        ).select_related('user', 'schedule').order_by('-booking_date')[:20]

        # ── Schedule operational risks (Layer D: Needs Attention) ──
        from bookings import scheduling
        weather_holds = list(
            Schedule.objects.filter(status='weather_hold', departure_time__gt=now)
            .select_related('ferry', 'route__departure_port', 'route__destination_port')
            .order_by('departure_time')[:50]
        )
        maintenance_conflicts = scheduling.upcoming_maintenance_conflicts()
        overlap_conflicts = scheduling.upcoming_overlap_conflicts()
        stale_weather = scheduling.routes_with_stale_weather()

        context = {
            **self.each_context(request),
            'title': 'Operations Dashboard',
            'failed_payments': failed_payments,
            'stale_pending': stale_pending,
            'unaccompanied': unaccompanied,
            'emergency': emergency,
            'unverified_docs': unverified_docs,
            'capacity_alerts': capacity_alerts,
            'cancelled_24h': cancelled_24h,
            'weather_holds': weather_holds,
            'maintenance_conflicts': maintenance_conflicts,
            'overlap_conflicts': overlap_conflicts,
            'stale_weather': stale_weather,
        }
        return TemplateResponse(request, 'admin/bookings/ops_dashboard.html', context)

    # ------------------------------------------------------------------ #
    # Schedule action — staff decision on a flagged sailing
    # ------------------------------------------------------------------ #
    def schedule_action(self, request):
        from django.http import HttpResponseRedirect
        redirect = HttpResponseRedirect(reverse('custom_admin:ops_dashboard'))
        if request.method != 'POST':
            return redirect

        sid = request.POST.get('schedule_id', '').strip()
        action = request.POST.get('action', '').strip()
        try:
            schedule = Schedule.objects.get(pk=int(sid))
        except (ValueError, Schedule.DoesNotExist):
            messages.error(request, "Schedule not found.")
            return redirect

        label = f"{schedule.ferry.name} — {schedule.route} ({schedule.departure_time:%b %d %H:%M})"
        if action == 'release':
            if schedule.status == 'weather_hold':
                schedule.status = 'scheduled'
                schedule.save(update_fields=['status', 'last_updated'])
                messages.success(request, f"Released to Scheduled: {label}")
            else:
                messages.info(request, f"Schedule is not on weather hold: {label}")
        elif action == 'cancel':
            schedule.status = 'cancelled'
            schedule.save(update_fields=['status', 'last_updated'])
            messages.warning(request, f"Cancelled: {label}")
        else:
            messages.error(request, "Unknown action.")
        clear_analytics_cache()
        return redirect

    # ------------------------------------------------------------------ #
    # Manual confirm — staff override for stuck/cash payments
    # ------------------------------------------------------------------ #
    def manual_confirm_view(self, request):
        from bookings import services
        from django.http import HttpResponseRedirect

        if request.method != 'POST':
            return HttpResponseRedirect(reverse('custom_admin:ops_dashboard'))

        booking_id = request.POST.get('booking_id', '').strip()
        reference = request.POST.get('reference', '').strip()
        if not booking_id:
            messages.error(request, "No booking ID provided.")
            return HttpResponseRedirect(reverse('custom_admin:ops_dashboard'))

        try:
            booking, changed = services.manually_confirm_booking(
                int(booking_id),
                confirmed_by=request.user.email,
                reference=reference,
            )
            if changed:
                messages.success(
                    request,
                    f"Booking #{booking_id} manually confirmed. Payment record created (ref: {reference or 'manual'})."
                )
            else:
                messages.info(request, f"Booking #{booking_id} was already confirmed.")
        except Exception as e:
            messages.error(request, f"Could not confirm booking #{booking_id}: {e}")

        return HttpResponseRedirect(reverse('custom_admin:ops_dashboard'))

    def get_urls(self):
        """Enhanced URL patterns including bulk operations and real-time endpoints."""
        urls = super().get_urls()
        custom_urls = [
            path('agents/', self.admin_view(self.agent_dashboard), name='agent_dashboard'),
            path('agents/data/', self.admin_view(self.agent_dashboard_data), name='agent_dashboard_data'),
            path('analytics-data/', self.admin_view(self.analytics_data_view), name='analytics-data'),
            path('widget-data/<str:widget_name>/', self.admin_view(self.get_widget_data), name='widget-data'),
            path('export-bookings/', self.admin_view(self.export_bookings), name='export-bookings'),
            path('scan-qr-code/', self.admin_view(self.scan_qr_code), name='scan_qr_code'),
            path('realtime-data/', self.admin_view(self.realtime_dashboard_data), name='realtime_data'),
            path('bulk-reschedule/', self.admin_view(self.bulk_reschedule_view), name='bulk_reschedule'),
            path('trigger-cache-refresh/', self.admin_view(self.trigger_cache_refresh), name='trigger_cache_refresh'),
            path('health-check/', self.admin_view(self.admin_health_check), name='admin_health_check'),
            path('enhanced-export/<str:format_type>/', self.admin_view(self.enhanced_booking_export),
                 name='enhanced_export'),
            path('<str:app_label>/<str:model_name>/export/', self.admin_view(self.export_changelist),
                 name='export_changelist'),
            # New operational tools
            path('manifest/', self.admin_view(self.departure_manifest), name='departure_manifest'),
            path('bulk-rebook/', self.admin_view(self.bulk_rebook_view), name='bulk_rebook'),
            path('ops/', self.admin_view(self.ops_dashboard), name='ops_dashboard'),
            path('manual-confirm/', self.admin_view(self.manual_confirm_view), name='manual_confirm'),
            path('schedule-action/', self.admin_view(self.schedule_action), name='schedule_action'),
        ]
        return custom_urls + urls


# Instantiate custom admin site
admin_site = CustomAdminSite(name='custom_admin')


# Inline classes for BookingAdmin
class PassengerInline(admin.TabularInline):
    model = Passenger
    extra = 1
    autocomplete_fields = ['linked_adult']
    fields = ('first_name', 'last_name', 'passenger_type', 'age', 'date_of_birth', 'linked_adult')
    readonly_fields = ('age', 'date_of_birth')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('linked_adult')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()


class VehicleInline(admin.TabularInline):
    model = Vehicle
    extra = 0
    fields = ('vehicle_type', 'dimensions', 'license_plate', 'price')
    readonly_fields = ('price',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()

class CargoInline(admin.TabularInline):
    model = Cargo
    extra = 0
    fields = ('cargo_type', 'weight_kg', 'dimensions_cm', 'license_plate')
    verbose_name = "Cargo"
    verbose_name_plural = "Cargo"

class AddOnInline(admin.TabularInline):
    model = AddOn
    extra = 0
    fields = ('add_on_type', 'quantity', 'price')
    readonly_fields = ('price',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()


class EnhancedModelAdmin(admin.ModelAdmin):
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/json/', self.admin_site.admin_view(self.json_view),
                 name=f'{self.model._meta.model_name}_json'),
        ]
        return custom_urls + urls

    def json_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if obj is None:
            return JsonResponse({'exists': False, 'matches_filters': False})

        cl = self.get_changelist_instance(request)
        queryset = cl.get_queryset(request)
        matches_filters = queryset.filter(pk=object_id).exists()

        data = {
            'exists': True,
            'matches_filters': matches_filters,
        }
        return JsonResponse(data)


# Register models with custom admin site
@admin.register(Port, site=admin_site)
class PortAdmin(EnhancedModelAdmin):
    list_display = ('name', 'lat', 'lng', 'operating_hours_start', 'operating_hours_end', 'berths')
    list_filter = ('tide_sensitive', 'night_ops_allowed')
    search_fields = ('name',)
    list_per_page = 25
    ordering = ('name',)
    list_display_links = ('name',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()
        logger.info("Cache invalidated after Port update")


@admin.register(Cargo, site=admin_site)
class CargoAdmin(EnhancedModelAdmin):
    list_display = ('booking', 'cargo_type', 'weight_kg', 'dimensions_cm', 'license_plate', 'price')
    list_filter = ('cargo_type',)
    search_fields = ('cargo_type', 'license_plate')
    autocomplete_fields = ['booking']
    list_per_page = 25
    ordering = ('booking__booking_date',)
    list_display_links = ('booking',)
    fieldsets = (
        ('General Info', {'fields': ('booking', 'cargo_type')}),
        ('Details', {'fields': ('weight_kg', 'dimensions_cm', 'license_plate', 'price')}),
    )
    readonly_fields = ('price',)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()
        logger.info("Cache invalidated after Cargo update")


@admin.register(Ferry, site=admin_site)
class FerryAdmin(EnhancedModelAdmin):
    list_display = ('name', 'operator', 'capacity', 'is_active', 'home_port', 'cruise_speed_knots')
    list_filter = ('is_active', 'home_port')
    search_fields = ('name', 'operator')
    autocomplete_fields = ['home_port']
    list_editable = ('is_active',)
    list_per_page = 25
    ordering = ('name',)
    list_display_links = ('name',)
    fieldsets = (
        ('General Info', {'fields': ('name', 'operator', 'home_port')}),
        ('Specifications', {'fields': ('capacity', 'cruise_speed_knots')}),
        ('Status', {'fields': ('is_active',)}),
    )
    actions = ['activate_ferries', 'deactivate_ferries']

    @admin.action(description="✅ Activate selected ferries")
    def activate_ferries(self, request, queryset):
        updated = queryset.update(is_active=True)
        clear_analytics_cache()
        self.message_user(request, f"{updated} ferry(ies) activated.", messages.SUCCESS)

    @admin.action(description="🛑 Deactivate selected ferries")
    def deactivate_ferries(self, request, queryset):
        updated = queryset.update(is_active=False)
        clear_analytics_cache()
        self.message_user(request, f"{updated} ferry(ies) deactivated.", messages.WARNING)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()
        logger.info("Cache invalidated after Ferry update")


@admin.register(Route, site=admin_site)
class RouteAdmin(EnhancedModelAdmin):
    list_display = ('departure_port', 'destination_port', 'distance_km', 'estimated_duration', 'base_fare',
                    'service_tier')
    list_filter = ('service_tier', 'departure_port', 'destination_port')
    search_fields = ('departure_port__name', 'destination_port__name')
    autocomplete_fields = ['departure_port', 'destination_port']
    list_per_page = 25
    ordering = ('departure_port', 'destination_port')
    list_display_links = ('departure_port', 'destination_port')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()
        logger.info("Cache invalidated after Route update")


@admin.register(WeatherCondition, site=admin_site)
class WeatherConditionAdmin(EnhancedModelAdmin):
    list_display = ('route', 'port', 'temperature', 'wind_speed', 'precipitation_probability', 'condition',
                    'updated_at')
    list_filter = ('condition', 'port')
    search_fields = ('route__departure_port__name', 'route__destination_port__name', 'port__name')
    autocomplete_fields = ['route', 'port']
    list_per_page = 25
    ordering = ('-updated_at',)
    list_display_links = ('route', 'port')
    actions = ['delete_expired']

    @admin.action(description="🗑️ Delete expired weather entries")
    def delete_expired(self, request, queryset):
        expired = queryset.filter(expires_at__lt=timezone.now())
        count = expired.count()
        expired.delete()
        clear_analytics_cache()
        self.message_user(request, f"Deleted {count} expired weather entry(ies).", messages.SUCCESS)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()

        # WebSocket notification for weather updates
        if get_channel_layer():
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'weather_alerts',
                    'weather_alerts': AdminEnhancements.get_critical_alerts(),
                    'timestamp': timezone.now().isoformat()
                }
            )
        logger.info("Cache invalidated after WeatherCondition update")


@admin.register(Schedule, site=admin_site)
class ScheduleAdmin(EnhancedModelAdmin):
    list_display = ('ferry', 'route', 'departure_time', 'arrival_time', 'available_seats', 'status', 'real_time_status',
                    'operational_day')
    list_filter = ('status', 'ferry', 'route', 'operational_day')
    search_fields = ('ferry__name', 'route__departure_port__name', 'route__destination_port__name')
    date_hierarchy = 'departure_time'
    autocomplete_fields = ['ferry', 'route']
    list_editable = ('status',)
    list_per_page = 25
    ordering = ('departure_time',)
    list_display_links = ('ferry', 'route')
    fieldsets = (
        ('Schedule Info', {'fields': ('ferry', 'route', 'departure_time', 'arrival_time'), 'classes': ('collapse',)}),
        ('Details', {'fields': ('available_seats', 'status', 'operational_day'), 'classes': ('collapse',)}),
    )

    def real_time_status(self, obj):
        if obj.status == 'weather_hold':
            return format_html('<span style="color:#b91c1c;font-weight:600">⚠ Weather Hold — needs review</span>')
        weather = WeatherCondition.objects.filter(route=obj.route).order_by('-updated_at').first()
        if weather:
            if weather.wind_speed and weather.wind_speed > 20:
                return format_html('<span style="color:#b91c1c">At Risk (High Wind: {} km/h)</span>',
                                   round(float(weather.wind_speed), 1))
            if weather.precipitation_probability and weather.precipitation_probability > 50:
                return format_html('<span style="color:#b91c1c">At Risk (High Precip: {}%)</span>',
                                   round(float(weather.precipitation_probability), 0))
        maintenance = MaintenanceLog.objects.filter(ferry=obj.ferry, completed_at__isnull=True).exists()
        if maintenance:
            return format_html('<span style="color:#b91c1c">Maintenance Pending</span>')
        return format_html('<span style="color:#26a69a">{}</span>', obj.status.capitalize())

    real_time_status.short_description = "Real-Time Status"

    actions = ['mark_scheduled', 'mark_delayed', 'mark_cancelled',
               'release_weather_hold', 'duplicate_next_day']

    def _broadcast_schedule(self, obj):
        if get_channel_layer():
            async_to_sync(get_channel_layer().group_send)(
                'admin_dashboard',
                {
                    'type': 'schedule_update',
                    'schedule_id': obj.id,
                    'status': obj.status,
                    'available_seats': obj.available_seats,
                    'timestamp': timezone.now().isoformat()
                }
            )

    def _set_status(self, request, queryset, status, label, level=messages.SUCCESS):
        count = 0
        for schedule in queryset:
            schedule.status = status
            schedule.save(update_fields=['status', 'last_updated'])
            self._broadcast_schedule(schedule)
            count += 1
        clear_analytics_cache()
        self.message_user(request, f"{count} schedule(s) marked {label}.", level)

    @admin.action(description="🟢 Mark selected as Scheduled")
    def mark_scheduled(self, request, queryset):
        self._set_status(request, queryset, 'scheduled', 'scheduled')

    @admin.action(description="🟠 Mark selected as Delayed")
    def mark_delayed(self, request, queryset):
        self._set_status(request, queryset, 'delayed', 'delayed', messages.WARNING)

    @admin.action(description="🔴 Mark selected as Cancelled")
    def mark_cancelled(self, request, queryset):
        self._set_status(request, queryset, 'cancelled', 'cancelled', messages.WARNING)

    @admin.action(description="✅ Release weather hold (back to Scheduled)")
    def release_weather_hold(self, request, queryset):
        held = queryset.filter(status='weather_hold')
        count = held.count()
        self._set_status(request, held, 'scheduled', 'scheduled (weather hold released)')
        if not count:
            self.message_user(request, "No selected schedules were on weather hold.",
                              messages.INFO)

    @admin.action(description="📅 Duplicate for next day (same time)")
    def duplicate_next_day(self, request, queryset):
        created = 0
        for s in queryset:
            Schedule.objects.create(
                ferry=s.ferry, route=s.route,
                departure_time=s.departure_time + timedelta(days=1),
                arrival_time=s.arrival_time + timedelta(days=1),
                estimated_duration=s.estimated_duration,
                available_seats=s.ferry.capacity,
                status='scheduled',
                operational_day=s.operational_day + timedelta(days=1),
                created_by_auto=True,
            )
            created += 1
        clear_analytics_cache()
        self.message_user(request, f"Created {created} schedule(s) for the next day.", messages.SUCCESS)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()

        # WebSocket notification for schedule updates
        self._broadcast_schedule(obj)
        logger.info("Cache invalidated after Schedule update")


@admin.register(Booking, site=admin_site)
class BookingAdmin(EnhancedModelAdmin):
    list_display = (
        'id', 'user_email', 'schedule', 'booking_date', 'passenger_adults',
        'passenger_children', 'passenger_infants', 'total_price', 'status'
    )
    list_filter = ('status', 'schedule__route', 'booking_date')
    search_fields = (
        'user__email', 'guest_email', 'schedule__ferry__name',
        'passengers__first_name', 'passengers__last_name',
        'cargo__cargo_type', 'cargo__license_plate'
    )
    autocomplete_fields = ['user', 'schedule']
    date_hierarchy = 'booking_date'
    # Status is intentionally NOT list-editable and is read-only on the form:
    # changing a booking's status must go through the Confirm/Cancel actions so
    # the service layer can release seats, issue refunds, update tickets, and
    # reject illegal transitions. Free-form status edits would silently break
    # seat inventory and could oversell.
    list_per_page = 25
    ordering = ('-booking_date',)
    list_display_links = ('id', 'user_email')
    readonly_fields = ('total_price', 'booking_date', 'status')

    # INLINES — CARGO INLINE ADDED
    inlines = [PassengerInline, VehicleInline, CargoInline, AddOnInline]

    fieldsets = (
        ('General Info', {
            'fields': ('user', 'guest_email', 'schedule', 'booking_date'),
            'classes': ('collapse',)
        }),
        ('Number of Passengers', {
            'fields': ('passenger_adults', 'passenger_children', 'passenger_infants'),
            'classes': ('collapse',)
        }),
        ('Status and Pricing', {
            'fields': ('status', 'total_price')
        }),
    )

    actions = [
        'confirm_bookings', 'cancel_bookings',
        'action_manual_confirm', 'export_bookings',
        'mark_tickets_used', 'mark_tickets_unused',
    ]

    @admin.action(description="✅ Confirm selected bookings")
    def confirm_bookings(self, request, queryset):
        from bookings import services
        confirmed, skipped = 0, 0
        for booking in queryset:
            try:
                services.transition_booking(booking, services.BookingStatus.CONFIRMED)
                confirmed += 1
            except services.InvalidTransition:
                skipped += 1
        clear_analytics_cache()
        msg = f"{confirmed} booking(s) confirmed."
        if skipped:
            msg += f" {skipped} skipped (already cancelled/invalid)."
        self.message_user(request, msg, messages.SUCCESS if confirmed else messages.WARNING)

    def changelist_view(self, request, extra_context=None):
        """Override to add WebSocket context"""
        response = super().changelist_view(request, extra_context)

        if extra_context is None:
            extra_context = {}

        try:
            from django.template.response import TemplateResponse
            if isinstance(response, TemplateResponse):
                cl = response.context_data.get('cl')
                if cl:
                    websocket_context = admin_site.get_changelist_context(cl)
                    extra_context['websocket_cl_data'] = websocket_context
                    response.context_data.update(extra_context)
        except Exception as e:
            logger.error(f"Error adding WebSocket context to BookingAdmin: {str(e)}")

        return response

    def user_email(self, obj):
        email = obj.user.email if obj.user else obj.guest_email or 'Guest'
        return format_html('<span aria-label="User or guest email">{}</span>', email)

    user_email.short_description = 'User/Guest Email'

    # === DELETE GUARDS: release seats so deleting an active booking never
    # leaks ferry inventory (a deleted confirmed/pending booking would
    # otherwise keep its seats reserved forever). ===
    def _release_if_active(self, booking):
        from bookings import services
        if booking.status in (services.BookingStatus.PENDING, services.BookingStatus.CONFIRMED):
            services.release_seats(booking.schedule_id, services.passenger_count(booking))

    def delete_model(self, request, obj):
        self._release_if_active(obj)
        super().delete_model(request, obj)
        clear_analytics_cache()

    def delete_queryset(self, request, queryset):
        for booking in queryset:
            self._release_if_active(booking)
        super().delete_queryset(request, queryset)
        clear_analytics_cache()

    # === ACTIONS ===

    def cancel_bookings(self, request, queryset):
        """Cancel via the service layer: releases seats, refunds (if paid),
        cancels tickets, and sets the correct 'cancelled' status. Idempotent."""
        from bookings import services
        cancelled, already, errors = 0, 0, 0
        for booking in queryset:
            try:
                _b, changed = services.cancel_booking(booking.pk, do_refund=True)
                if changed:
                    cancelled += 1
                else:
                    already += 1
            except Exception as e:
                errors += 1
                logger.error(f"Admin cancel failed for booking {booking.pk}: {e}")

        clear_analytics_cache()
        if get_channel_layer():
            async_to_sync(get_channel_layer().group_send)(
                'admin_dashboard',
                {
                    'type': 'booking_update',
                    'count': cancelled,
                    'action': 'cancelled',
                    'timestamp': timezone.now().isoformat()
                }
            )
        msg = f"{cancelled} booking(s) cancelled (seats released, refunds issued where applicable)."
        if already:
            msg += f" {already} were already cancelled."
        if errors:
            msg += f" {errors} failed — see logs."
        self.message_user(request, msg, messages.WARNING if errors else messages.SUCCESS)
        logger.info(f"Admin cancelled {cancelled} bookings ({already} no-op, {errors} errors)")

    cancel_bookings.short_description = "🔴 Cancel selected bookings (refund + release seats)"

    @admin.action(description="💵 Manually confirm (cash / offline payment)")
    def action_manual_confirm(self, request, queryset):
        from bookings import services
        confirmed, skipped, errors = 0, 0, []
        for booking in queryset:
            try:
                _, changed = services.manually_confirm_booking(
                    booking.pk, confirmed_by=request.user.email, reference='admin-manual'
                )
                if changed:
                    confirmed += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append(str(e))
        msg = f"{confirmed} booking(s) confirmed."
        if skipped:
            msg += f" {skipped} already confirmed."
        if errors:
            msg += f" Errors: {'; '.join(errors[:3])}"
        self.message_user(request, msg, messages.SUCCESS if confirmed else messages.WARNING)

    def mark_tickets_used(self, request, queryset):
        count = 0
        for booking in queryset:
            tickets_updated = Ticket.objects.filter(booking=booking).update(ticket_status='used')
            count += tickets_updated
        self.message_user(request, f"{count} tickets marked as used.")
        clear_analytics_cache()

        if get_channel_layer():
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'ticket_update',
                    'count': count,
                    'action': 'marked_used',
                    'timestamp': timezone.now().isoformat()
                }
            )
        logger.info(f"Cache invalidated after marking {count} tickets as used")

    mark_tickets_used.short_description = "Mark tickets as used"

    def mark_tickets_unused(self, request, queryset):
        count = 0
        for booking in queryset:
            tickets_updated = Ticket.objects.filter(booking=booking).update(ticket_status='active')
            count += tickets_updated
        self.message_user(request, f"{count} tickets marked as unused.")
        clear_analytics_cache()

        if get_channel_layer():
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'ticket_update',
                    'count': count,
                    'action': 'marked_unused',
                    'timestamp': timezone.now().isoformat()
                }
            )
        logger.info(f"Cache invalidated after marking {count} tickets as unused")

    mark_tickets_unused.short_description = "Mark tickets as unused"

    # === EXPORT WITH CARGO ===
    def export_bookings(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="selected_bookings_export.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'ID', 'User/Guest Email', 'Route', 'Booking Date', 'Status', 'Total Price',
            'Passengers', 'Vehicles', 'Cargo', 'Add-Ons'
        ])

        for item in queryset.select_related(
                'user', 'schedule__route__departure_port', 'schedule__route__destination_port'
        ).prefetch_related(
            'passengers', 'vehicles', 'cargo', 'add_ons'
        ):
            passengers = ", ".join([p.get_full_name() for p in item.passengers.all()]) or 'None'
            vehicles = ", ".join([f"{v.vehicle_type} ({v.license_plate})" for v in item.vehicles.all()]) or 'None'
            cargo_list = ", ".join([
                f"{c.get_cargo_type_display()} ({c.weight_kg}kg, {c.dimensions_cm})"
                for c in item.cargo.all()
            ]) or 'None'
            add_ons = ", ".join([
                f"{a.get_add_on_type_display()} (x{a.quantity})" for a in item.add_ons.all()
            ]) or 'None'

            writer.writerow([
                item.id,
                item.user.email if item.user else item.guest_email or 'Guest',
                f"{item.schedule.route.departure_port} to {item.schedule.route.destination_port}"
                if item.schedule and item.schedule.route else 'N/A',
                item.booking_date.strftime('%Y-%m-%d %H:%M') if item.booking_date else 'N/A',
                item.status,
                f"{item.total_price:.2f}" if item.total_price else '0.00',
                passengers,
                vehicles,
                cargo_list,
                add_ons
            ])

        logger.info(f"Exported {queryset.count()} bookings as CSV (with cargo)")
        clear_analytics_cache()
        return response

    export_bookings.short_description = "Export selected bookings (CSV)"

    # === OPTIMIZED QUERIES ===
    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'schedule__route__departure_port', 'schedule__route__destination_port'
        ).prefetch_related(
            'passengers', 'vehicles', 'cargo', 'add_ons'
        )

    # === SAVE HOOK ===
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()

        if get_channel_layer():
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'booking_update',
                    'booking_id': obj.id,
                    'status': obj.status,
                    'timestamp': timezone.now().isoformat()
                }
            )
        logger.info("Cache invalidated after Booking update")


@admin.register(Passenger, site=admin_site)
class PassengerAdmin(EnhancedModelAdmin):
    list_display = (
        'booking', 'first_name', 'last_name',
        'passenger_type', 'age', 'date_of_birth',
        'linked_adult_display', 'document_link',
    )
    list_filter = ('passenger_type', 'verification_status')
    search_fields = ('first_name', 'last_name', 'booking__id')
    autocomplete_fields = ['booking', 'linked_adult']
    list_per_page = 25
    ordering = ('booking__booking_date', 'last_name')
    list_display_links = ('booking', 'first_name')
    list_select_related = ('booking', 'linked_adult')
    empty_value_display = '—'
    actions = ['verify_documents', 'reject_documents', 'reset_verification']

    @admin.action(description="✅ Mark documents Verified")
    def verify_documents(self, request, queryset):
        updated = queryset.update(verification_status='verified')
        self.message_user(request, f"{updated} passenger(s) marked verified.", messages.SUCCESS)

    @admin.action(description="❌ Mark documents Rejected")
    def reject_documents(self, request, queryset):
        updated = queryset.update(verification_status='rejected')
        self.message_user(request, f"{updated} passenger(s) marked rejected.", messages.WARNING)

    @admin.action(description="↩️ Reset verification to Pending")
    def reset_verification(self, request, queryset):
        updated = queryset.update(verification_status='pending')
        self.message_user(request, f"{updated} passenger(s) reset to pending.", messages.INFO)

    fieldsets = (
        ('General Info', {
            'fields': ('booking', 'first_name', 'last_name')
        }),
        ('Details', {
            'fields': ('passenger_type', 'age', 'date_of_birth', 'linked_adult')
        }),
        ('Documents & Verification', {
            'fields': ('document', 'verification_status', 'is_group_leader')
        }),
    )

    @admin.display(description='Linked Adult', ordering='linked_adult__last_name')
    def linked_adult_display(self, obj: Passenger):
        la = obj.linked_adult
        if not la:
            return format_html('<span aria-label="Linked adult name">—</span>')
        name = la.get_full_name() if hasattr(la, 'get_full_name') else f"{la.first_name} {la.last_name}".strip()
        return format_html('<span aria-label="Linked adult name">{}</span>', name or '—')

    @admin.display(description="Document")
    def document_link(self, obj):
        if not obj.document:
            return "—"
        # Renders as a clickable download link
        return format_html(
            '<a href="{}" target="_blank">View</a>',
            obj.document.url
        )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('booking', 'linked_adult')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()
        logger.info("Cache invalidated after Passenger update")



@admin.register(Vehicle, site=admin_site)
class VehicleAdmin(EnhancedModelAdmin):
    list_display = ('booking', 'vehicle_type', 'dimensions', 'license_plate', 'price')
    list_filter = ('vehicle_type',)
    search_fields = ('license_plate', 'booking__id')
    autocomplete_fields = ['booking']
    list_per_page = 25
    ordering = ('booking__booking_date',)
    list_display_links = ('booking',)
    fieldsets = (
        ('General Info', {'fields': ('booking', 'vehicle_type')}),
        ('Details', {'fields': ('dimensions', 'license_plate', 'price')}),
    )
    readonly_fields = ('price',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('booking')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()
        logger.info("Cache invalidated after Vehicle update")


@admin.register(AddOn, site=admin_site)
class AddOnAdmin(EnhancedModelAdmin):
    list_display = ('booking', 'get_add_on_type_display', 'quantity', 'price')
    list_filter = ('add_on_type',)
    search_fields = ('booking__id', 'add_on_type')
    autocomplete_fields = ['booking']
    list_per_page = 25
    ordering = ('booking__booking_date',)
    list_display_links = ('booking',)
    fieldsets = (
        ('General Info', {'fields': ('booking', 'add_on_type')}),
        ('Details', {'fields': ('quantity', 'price')}),
    )
    readonly_fields = ('price',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('booking')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()
        logger.info("Cache invalidated after AddOn update")


@admin.register(Payment, site=admin_site)
class PaymentAdmin(EnhancedModelAdmin):
    list_display = ('booking', 'payment_method', 'amount', 'payment_status', 'payment_date')
    list_filter = ('payment_method', 'payment_status')
    search_fields = ('booking__id', 'transaction_id', 'session_id')
    autocomplete_fields = ['booking']
    date_hierarchy = 'payment_date'
    list_per_page = 25
    ordering = ('-payment_date',)
    list_display_links = ('booking',)
    readonly_fields = ('amount', 'payment_date')
    fieldsets = (
        ('General Info', {'fields': ('booking', 'payment_method')}),
        ('Details', {'fields': ('amount', 'payment_status', 'payment_date', 'transaction_id', 'session_id')}),
    )
    actions = ['mark_completed', 'mark_refunded', 'mark_failed']

    @admin.action(description="✅ Mark payment Completed")
    def mark_completed(self, request, queryset):
        updated = queryset.update(payment_status='completed')
        clear_analytics_cache()
        self.message_user(request, f"{updated} payment(s) marked completed.", messages.SUCCESS)

    @admin.action(description="💸 Mark payment Refunded (record only)")
    def mark_refunded(self, request, queryset):
        updated = queryset.update(payment_status='refunded')
        clear_analytics_cache()
        self.message_user(
            request,
            f"{updated} payment(s) marked refunded. Note: this only updates the record — "
            "use the booking Cancel action to issue an actual Stripe refund.",
            messages.WARNING,
        )

    @admin.action(description="⚠️ Mark payment Failed")
    def mark_failed(self, request, queryset):
        updated = queryset.update(payment_status='failed')
        clear_analytics_cache()
        self.message_user(request, f"{updated} payment(s) marked failed.", messages.WARNING)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('booking')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()

        # WebSocket notification for payment updates
        if get_channel_layer() and obj.payment_status == 'completed':
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'payment_update',
                    'payment_id': obj.id,
                    'amount': float(obj.amount),
                    'status': obj.payment_status,
                    'timestamp': timezone.now().isoformat()
                }
            )
        logger.info("Cache invalidated after Payment update")


@admin.register(Ticket, site=admin_site)
class TicketAdmin(EnhancedModelAdmin):
    list_display = ('booking', 'passenger', 'ticket_status', 'issued_at', 'qr_token')
    list_filter = (TicketStatusFilter, 'ticket_status')
    search_fields = ('booking__id', 'passenger__first_name', 'passenger__last_name', 'qr_token')
    autocomplete_fields = ['booking', 'passenger']
    date_hierarchy = 'issued_at'
    list_per_page = 25
    ordering = ('-issued_at',)
    list_display_links = ('booking', 'passenger')
    readonly_fields = ('issued_at', 'qr_token')
    fieldsets = (
        ('General Info', {'fields': ('booking', 'passenger')}),
        ('Details', {'fields': ('ticket_status', 'issued_at', 'qr_code', 'qr_token')}),
    )
    actions = ['mark_tickets_used', 'mark_tickets_unused', 'smart_validate_tickets']

    def changelist_view(self, request, extra_context=None):
        """Override to add WebSocket context"""
        response = super().changelist_view(request, extra_context)

        # Add WebSocket context to template
        if extra_context is None:
            extra_context = {}

        try:
            from django.template.response import TemplateResponse
            if isinstance(response, TemplateResponse):
                cl = response.context_data.get('cl')
                if cl:
                    websocket_context = admin_site.get_changelist_context(cl)
                    extra_context['websocket_cl_data'] = websocket_context
                    response.context_data.update(extra_context)
        except Exception as e:
            logger.error(f"Error adding WebSocket context: {str(e)}")

        return response

    def mark_tickets_used(self, request, queryset):
        count = queryset.update(ticket_status='used')
        self.message_user(request, f"{count} tickets marked as used.")
        clear_analytics_cache()

        # WebSocket notification
        if get_channel_layer():
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'ticket_update',
                    'count': count,
                    'action': 'marked_used',
                    'timestamp': timezone.now().isoformat()
                }
            )
        logger.info(f"Cache invalidated after marking {count} tickets as used")

    mark_tickets_used.short_description = "Mark tickets as used"

    def mark_tickets_unused(self, request, queryset):
        count = queryset.update(ticket_status='active')
        self.message_user(request, f"{count} tickets marked as unused.")
        clear_analytics_cache()

        # WebSocket notification
        if get_channel_layer():
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'ticket_update',
                    'count': count,
                    'action': 'marked_unused',
                    'timestamp': timezone.now().isoformat()
                }
            )
        logger.info(f"Cache invalidated after marking {count} tickets as unused")

    mark_tickets_unused.short_description = "Mark tickets as unused"

    def smart_validate_tickets(self, request, queryset):
        """Smart ticket validation with QR code generation and status tracking."""
        updated = AdminEnhancements.smart_ticket_validation(queryset)
        self.message_user(request, f"Smart validated {updated} tickets.")
        clear_analytics_cache()

        # WebSocket notification
        if get_channel_layer():
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'ticket_update',
                    'count': updated,
                    'action': 'smart_validated',
                    'timestamp': timezone.now().isoformat()
                }
            )
        logger.info(f"Cache invalidated after smart validating {updated} tickets")

    smart_validate_tickets.short_description = "Smart validate tickets"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('booking', 'passenger')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()
        logger.info("Cache invalidated after Ticket update")


@admin.register(MaintenanceLog, site=admin_site)
class MaintenanceLogAdmin(EnhancedModelAdmin):
    list_display = ('ferry', 'maintenance_date', 'completed_at', 'maintenance_interval_days')
    list_filter = ('ferry', 'maintenance_date')
    search_fields = ('ferry__name',)
    autocomplete_fields = ['ferry']
    date_hierarchy = 'maintenance_date'
    list_per_page = 25
    ordering = ('-maintenance_date',)
    list_display_links = ('ferry',)
    fieldsets = (
        ('General Info', {'fields': ('ferry', 'maintenance_date')}),
        ('Details', {'fields': ('completed_at', 'maintenance_interval_days')}),
    )
    actions = ['mark_completed', 'reopen_maintenance']

    @admin.action(description="✅ Mark maintenance Completed (restores schedules)")
    def mark_completed(self, request, queryset):
        # Save individually so the post_save signal restores the ferry's
        # delayed schedules (bulk update would skip the signal).
        count = 0
        for log in queryset.filter(completed_at__isnull=True):
            log.completed_at = timezone.now()
            log.save(update_fields=['completed_at'])
            count += 1
        self.message_user(
            request, f"{count} maintenance log(s) completed; affected schedules restored.",
            messages.SUCCESS,
        )

    @admin.action(description="🔧 Reopen maintenance (delays upcoming schedules)")
    def reopen_maintenance(self, request, queryset):
        count = 0
        for log in queryset.exclude(completed_at__isnull=True):
            log.completed_at = None
            log.save(update_fields=['completed_at'])
            count += 1
        self.message_user(
            request, f"{count} maintenance log(s) reopened; upcoming schedules delayed.",
            messages.WARNING,
        )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('ferry')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()

        # WebSocket notification for maintenance updates
        if get_channel_layer() and obj.completed_at:
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'maintenance_update',
                    'ferry': obj.ferry.name,
                    'status': 'completed' if obj.completed_at else 'pending',
                    'timestamp': timezone.now().isoformat()
                }
            )
        logger.info("Cache invalidated after MaintenanceLog update")


@admin.register(ServicePattern, site=admin_site)
class ServicePatternAdmin(EnhancedModelAdmin):
    list_display = ('route', 'get_weekday_display', 'window', 'target_departures')
    list_filter = ('weekday', 'route')
    search_fields = ('route__departure_port__name', 'route__destination_port__name')
    autocomplete_fields = ['route']
    list_per_page = 25
    ordering = ('route', 'weekday')
    list_display_links = ('route',)

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('route__departure_port', 'route__destination_port')

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        clear_analytics_cache()
        logger.info("Cache invalidated after ServicePattern update")


# Signal handlers for real-time updates
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


@receiver([post_save, post_delete])
def trigger_realtime_updates(sender, instance, **kwargs):
    """Trigger real-time updates when models are modified."""
    if sender not in [Booking, Payment, Schedule, WeatherCondition, Ticket, MaintenanceLog]:
        return

    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    action_type = 'save' if kwargs.get('created', False) or post_save == kwargs['signal'] else 'delete'
    now = timezone.now()
    message = {
        'type': f'{sender.__name__.lower()}_update',
        'model': sender.__name__.lower(),
        'action': action_type,
        'instance_id': getattr(instance, 'id', None),
        'timestamp': now.isoformat()
    }

    # Add recent_activities to every update
    recent_logs = LogEntry.objects.select_related('user', 'content_type').filter(
        action_time__gte=now - timedelta(days=7)
    ).order_by('-action_time')[:10]
    consolidated_activities = defaultdict(
        lambda: {'count': 0, 'timestamp': None, 'operator': None, 'action': None, 'resource': None})
    for log in recent_logs:
        action = log.get_change_message()
        resource = f"{log.content_type} ({log.object_repr})"
        key = (action, resource)
        if key in consolidated_activities:
            consolidated_activities[key]['count'] += 1
        else:
            consolidated_activities[key]['count'] = 1
            consolidated_activities[key]['timestamp'] = log.action_time.isoformat()
            consolidated_activities[key]['operator'] = log.user.username
            consolidated_activities[key]['action'] = action
            consolidated_activities[key]['resource'] = resource
    message['recent_activities'] = [
        {
            'timestamp': v['timestamp'],
            'operator': v['operator'],
            'action': v['action'],
            'resource': v['resource'],
            'count': v['count']
        }
        for v in consolidated_activities.values()
    ]

    # Specific data for certain models
    if sender in [Booking, Ticket, Payment]:
        recent_bookings = [
            {
                'id': b.id,
                'user_email': b.user.email if b.user else b.guest_email or 'Guest',
                'route': f"{b.schedule.route.departure_port.name} to {b.schedule.route.destination_port.name}" if b.schedule and b.schedule.route else 'N/A',
                'booking_date': b.booking_date.isoformat() if b.booking_date else None,
                'status': b.status
            }
            for b in Booking.objects.select_related('user', 'schedule__route__departure_port',
                                                    'schedule__route__destination_port').order_by('-booking_date')[:10]
        ]
        message['type'] = 'booking_update'
        message['recent_bookings'] = recent_bookings
        if sender == Payment:
            message['type'] = 'payment_update'
        elif sender == Ticket:
            message['type'] = 'ticket_update'

    elif sender == WeatherCondition:
        message['type'] = 'weather_alerts'
        message['weather_alerts'] = AdminEnhancements.get_critical_alerts()

    async_to_sync(channel_layer.group_send)('admin_dashboard', message)


# Background task management
async def periodic_admin_updates():
    """Periodic background tasks for admin updates."""
    while True:
        try:
            # Check for critical alerts and broadcast
            if get_channel_layer():
                channel_layer = get_channel_layer()
                alerts = AdminEnhancements.get_critical_alerts()
                if alerts:
                    await channel_layer.group_send(
                        'admin_dashboard',
                        {
                            'type': 'critical_alerts',
                            'alerts': alerts[:3],  # Top 3 critical alerts
                            'timestamp': timezone.now().isoformat()
                        }
                    )

            # Clear temporary cache entries
            cache.delete_pattern('temp_*')
            cache.delete_pattern('weather_alerts_*')

            # Check for notifications
            notifications = AdminEnhancements.check_for_notifications(None)  # System-wide check
            if notifications and get_channel_layer():
                await channel_layer.group_send(
                    'admin_dashboard',
                    {
                        'type': 'system_notifications',
                        'notifications': notifications,
                        'timestamp': timezone.now().isoformat()
                    }
                )

        except Exception as e:
            logger.error(f"Periodic update error: {str(e)}", exc_info=True)

        await asyncio.sleep(300)  # Run every 5 minutes


def start_admin_background_tasks():
    """Start background tasks for admin enhancements."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(periodic_admin_updates())
            logger.info("Admin background tasks started in existing event loop")
        else:
            loop.run_until_complete(periodic_admin_updates())
            logger.info("Admin background tasks completed")
    except Exception as e:
        logger.error(f"Failed to start admin background tasks: {str(e)}")


# Export utilities
__all__ = [
    'AdminEnhancements', 'clear_analytics_cache', 'CustomAdminSite',
    'start_admin_background_tasks', 'periodic_admin_updates'
]