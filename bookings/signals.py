from django.db.models.signals import post_save
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from bookings.models import Booking
import json
import logging

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Booking)
def broadcast_booking_update(sender, instance, created, **kwargs):
    """Broadcast booking updates to admin dashboard via WebSocket."""
    try:
        channel_layer = get_channel_layer()
        booking_data = {
            'booking_id': instance.id,
            'status': instance.status,
            'route': f"{instance.schedule.route.departure_port.name} to {instance.schedule.route.destination_port.name}",
            'total_price': float(instance.total_price or 0),
            'booking_date': instance.booking_date.isoformat(),
            'passengers': instance.passenger_adults + instance.passenger_children + instance.passenger_infants
        }
        async_to_sync(channel_layer.group_send)(
            "admin_dashboard",
            {
                "type": "booking_update",
                "data": [booking_data]
            }
        )
        logger.info(f"Broadcasted booking update for booking {instance.id}")
    except Exception as e:
        logger.error(f"Error broadcasting booking update for {instance.id}: {str(e)}")