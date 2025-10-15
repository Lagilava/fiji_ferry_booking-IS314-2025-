# Add this to bookings/consumers.py - DO NOT REMOVE EXISTING CODE

import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from asgiref.sync import sync_to_async
from django.utils import timezone, asyncio
from django.apps import apps
from django.contrib import admin
from django.db import transaction
from django.http import HttpRequest
from .admin import AdminEnhancements
from .models import Booking, Schedule, Ticket, Payment, WeatherCondition
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)


class AdminDashboardConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_anonymous or not self.user.is_staff:
            await self.close()
            logger.warning(f"Unauthorized WebSocket connection attempt by {self.scope.get('user', 'anonymous')}")
            return

        self.group_name = 'admin_dashboard'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"Admin WebSocket connected: {self.user.username}")

        # Send initial data
        await self.send_initial_data()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"Admin WebSocket disconnected: {self.scope.get('user', 'anonymous')}")

    @database_sync_to_async
    def get_initial_data_sync(self):
        """Sync wrapper for initial data"""
        return {
            'bookings': AdminEnhancements.get_realtime_bookings(),
            'schedules': AdminEnhancements.get_realtime_schedules(),
            'alerts': AdminEnhancements.get_critical_alerts(),
            'payments': AdminEnhancements.get_realtime_payments(),
            'timestamp': timezone.now().isoformat()
        }

    async def send_initial_data(self):
        """Send initial real-time data to connected clients"""
        try:
            initial_data = await sync_to_async(self.get_initial_data_sync)()
            data = {
                'type': 'initial_data',
                **initial_data
            }
            await self.send(text_data=json.dumps(data))
            logger.info("Initial data sent to admin dashboard")
        except Exception as e:
            logger.error(f"Error sending initial data: {str(e)}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Failed to load initial data'
            }))

    async def receive(self, text_data):
        """Handle messages from admin clients"""
        try:
            data = json.loads(text_data)
            action = data.get('action')

            if action == 'refresh_weather':
                await self.broadcast_weather_update()
            elif action == 'refresh_data':
                await self.send_initial_data()
            elif action == 'force_cache_clear':
                await self.clear_cache_and_notify()

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received: {text_data}")
        except Exception as e:
            logger.error(f"WebSocket receive error: {str(e)}")

    async def broadcast_weather_update(self):
        """Broadcast weather updates to all admin clients"""
        try:
            alerts = await sync_to_async(AdminEnhancements.get_critical_alerts)()
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'weather_alerts_update',
                    'weather_alerts': alerts,
                    'timestamp': timezone.now().isoformat()
                }
            )
        except Exception as e:
            logger.error(f"Weather broadcast error: {str(e)}")

    async def clear_cache_and_notify(self):
        """Clear analytics cache and notify clients"""
        try:
            from .admin import clear_analytics_cache
            sync_to_async(clear_analytics_cache)()
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'cache_cleared',
                    'message': 'Analytics cache cleared successfully',
                    'timestamp': timezone.now().isoformat()
                }
            )
        except Exception as e:
            logger.error(f"Cache clear error: {str(e)}")

    # Message handlers for broadcasting
    async def model_update(self, event):
        """Handle generic model updates"""
        await self.send(text_data=json.dumps({
            'type': f'{event["model"]}_update',
            'action': event['action'],
            'instance_id': event.get('instance_id'),
            'timestamp': event['timestamp']
        }))

    async def ticket_update(self, event):
        ticket_id = event.get('ticket_id')
        new_status = event.get('new_status', 'unknown')

        if ticket_id is None:
            logger.error(f"Missing 'ticket_id' in ticket_update event: {event}")
            return

        await self.send(text_data=json.dumps({
            'type': 'ticket_update',
            'ticket_id': ticket_id,
            'old_status': event.get('old_status'),
            'new_status': new_status,
            'timestamp': event.get('timestamp'),
            'message': f"Ticket {ticket_id} updated to {new_status}"
        }))

        logger.info(f"Ticket update broadcast: {ticket_id} -> {new_status}")

    async def booking_update(self, event):
        """Handle booking updates"""
        await self.send(text_data=json.dumps({
            'type': 'booking_update',
            'booking_id': event.get('booking_id'),
            'count': event.get('count'),
            'action': event['action'],
            'status': event.get('status'),
            'timestamp': event['timestamp']
        }))

    async def schedule_update(self, event):
        """Handle schedule updates"""
        await self.send(text_data=json.dumps({
            'type': 'schedule_update',
            'schedule_id': event['schedule_id'],
            'status': event['status'],
            'available_seats': event['available_seats'],
            'timestamp': event['timestamp']
        }))

    async def weather_alerts_update(self, event):
        """Handle weather alerts"""
        await self.send(text_data=json.dumps({
            'type': 'weather_alerts',
            'weather_alerts': event['weather_alerts'],
            'timestamp': event['timestamp']
        }))

    async def cache_cleared(self, event):
        """Handle cache clear notifications"""
        await self.send(text_data=json.dumps({
            'type': 'cache_cleared',
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def handleMessage(self, data):
        """Enhanced message handling for change list integration"""
        message_type = data.get('type')

        if message_type == 'join_changelist':
            await self.handleJoinChangeList(data)
        elif message_type == 'request_changelist_sync':
            await self.handleChangeListSync(data)
        elif message_type == 'selection_change':
            await self.broadcastSelectionChange(data)
        else:
            # Existing handlers
            if data.get('action') == 'refresh_weather':
                await self.broadcast_weather_update()
            # ... rest of existing handlers

    async def handleJoinChangeList(self, data):
        """Handle change list connection"""
        model = data.get('model')
        app_label = data.get('app_label')
        if model and app_label:
            group_name = f"admin_changelist_{app_label}_{model}"
            await self.channel_layer.group_add(group_name, self.channel_name)
            await self.send(text_data=json.dumps({
                'type': 'connection_confirmed',
                'model': model,
                'app_label': app_label
            }))

    async def handleChangeListSync(self, data):
        """Handle change list sync request"""
        model = data.get('model')
        app_label = data.get('app_label')
        filters = data.get('filters', {})

        # Forward to model-specific consumer or handle here
        group_name = f"admin_changelist_{app_label}_{model}"
        await self.channel_layer.group_send(
            group_name,
            {
                'type': 'full_sync',
                'objects': [],  # You'd populate this with actual data
                'fields': [],  # Field definitions
                'total_count': 0,
                'timestamp': timezone.now().isoformat()
            }
        )

    async def broadcastSelectionChange(self, data):
        """Broadcast selection changes to model group"""
        model = data.get('model')
        app_label = data.get('app_label')
        if model and app_label:
            group_name = f"admin_changelist_{app_label}_{model}"
            await self.channel_layer.group_send(
                group_name,
                {
                    'type': 'selection_change',
                    'selected': data.get('selected', []),
                    'timestamp': timezone.now().isoformat()
                }
            )

class AdminChangeListConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time admin change list updates
    """

    async def connect(self):
        self.user = self.scope["user"]
        if self.user.is_anonymous or not self.user.is_staff:
            await self.close()
            logger.warning(f"Unauthorized ChangeList WebSocket connection by {self.scope.get('user', 'anonymous')}")
            return

        # Extract model info from query params or path
        self.app_label = self.scope['url_route']['kwargs'].get('app_label') or \
                         self.scope['query_string'].decode().split('app_label=')[1].split('&')[0] if 'app_label=' in \
                                                                                                     self.scope[
                                                                                                         'query_string'].decode() else None
        self.model_name = self.scope['url_route']['kwargs'].get('model') or \
                          self.scope['query_string'].decode().split('model=')[1].split('&')[0] if 'model=' in \
                                                                                                  self.scope[
                                                                                                      'query_string'].decode() else None

        if not self.app_label or not self.model_name:
            await self.close()
            logger.error("Missing app_label or model_name in ChangeList WebSocket connection")
            return

        self.model = apps.get_model(self.app_label, self.model_name)
        self.group_name = f"admin_changelist_{self.app_label}_{self.model_name}"

        # Store connection info
        self.filters = {}
        self.user_filters = {}

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        logger.info(
            f"Admin ChangeList WebSocket connected: {self.user.username} for {self.app_label}.{self.model_name}")

        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_confirmed',
            'model': self.model_name,
            'app_label': self.app_label,
            'timestamp': timezone.now().isoformat()
        }))

        # Send initial sync after brief delay to allow client setup
        await self.send_initial_sync()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(
            f"Admin ChangeList WebSocket disconnected: {self.user.username} for {self.app_label}.{self.model_name}")

    async def receive(self, text_data):
        """Handle messages from admin change list clients"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            logger.debug(f"Received {message_type} from {self.user.username}: {data}")

            if message_type == 'connection':
                await self.handle_connection(data)
            elif message_type == 'request_sync':
                await self.handle_request_sync(data)
            elif message_type == 'selection_change':
                await self.handle_selection_change(data)
            elif message_type == 'apply_filters':
                await self.handle_apply_filters(data)
            else:
                logger.warning(f"Unknown message type: {message_type}")

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received: {text_data}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))
        except Exception as e:
            logger.error(f"ChangeList WebSocket receive error: {str(e)}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Server error: {str(e)}'
            }))

    @database_sync_to_async
    def get_model_admin(self):
        """Get the model admin instance"""
        try:
            app_config = apps.get_app_config(self.app_label)
            model_admin = admin.site._registry[self.model]
            return model_admin
        except (KeyError, AttributeError):
            return None

    @database_sync_to_async
    def get_filtered_queryset(self, filters=None):
        """Get filtered queryset for the current user and filters"""
        try:
            model_admin = admin.site._registry.get(self.model)
            if not model_admin:
                return [], []

            # Create mock request for admin context
            request = HttpRequest()
            request.user = self.user

            # Apply filters if provided
            queryset = model_admin.get_queryset(request)

            if filters:
                # Apply search and filter conditions
                if filters.get('q'):
                    queryset = queryset.filter(
                        model_admin.get_search_results(request, queryset, filters['q'])
                    )

                # Apply field filters
                for field, value in filters.items():
                    if field not in ['q', 'o', '_p']:  # Skip pagination and ordering
                        # This is simplified - you'd need to handle actual filter logic
                        # based on your ModelAdmin's filter implementation
                        pass

            # Get field structure for table display
            fields = []
            for field in model_admin.list_display:
                if callable(field):
                    field_name = field.__name__
                    verbose_name = field_name
                else:
                    field_name = field
                    verbose_name = str(model_admin.model._meta.get_field(field).verbose_name)
                fields.append({
                    'name': field_name,
                    'verbose_name': verbose_name
                })

            # Serialize objects for WebSocket
            objects = []
            for obj in queryset[:100]:  # Limit for performance
                obj_data = {
                    'id': obj.pk,
                    'fields': {}
                }
                for field in fields:
                    try:
                        value = getattr(obj, field['name'])
                        if callable(value):
                            value = value()
                        obj_data['fields'][field['name']] = str(value)
                    except Exception:
                        obj_data['fields'][field['name']] = 'N/A'
                objects.append(obj_data)

            return objects, fields

        except Exception as e:
            logger.error(f"Error getting filtered queryset: {str(e)}")
            return [], []

    async def handle_connection(self, data):
        """Handle initial connection with model info"""
        self.user_filters[self.user.id] = data.get('filters', {})
        await self.send(text_data=json.dumps({
            'type': 'filters_applied',
            'filters': self.user_filters.get(self.user.id, {}),
            'timestamp': timezone.now().isoformat()
        }))

    async def handle_request_sync(self, data):
        """Handle full sync request"""
        try:
            filters = data.get('filters', {})
            objects, fields = await sync_to_async(self.get_filtered_queryset)(filters)

            await self.send(text_data=json.dumps({
                'type': 'full_sync',
                'objects': objects,
                'fields': fields,
                'total_count': len(objects),
                'timestamp': timezone.now().isoformat()
            }))

            logger.info(f"Full sync sent to {self.user.username}: {len(objects)} {self.model_name} objects")

        except Exception as e:
            logger.error(f"Full sync error: {str(e)}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Sync failed: {str(e)}'
            }))

    async def handle_selection_change(self, data):
        """Handle selection changes for export coordination"""
        selected_ids = data.get('selected', [])
        # Broadcast to group for coordination
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'selection_change',
                'selected': selected_ids,
                'user': self.user.username,
                'timestamp': timezone.now().isoformat()
            }
        )

    async def handle_apply_filters(self, data):
        """Handle filter application"""
        self.user_filters[self.user.id] = data.get('filters', {})
        await self.handle_request_sync(data)

    async def send_initial_sync(self):
        """Send initial data sync after connection"""
        await asyncio.sleep(0.5)  # Brief delay for client setup
        await self.handle_request_sync({'filters': {}})

    # Message handlers for broadcasting updates
    async def model_update(self, event):
        """Broadcast model updates to matching clients"""
        if not self.user.is_staff:
            return

        try:
            await self.send(text_data=json.dumps({
                'type': 'model_update',
                'action': event['action'],
                'model': event['model'],
                'objects': event.get('objects', []),
                'timestamp': event['timestamp']
            }))

            logger.debug(f"Model update broadcast to {self.user.username}: {event['action']} on {event['model']}")

        except Exception as e:
            logger.error(f"Model update broadcast error: {str(e)}")

    async def selection_change(self, event):
        """Broadcast selection changes"""
        await self.send(text_data=json.dumps({
            'type': 'selection_change',
            'selected': event['selected'],
            'user': event['user'],
            'timestamp': event['timestamp']
        }))

    async def activity_update(self, event):
        """Broadcast activity updates"""
        await self.send(text_data=json.dumps({
            'type': 'activity',
            'user': event['user'],
            'action': event['action'],
            'target': event['target'],
            'details': event.get('details'),
            'timestamp': event['timestamp']
        }))

    async def export_ready(self, event):
        """Handle export completion"""
        await self.send(text_data=json.dumps({
            'type': 'export_ready',
            'export_id': event['export_id'],
            'filename': event['filename'],
            'timestamp': event['timestamp']
        }))


