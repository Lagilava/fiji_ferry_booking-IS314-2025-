import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ferry_system.settings')
django.setup()

from bookings.models import Port, Ferry, Route, Schedule
from datetime import datetime, date, timedelta

# ensure ports
nadi, _ = Port.objects.get_or_create(name='Nadi', defaults={'lat': -17.7728, 'lng': 177.3805})
suva, _ = Port.objects.get_or_create(name='Suva', defaults={'lat': -18.1248, 'lng': 178.3967})

# ensure ferry
ferry, _ = Ferry.objects.get_or_create(name='Lomaiviti Princess', defaults={'capacity': 800, 'operator': 'Fiji Ferries', 'home_port': nadi})

# ensure route
route, _ = Route.objects.get_or_create(departure_port=nadi, destination_port=suva,
                                      defaults={'distance_km': 150.0, 'estimated_duration': timedelta(hours=3, minutes=30), 'base_fare': 500.00, 'service_tier':'major', 'preferred_departure_windows':['06:00-09:00'], 'safety_buffer_minutes': 15})

departure_dt = datetime(2026, 3, 23, 10, 0)
arrival_dt = departure_dt + timedelta(hours=3, minutes=30)

schedule, created = Schedule.objects.get_or_create(
    ferry=ferry,
    route=route,
    departure_time=departure_dt,
    defaults={
        'arrival_time': arrival_dt,
        'estimated_duration': '3h 30m',
        'available_seats': 100,
        'status': 'scheduled',
        'operational_day': date(2026,3,23),
        'notes': 'Seed row for filter test',
        'created_by_auto': False
    }
)

print('Created schedule:', created, 'id', schedule.id)
print('Schedule:', schedule)
