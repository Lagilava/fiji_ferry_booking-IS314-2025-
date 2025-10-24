# bookings/signals.py
from datetime import timedelta

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from bookings.models import Booking, Payment, Schedule, WeatherCondition, Ticket, MaintenanceLog
from bookings.admin import AdminEnhancements
from django.utils import timezone
import json
import logging
from collections import defaultdict
from django.contrib.admin.models import LogEntry

logger = logging.getLogger(__name__)

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

    # Include notifications and alerts in every message to ensure update
    message['notifications'] = AdminEnhancements.check_for_notifications(None)
    message['alerts'] = AdminEnhancements.get_critical_alerts()

    async_to_sync(channel_layer.group_send)('admin_dashboard', message)

@receiver(post_save, sender=Booking)
def notify_high_value_booking(sender, instance, created, **kwargs):
    channel_layer = get_channel_layer()
    if channel_layer and created and instance.total_price > 1000 and instance.status == 'confirmed':
        notifications = AdminEnhancements.check_for_notifications(None)
        if notifications:
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'system_notifications',
                    'notifications': notifications,
                    'timestamp': timezone.now().isoformat()
                }
            )

@receiver(post_save, sender=Payment)
def notify_failed_payment(sender, instance, created, **kwargs):
    channel_layer = get_channel_layer()
    if channel_layer and created and instance.payment_status == 'failed':
        notifications = AdminEnhancements.check_for_notifications(None)
        if notifications:
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'system_notifications',
                    'notifications': notifications,
                    'timestamp': timezone.now().isoformat()
                }
            )

@receiver(post_save, sender=Schedule)
def notify_schedule_alert(sender, instance, **kwargs):
    channel_layer = get_channel_layer()
    if channel_layer and (instance.available_seats < 5 or instance.status == 'delayed'):
        alerts = AdminEnhancements.get_critical_alerts()
        if alerts:
            async_to_sync(channel_layer.group_send)(
                'admin_dashboard',
                {
                    'type': 'critical_alerts',
                    'alerts': alerts,
                    'timestamp': timezone.now().isoformat()
                }
            )