# Signal handlers for real-time updates (add to your signals.py or here)
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


@receiver([post_save, post_delete], dispatch_uid="admin_changelist_signals")
def broadcast_model_changes(sender, instance, **kwargs):
    """Broadcast model changes to admin change list WebSocket"""
    if not hasattr(instance, '_broadcast_to_changelist'):
        return

    # Only broadcast if explicitly marked
    if not getattr(instance, '_broadcast_to_changelist', False):
        return

    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            model_name = instance._meta.model_name
            app_label = instance._meta.app_label

            # Determine action
            action = 'delete' if kwargs.get('using', False) and kwargs.get('signal') == post_delete else 'update'
            if kwargs.get('created'):
                action = 'create'

            async def broadcast_update():
                await channel_layer.group_send(
                    f"admin_changelist_{app_label}_{model_name}",
                    {
                        'type': 'model_update',
                        'action': action,
                        'model': model_name,
                        'objects': [{
                            'id': instance.pk,
                            'fields': {field.name: str(getattr(instance, field.name, 'N/A'))
                                       for field in instance._meta.fields}
                        }],
                        'timestamp': timezone.now().isoformat()
                    }
                )

            # Run async broadcast
            import asyncio
            loop = asyncio.get_event_loop()
            loop.create_task(broadcast_update())

    except Exception as e:
        logger.error(f"Error broadcasting model change: {str(e)}")


# Utility function to mark instances for broadcasting
def mark_for_broadcast(instance):
    """Mark instance for WebSocket broadcasting"""
    setattr(instance, '_broadcast_to_changelist', True)
    return instance


# Admin action decorator for real-time updates
def broadcast_admin_action(action_func):
    """Decorator to broadcast admin actions"""

    def wrapper(modeladmin, request, queryset):
        result = action_func(modeladmin, request, queryset)

        try:
            channel_layer = get_channel_layer()
            if channel_layer:
                app_label = modeladmin.model._meta.app_label
                model_name = modeladmin.model._meta.model_name

                async def broadcast_action():
                    await channel_layer.group_send(
                        f"admin_changelist_{app_label}_{model_name}",
                        {
                            'type': 'activity_update',
                            'user': request.user.username,
                            'action': f'bulk_{action_func.__name__}',
                            'target': f'{len(queryset)} {model_name}(s)',
                            'details': f'Admin action executed by {request.user.username}',
                            'timestamp': timezone.now().isoformat()
                        }
                    )

                import asyncio
                loop = asyncio.get_event_loop()
                loop.create_task(broadcast_action())

        except Exception as e:
            logger.error(f"Error broadcasting admin action: {str(e)}")

        return result

    return wrapper