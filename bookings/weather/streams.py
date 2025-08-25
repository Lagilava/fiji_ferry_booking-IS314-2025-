import json
import time
from django.http import StreamingHttpResponse
from bookings.models import Route
import requests

from ferry_system import settings


def weather_stream(request):
    def event_stream():
        while True:
            try:
                routes = Route.objects.all()
                weather_data = []
                for route in routes:
                    port = route.departure_port
                    if port.latitude and port.longitude:
                        api_key = settings.OPENWEATHERMAP_API_KEY  #key
                        url = f"http://api.openweathermap.org/data/2.5/weather?lat={port.latitude}&lon={port.longitude}&appid={api_key}&units=metric"
                        response = requests.get(url, timeout=5)
                        if response.status_code == 200:
                            data = response.json()
                            weather_data.append({
                                'route_id': route.id,
                                'port': port.name,
                                'temperature': data['main']['temp'],
                                'wind_speed': data['wind']['speed'] * 3.6,  # Convert m/s to kph
                                'wave_height': None,  # Use marine API like Storm Glass if needed
                                'condition': data['weather'][0]['main'],
                                'error': None
                            })
                        else:
                            weather_data.append({
                                'route_id': route.id,
                                'port': port.name,
                                'temperature': None,
                                'wind_speed': None,
                                'wave_height': None,
                                'condition': None,
                                'error': 'Failed to fetch weather data'
                            })
                    else:
                        weather_data.append({
                            'route_id': route.id,
                            'port': port.name,
                            'temperature': None,
                            'wind_speed': None,
                            'wave_height': None,
                            'condition': None,
                            'error': 'Port coordinates unavailable'
                        })
                yield f"data: {json.dumps({'weather': weather_data})}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'weather': [], 'error': str(e)})}\n\n"
            time.sleep(60)  # Update every minute

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response