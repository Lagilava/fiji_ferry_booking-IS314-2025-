from channels.generic.websocket import AsyncWebsocketConsumer
import json
import logging
from bookings.models import Schedule

logger = logging.getLogger(__name__)

class ScheduleConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        await self.channel_layer.group_add('schedules', self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard('schedules', self.channel_name)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            if data.get('action') == 'update' and data.get('schedule'):
                await self.channel_layer.group_send(
                    'schedules',
                    {
                        'type': 'schedule_update',
                        'schedule': data.get('schedule')
                    }
                )
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON received: {text_data}")
            await self.send(text_data=json.dumps({'error': 'Invalid JSON'}))

    async def schedule_update(self, event):
        await self.send(text_data=json.dumps({
            'schedule': event['schedule']
        }))