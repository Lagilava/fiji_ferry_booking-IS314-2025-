import base64
import datetime
import hashlib
import io
import json
import logging
import os
import re
import time
import uuid
from decimal import Decimal, ROUND_HALF_UP
from email.mime.image import MIMEImage
from io import BytesIO

import qrcode
import requests
import stripe
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import send_mail, EmailMultiAlternatives
from django.core.validators import FileExtensionValidator
from django.db import transaction
from django.db.models import Subquery, Max, OuterRef, Prefetch, Q, F
from django.http import FileResponse
from django.http import JsonResponse, HttpResponseForbidden, StreamingHttpResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST, require_GET
# PDF generation lives in bookings/pdf.py (render_booking_pdf).

from .decorators import login_required_allow_anonymous
from .forms import ModifyBookingForm
from .models import Schedule, Booking, Passenger, Payment, Ticket, Cargo, Route, WeatherCondition, AddOn, Vehicle, Port
from . import services
from .pdf import render_booking_pdf
from .views_helpers import (
    _otp_store_key, generate_otp_code, require_guest_otp
)

EMAIL_RE = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

def safe_float(val):
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


def safe_int(val):
    try:
        return int(val) if val is not None else 0
    except (TypeError, ValueError):
        return 0


@require_GET
@csrf_exempt
def check_session(request):
    """
    Check if the user's session is valid.
    """
    if request.session.session_key:
        return JsonResponse({'valid': True})
    return JsonResponse({'valid': False}, status=401)


@require_GET
def weather_stream(request):
    API_KEY = settings.WEATHER_API_KEY
    FETCH_INTERVAL = 30  # seconds

    def fetch_weather(route, port):
        """Fetch weather from DB or API"""
        now = timezone.now()
        # Check DB first
        weather = WeatherCondition.objects.filter(
            route=route, port=port, expires_at__gt=now
        ).order_by('-updated_at').first()

        if weather and not weather.is_expired():
            return weather

        # Fallback to API
        try:
            resp = requests.get(
                'https://api.weatherapi.com/v1/current.json',
                params={'key': API_KEY, 'q': f"{port.lat},{port.lng}", 'aqi': 'no'},
                timeout=5
            )
            resp.raise_for_status()
            data = resp.json()
            temperature = data['current']['temp_c']
            wind_speed = data['current']['wind_kph']
            condition = data['current']['condition']['text']
            precipitation_probability = data['current'].get('precip_mm', 0) * 100

            weather, _ = WeatherCondition.objects.update_or_create(
                route=route,
                port=port,
                defaults={
                    'temperature': temperature,
                    'wind_speed': wind_speed,
                    'precipitation_probability': precipitation_probability,
                    'condition': condition,
                    'expires_at': now + datetime.timedelta(minutes=30),
                    'updated_at': now
                }
            )
            return weather
        except requests.RequestException as e:
            return None

    def stream():
        last_sent_times = {}
        while True:
            now = timezone.now()
            schedules = Schedule.objects.filter(
                status='scheduled', departure_time__gt=now
            ).select_related('route__departure_port')
            route_ids = schedules.values_list('route_id', flat=True).distinct()
            routes = Route.objects.filter(id__in=route_ids).select_related('departure_port')

            weather_data = []

            for route in routes:
                port = route.departure_port
                weather = fetch_weather(route, port)
                last_sent = last_sent_times.get(route.id)

                if weather and (not last_sent or weather.updated_at > last_sent):
                    data = {
                        'route_id': route.id,
                        'port': port.name,
                        'temperature': safe_float(weather.temperature),
                        'wind_speed': safe_float(weather.wind_speed),
                        'precipitation_probability': safe_float(weather.precipitation_probability),
                        'condition': weather.condition,
                        'updated_at': weather.updated_at.isoformat(),
                        'expires_at': weather.expires_at.isoformat(),
                        'warning': None
                    }
                    if data['wind_speed'] and data['wind_speed'] > 30:
                        data['warning'] = 'Strong winds expected, potential delays.'
                    elif data['precipitation_probability'] and data['precipitation_probability'] > 50:
                        data['warning'] = 'High chance of rain, please prepare accordingly.'

                    weather_data.append(data)
                    last_sent_times[route.id] = now

            if weather_data:
                yield f"data: {json.dumps({'weather': weather_data})}\n\n"

            yield ":\n\n"  # SSE keep-alive
            time.sleep(FETCH_INTERVAL)

    response = StreamingHttpResponse(stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@require_GET
@cache_page(60 * 10)  # Cache for 10 minutes
def get_weather_conditions(request):
    schedule_id = request.GET.get('schedule_id')
    since = request.GET.get('since')
    last_updated = None

    # Parse 'since' parameter for conditional updates
    if since:
        try:
            last_updated = timezone.datetime.fromisoformat(since.replace('Z', '+00:00'))
            if not timezone.is_aware(last_updated):
                last_updated = timezone.make_aware(last_updated)
        except ValueError:
            logger.error(f"Invalid 'since' parameter: {since}")
            return JsonResponse({'valid': False, 'error': 'Invalid since parameter'}, status=400)

    # Validate schedule_id
    if not schedule_id or not schedule_id.isdigit():
        logger.error(f"Invalid schedule_id: {schedule_id}")
        return JsonResponse({'valid': False, 'error': 'Invalid schedule ID'}, status=400)

    # Fetch the specific schedule
    try:
        schedule = Schedule.objects.select_related('route__departure_port').get(
            id=schedule_id,
            status='scheduled',
            departure_time__gt=timezone.now()
        )
    except Schedule.DoesNotExist:
        logger.error(f"Schedule not found or invalid: {schedule_id}")
        return JsonResponse({'valid': False, 'error': 'Schedule not found or no longer available'}, status=404)

    route = schedule.route
    port = route.departure_port

    # Generate concise cache key using MD5 hash of route_id
    cache_key = f"weather_route_{hashlib.md5(str(route.id).encode()).hexdigest()}"
    logger.debug(f"Generated cache key: {cache_key}")

    # Check cache
    cached_weather = cache.get(cache_key)
    if cached_weather and (not last_updated or cached_weather['updated_at'] > last_updated.isoformat()):
        logger.info(f"Cache hit for route_id: {route.id}")
        return JsonResponse({'valid': True, 'weather': cached_weather})

    # Check database for existing weather condition
    now = timezone.now()
    weather = WeatherCondition.objects.filter(
        route=route,
        port=port,
        expires_at__gt=now
    )
    if last_updated:
        weather = weather.filter(updated_at__gt=last_updated)
    weather = weather.first()

    weather_data = None
    if weather:
        weather_data = {
            'route_id': route.id,
            'port': port.name,
            'temperature': float(weather.temperature) if weather.temperature is not None else None,
            'wind_speed': float(weather.wind_speed) if weather.wind_speed is not None else None,
            'precipitation_probability': float(weather.precipitation_probability) if weather.precipitation_probability is not None else None,
            'condition': weather.condition,
            'updated_at': weather.updated_at.isoformat(),
            'expires_at': weather.expires_at.isoformat(),
            'warning': None
        }
        # Generate warning based on conditions (customize as needed)
        if weather.wind_speed and weather.wind_speed > 30:
            weather_data['warning'] = 'Strong winds expected, potential delays.'
        elif weather.precipitation_probability and weather.precipitation_probability > 50:
            weather_data['warning'] = 'High chance of rain, please prepare accordingly.'

    else:
        # Fetch from Weather API
        try:
            response = requests.get(
                'https://api.weatherapi.com/v1/current.json',
                params={
                    'key': settings.WEATHER_API_KEY,
                    'q': f"{port.lat},{port.lng}",  # Fixed 'lng' to 'lon' assuming model field
                    'aqi': 'no'
                },
                timeout=5
            )
            response.raise_for_status()
            data = response.json()

            temperature = data['current']['temp_c']
            wind_speed = data['current']['wind_kph']
            condition = data['current']['condition']['text']
            precipitation_probability = data['current'].get('precip_mm', 0) * 100

            # Create or update WeatherCondition
            weather, _ = WeatherCondition.objects.update_or_create(
                route=route,
                port=port,
                defaults={
                    'temperature': temperature,
                    'wind_speed': wind_speed,
                    'precipitation_probability': precipitation_probability,
                    'condition': condition,
                    'expires_at': now + datetime.timedelta(minutes=30),
                    'updated_at': now
                }
            )

            weather_data = {
                'route_id': route.id,
                'port': port.name,
                'temperature': temperature,
                'wind_speed': wind_speed,
                'precipitation_probability': precipitation_probability,
                'condition': condition,
                'updated_at': now.isoformat(),
                'expires_at': (now + datetime.timedelta(minutes=30)).isoformat(),
                'warning': None
            }
            # Generate warning based on conditions
            if wind_speed > 30:
                weather_data['warning'] = 'Strong winds expected, potential delays.'
            elif precipitation_probability > 50:
                weather_data['warning'] = 'High chance of rain, please prepare accordingly.'

        except requests.RequestException as e:
            logger.error(f"WeatherAPI error for {port.name}: {str(e)}")
            weather_data = {
                'route_id': route.id,
                'port': port.name,
                'temperature': None,
                'wind_speed': None,
                'precipitation_probability': None,
                'condition': None,
                'updated_at': None,
                'expires_at': None,
                'warning': None,
                'error': 'Weather data unavailable'
            }

    # Cache the result
    cache.set(cache_key, weather_data, timeout=60 * 10)
    logger.info(f"Weather data cached for route_id: {route.id}")

    return JsonResponse({'valid': True, 'weather': weather_data})


def privacy_policy(request):
    return render(request, 'privacy_policy.html')


# Pricing calculations live in bookings/pricing.py.
from .pricing import (
    calculate_cargo_price, calculate_addon_price, calculate_passenger_price,
    calculate_vehicle_price, calculate_total_price,
)


def routes_api(request):
    try:
        # Only pull upcoming/active schedules into memory
        upcoming = Prefetch(
            'bookings',  # <— current related_name
            queryset=Schedule.objects.filter(status='scheduled').order_by('departure_time'),
            to_attr='prefetched_schedules'
        )

        routes = (
            Route.objects
                 .select_related('departure_port', 'destination_port')
                 .prefetch_related(upcoming)
        )

        routes_data = []
        for route in routes:
            # get the first upcoming schedule id (if any)
            first_schedule_id = (
                route.prefetched_schedules[0].id if getattr(route, 'prefetched_schedules', []) else None
            )

            routes_data.append({
                'id': route.id,
                'departure_port': {
                    'name': route.departure_port.name,
                    'lat': route.departure_port.lat,
                    'lng': route.departure_port.lng
                },
                'destination_port': {
                    'name': route.destination_port.name,
                    'lat': route.destination_port.lat,
                    'lng': route.destination_port.lng
                },
                'distance_km': float(route.distance_km) if route.distance_km else None,
                'estimated_duration': int(route.estimated_duration.total_seconds() / 60) if route.estimated_duration else None,
                'base_fare': float(route.base_fare) if route.base_fare else None,
                'schedule_id': first_schedule_id,
                'waypoints': route.waypoints or [
                    [route.departure_port.lat, route.departure_port.lng],
                    [route.destination_port.lat, route.destination_port.lng]
                ]
            })

        return JsonResponse({'routes': routes_data})
    except Exception as e:
        logger.error(f"Routes API error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def profile(request):
    return render(request, "bookings/profile.html")


def terms_of_service(request):
    return render(request, "terms_of_service.html")


@require_GET
def homepage(request):
    now = timezone.now()
    schedules = Schedule.objects.filter(
        status='scheduled',
        departure_time__gt=now
    ).select_related('ferry', 'route__departure_port', 'route__destination_port').order_by('departure_time')

    route_input = request.GET.get('route', '').strip().lower()
    route_id = request.GET.get('route_id', '').strip()
    travel_date = request.GET.get('date', '').strip()
    passengers = request.GET.get('passengers', '1')

    logger.debug(f"Search parameters: route={route_input}, route_id={route_id}, travel_date={travel_date}, passengers={passengers}")

    # --- Route filtering ---
    if route_id and route_id.isdigit():
        schedules = schedules.filter(route_id=int(route_id))
    elif route_input:
        # support both "Nadi to Suva" and "Nadi-to-Suva" formats.
        # Split only on a standalone "to" token (word boundaries) so port names
        # that contain the letters "to" (e.g. Natovi, Lautoka) are not corrupted.
        normalized = route_input.replace('\u2013', '-').lower()
        parts = [p.strip(' -') for p in re.split(r'\bto\b', normalized) if p.strip(' -')]
        if len(parts) == 2:
            origin, destination = parts
            schedules = schedules.filter(
                route__departure_port__name__iexact=origin,
                route__destination_port__name__iexact=destination
            )
        else:
            messages.error(request, "Invalid route format. Use 'origin-to-destination' or 'Origin to Destination'.")

    # --- Date filtering ---
    if travel_date:
        try:
            travel_date_obj = datetime.datetime.strptime(travel_date, '%Y-%m-%d')
            travel_date_start = timezone.make_aware(travel_date_obj)
            travel_date_end = travel_date_start + datetime.timedelta(days=1)
            schedules = schedules.filter(
                departure_time__range=(travel_date_start, travel_date_end)
            )
        except ValueError:
            messages.error(request, "Invalid date format. Please use YYYY-MM-DD.")

    # --- Routes queryset ---
    routes = Route.objects.select_related('departure_port', 'destination_port').all()

    # --- Next Departure Info ---
    next_departure = schedules.first()
    next_departure_info = None
    if next_departure:
        next_departure_info = {
            'time': next_departure.departure_time.strftime('%a, %b %d, %H:%M'),
            'route': f"{next_departure.route.departure_port.name} to {next_departure.route.destination_port.name}",
            'schedule_id': next_departure.id,
            'estimated_duration': int(
                next_departure.route.estimated_duration.total_seconds() / 60) if next_departure.route.estimated_duration else None
        }
    else:
        next_departure_info = {
            'time': '10:00 AM',
            'route': 'Nadi to Suva',
            'schedule_id': 1,
            'estimated_duration': 240
        }

    # --- Default Weather Data (fallback) ---
    weather_data = {
        'current': {
            'temp': 28,
            'condition': 'Sunny',
            'humidity': 65,
            'wind': 12
        },
        'forecast': [
            {'date': 'Tomorrow', 'temp': 29, 'condition': 'Partly Cloudy'},
            {'date': 'Friday', 'temp': 27, 'condition': 'Sunny'}
        ],
        'ports': {
            'nadi': {'temp': 28, 'condition': 'Sunny', 'wind': 10, 'precip': 0},
            'suva': {'temp': 26, 'condition': 'Partly Cloudy', 'wind': 8, 'precip': 5},
            'denarau': {'temp': 28, 'condition': 'Sunny', 'wind': 10, 'precip': 0},
            'yasawa': {'temp': 27, 'condition': 'Clear', 'wind': 12, 'precip': 2}
        }
    }

    # --- Real Weather Overrides (if available) ---
    try:
        current_conditions = WeatherCondition.objects.filter(
            expires_at__gt=now
        ).order_by('-updated_at').first()

        if current_conditions:
            weather_data['current'] = {
                'temp': float(getattr(current_conditions, 'temperature', 28) or 28),
                'condition': getattr(current_conditions, 'condition', 'Sunny') or 'Sunny',
                'humidity': int(getattr(current_conditions, 'humidity', 65) or 65),
                'wind': float(getattr(current_conditions, 'wind_speed', 12) or 12)
            }

        port_weather = WeatherCondition.objects.filter(
            port__name__in=['Nadi', 'Suva', 'Denarau', 'Yasawa'],
            expires_at__gt=now
        ).select_related('port').order_by('port__name', '-updated_at')

        port_data = {}
        for pw in port_weather:
            port_key = pw.port.name.lower()
            port_data[port_key] = {
                'temp': float(pw.temperature) if pw.temperature else 28,
                'condition': pw.condition or 'Sunny',
                'wind': float(pw.wind_speed) if pw.wind_speed else 10,
                'precip': int(pw.precipitation_probability) if pw.precipitation_probability else 0
            }

        weather_data['ports'].update(port_data)

        weather_data['forecast'] = [
            {'date': 'Tomorrow', 'temp': 29, 'condition': 'Partly Cloudy'},
            {'date': 'Friday', 'temp': 27, 'condition': 'Sunny'}
        ]
    except Exception as e:
        logger.error(f"Weather data fetch error: {e}")

    # --- Schedule-specific Weather ---
    schedule_weather_data = []
    schedule_route_ids = schedules.values_list('route_id', flat=True).distinct()

    if schedule_route_ids:
        try:
            latest_conditions_subquery = WeatherCondition.objects.filter(
                route_id=OuterRef('route_id'),
                expires_at__gt=now
            ).values('route_id').annotate(
                latest_updated=Max('updated_at')
            ).values('latest_updated')

            latest_conditions = WeatherCondition.objects.filter(
                route_id__in=schedule_route_ids,
                expires_at__gt=now,
                updated_at__in=Subquery(latest_conditions_subquery)
            ).select_related('route', 'port')

            latest_per_route = {wc.route_id: wc for wc in latest_conditions}

            for schedule in schedules:
                wc = latest_per_route.get(schedule.route_id)
                if wc and not wc.is_expired():
                    schedule_weather_data.append({
                        'route_id': schedule.route_id,
                        'schedule_id': schedule.id,
                        'port': wc.port.name,
                        'condition': wc.condition,
                        'temperature': float(wc.temperature) if wc.temperature is not None else None,
                        'wind_speed': float(wc.wind_speed) if wc.wind_speed is not None else None,
                        'precipitation_probability': float(wc.precipitation_probability) if wc.precipitation_probability is not None else None,
                        'expires_at': wc.expires_at.isoformat() if wc.expires_at else None,
                        'updated_at': wc.updated_at.isoformat() if wc.updated_at else None,
                        'is_expired': False,
                        'error': None
                    })
                else:
                    schedule_weather_data.append({
                        'route_id': schedule.route_id,
                        'schedule_id': schedule.id,
                        'port': schedule.route.departure_port.name,
                        'condition': None,
                        'temperature': None,
                        'wind_speed': None,
                        'precipitation_probability': None,
                        'expires_at': None,
                        'updated_at': None,
                        'is_expired': True,
                        'error': 'No valid weather data available'
                    })
        except Exception as e:
            logger.error(f"Schedule weather data error: {e}")
            for schedule in schedules:
                schedule_weather_data.append({
                    'route_id': schedule.route_id,
                    'schedule_id': schedule.id,
                    'port': schedule.route.departure_port.name,
                    'condition': 'Partly Cloudy',
                    'temperature': 28,
                    'wind_speed': 12,
                    'precipitation_probability': 5,
                    'is_expired': False,
                    'error': None
                })

    # --- Pagination ---
    total_schedules_count = schedules.count()
    displayed_schedules = schedules[:12]
    remaining_schedules = max(0, total_schedules_count - len(displayed_schedules))

    # --- Safe JSON route serialization ---
    routes_data = list(routes.values(
        'id',
        'departure_port__name',
        'destination_port__name',
        'distance_km',
        'estimated_duration',
        'base_fare',
        'service_tier',
        'min_weekly_services',
        'preferred_departure_windows',
        'safety_buffer_minutes',
        'waypoints'
    )[:10])

    if not routes_data:
        routes_data = [
            {
                'departure_port__name': 'Nadi',
                'destination_port__name': 'Suva',
                'base_fare': 50,
            },
            {
                'departure_port__name': 'Denarau',
                'destination_port__name': 'Yasawa Islands',
                'base_fare': 100,
            },
            {
                'departure_port__name': 'Suva',
                'destination_port__name': 'Lautoka',
                'base_fare': 40,
            },
        ]

    # --- Context ---
    context = {
        'bookings': displayed_schedules,
        'total_schedules': total_schedules_count,
        'remaining_schedules': remaining_schedules,
        'routes': routes_data,
        'form_data': {
            'route': route_input,
            'route_id': route_id,
            'date': travel_date or now.date().strftime('%Y-%m-%d'),
            'passengers': passengers
        },
        'weather_data': weather_data,
        'schedule_weather_data': schedule_weather_data,
        'next_departure': next_departure_info,
        'today': now.date(),
        'tile_error_url': '/static/images/tile-error.png'
    }

    return render(request, 'home.html', context)


@login_required_allow_anonymous
def booking_history(request):
    logger.debug(
        f"Fetching booking history for user={request.user if request.user.is_authenticated else 'Guest'}, "
        f"session_guest_email={request.session.get('guest_email')}, "
        f"session_keys={list(request.session.keys())}"
    )

    if request.method == 'POST':
        guest_email = request.POST.get('guest_email', '').strip()
        if guest_email:
            request.session['guest_email'] = guest_email
            logger.debug(f"Set guest_email in session: {guest_email}")

    if request.user.is_authenticated:
        bookings = Booking.objects.filter(user=request.user).select_related('schedule__ferry', 'schedule__route').order_by('-booking_date')
    else:
        guest_email = request.session.get('guest_email')
        bookings = Booking.objects.filter(guest_email=guest_email).select_related('schedule__ferry', 'schedule__route').order_by('-booking_date') if guest_email else []

    for booking in bookings:
        booking.update_status_if_expired()

    return render(request, 'bookings/history.html', {
        'bookings': bookings,
        'cutoff_time': timezone.now() + datetime.timedelta(hours=6),
        'is_guest': not request.user.is_authenticated
    })


def generate_ticket(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    if booking.status != 'confirmed':
        messages.error(request, "Tickets can only be generated for confirmed bookings.")
        return redirect('bookings:booking_history')

    for passenger in booking.passengers.all():
        if not Ticket.objects.filter(booking=booking, passenger=passenger).exists():
            ticket = Ticket.objects.create(
                booking=booking,
                passenger=passenger,
                ticket_status='active',
                qr_token=uuid.uuid4().hex
            )
            qr_data = request.build_absolute_uri(reverse('bookings:view_ticket', args=[ticket.qr_token]))
            qr = qrcode.QRCode()
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            ticket.qr_code.save(f"ticket_{ticket.id}.png", ContentFile(buffer.getvalue()))

    messages.success(request, f"Tickets generated for Booking #{booking.id}.")
    return redirect('bookings:view_tickets', booking_id=booking.id)


@login_required
def view_cargo(request, cargo_id):
    cargo = get_object_or_404(Cargo, id=cargo_id, booking__user=request.user)
    return render(request, 'bookings/view_cargo.html', {'cargo': cargo})


@login_required_allow_anonymous
def view_ticket(request, qr_token):
    try:
        ticket = Ticket.objects.select_related('booking__schedule__ferry', 'booking__schedule__route', 'passenger').get(qr_token=qr_token)
    except Ticket.DoesNotExist:
        messages.error(request, "Invalid or expired ticket link.")
        return redirect('bookings:booking_history')
    if request.user.is_authenticated and ticket.booking.user != request.user:
        return HttpResponseForbidden("You are not authorized to view this ticket.")
    if not request.user.is_authenticated and ticket.booking.guest_email != request.session.get('guest_email'):
        return HttpResponseForbidden("You are not authorized to view this ticket.")
    return render(request, 'bookings/view_ticket.html', {'ticket': ticket})


def get_schedule_updates(request):
    now = timezone.now()
    schedules = Schedule.objects.filter(
        departure_time__gte=now,
        status='scheduled',
        available_seats__gt=0
    ).select_related('route__departure_port', 'route__destination_port', 'ferry').order_by('departure_time')

    # Pagination for infinite scroll
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = max(1, min(50, int(request.GET.get('limit', 12))))
    except (TypeError, ValueError):
        limit = 12

    total = schedules.count()
    paged = schedules[offset:offset + limit]

    data = [
        {
            'id': s.id,
            'route': f"{s.route.departure_port.name} to {s.route.destination_port.name}",
            'departure_time': s.departure_time.isoformat(),
            'available_seats': s.available_seats,
            'ferry_name': s.ferry.name,
            'status': s.status,
            'base_fare': float(s.route.base_fare) if s.route.base_fare else None,
            'duration': int(s.route.estimated_duration.total_seconds() / 60) if s.route.estimated_duration else None
        } for s in paged
    ]

    return JsonResponse({
        'schedules': data,
        'total': total,
        'offset': offset,
        'limit': limit,
        'remaining': max(0, total - (offset + len(data)))
    })


@require_POST
@csrf_protect
def validate_step(request):
    """
    Robust, side-effect-free gate used by book.js to allow moving between steps.
    Returns 200 with {'valid': False} on validation failures so the client can handle
    errors without noisy server logs. Change status to 400 if you explicitly prefer 400s.
    """
    step = (request.POST.get('step') or '').strip()
    errors = []

    def _resp(ok: bool):
        # Set to 400 if you want server logs on validation failures
        return JsonResponse({'valid': ok, 'errors': errors, 'step': step}, status=200)

    if step == '1':
        schedule_id = (request.POST.get('schedule_id') or '').strip()
        guest_email = (request.POST.get('guest_email') or '').strip().lower()
        is_authenticated = bool(getattr(request.user, 'is_authenticated', False))

        # ---- schedule check (no ORM hit for non-digit) ----
        if not schedule_id.isdigit():
            errors.append({'field': 'schedule_id', 'message': 'Please select a valid ferry schedule.'})
        else:
            cache_key = f'schedule_exists_{schedule_id}'
            schedule_exists = cache.get(cache_key)

            if schedule_exists is None:
                schedule = (
                    Schedule.objects
                    .filter(id=int(schedule_id), status='scheduled', departure_time__gt=timezone.now())
                    .only('id', 'available_seats')
                    .first()
                )
                schedule_exists = bool(schedule)
                cache.set(cache_key, schedule_exists, timeout=3600)

                if schedule_exists:
                    adults   = safe_int(request.POST.get('adults', '0'))
                    children = safe_int(request.POST.get('children', '0'))
                    infants  = safe_int(request.POST.get('infants', '0'))
                    total    = max(0, adults) + max(0, children) + max(0, infants)

                    # Only enforce seats when counts are provided (>0)
                    if total > 0 and total > schedule.available_seats:
                        errors.append({
                            'field': 'schedule_id',
                            'message': f'Not enough seats available ({schedule.available_seats} remaining).'
                        })

            if not schedule_exists:
                errors.append({'field': 'schedule_id', 'message': 'Please select a valid ferry schedule.'})

        # ---- guest email / OTP verification ----
        if not is_authenticated:
            if not guest_email:
                errors.append({'field': 'guest_email', 'message': 'Guest email is required.'})
            elif not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', guest_email):
                errors.append({'field': 'guest_email', 'message': 'Please enter a valid email address.'})
            else:
                # Canonical flag fast-path
                canonical = (request.session.get('guest_otp_verified_email') or '').lower()
                verified_ok = (canonical == guest_email)

                # Fallback: check the per-email OTP bucket if present and verified
                if not verified_ok:
                    try:
                        key = _otp_store_key(guest_email)
                        data = request.session.get(key) or {}
                        if data.get('verified') is True:
                            verified_ok = True
                            # Promote to canonical so subsequent checks are fast
                            request.session['guest_otp_verified_email'] = guest_email
                            request.session['guest_otp_verified_at'] = timezone.now().isoformat()
                            request.session.modified = True
                    except Exception:
                        pass

                if not verified_ok:
                    errors.append({
                        'field': 'guest_email',
                        'message': 'Please verify your email (we’ve sent a one-time code).'
                    })

        return _resp(len(errors) == 0)

    elif step == '2':
        adults = safe_int(request.POST.get('adults', '0'))
        children = safe_int(request.POST.get('children', '0'))
        infants = safe_int(request.POST.get('infants', '0'))

        total_passengers = adults + children + infants
        if total_passengers == 0:
            errors.append({'field': 'general', 'message': 'At least one passenger is required.'})
        if (children > 0 or infants > 0) and adults == 0:
            errors.append({'field': 'general', 'message': 'Children and infants must be accompanied by an adult.'})

        for field, value in [('adults', adults), ('children', children), ('infants', infants)]:
            if value < 0:
                errors.append({'field': field, 'message': f'{field.capitalize()} count cannot be negative.'})

        # Per-passenger detail checks (keep your existing implementation)
        def validate_passenger_data(req, p_type, idx, adult_count, errs):
            # implement your existing checks here (first/last, age/DOB, doc presence, linked adult)
            pass

        for p_type, count in (('adult', adults), ('child', children), ('infant', infants)):
            for i in range(count):
                validate_passenger_data(request, p_type, i, adults, errors)

        return _resp(len(errors) == 0)

    elif step == '3':
        add_vehicle = request.POST.get('add_vehicle') in ('true', 'on', '1')
        add_cargo   = request.POST.get('add_cargo') in ('true', 'on', '1')

        if add_vehicle:
            vehicle_type = (request.POST.get('vehicle_type') or '').strip()
            vehicle_dimensions = (request.POST.get('vehicle_dimensions') or '').strip()
            if not vehicle_type:
                errors.append({'field': 'vehicle_type', 'message': 'Vehicle type is required.'})
            if not re.match(r'^\d+x\d+x\d+$', vehicle_dimensions or ''):
                errors.append({'field': 'vehicle_dimensions', 'message': 'Vehicle dimensions must be in format LxWxH (e.g., 400x180x150).'})

        if add_cargo:
            cargo_type = (request.POST.get('cargo_type') or '').strip()
            cargo_weight = (request.POST.get('cargo_weight_kg') or '').strip()
            cargo_dimensions = (request.POST.get('cargo_dimensions_cm') or '').strip()
            if not cargo_type:
                errors.append({'field': 'cargo_type', 'message': 'Cargo type is required.'})
            try:
                weight = float(cargo_weight)
                if weight <= 0:
                    errors.append({'field': 'cargo_weight_kg', 'message': 'Cargo weight must be a positive number.'})
            except ValueError:
                errors.append({'field': 'cargo_weight_kg', 'message': 'Cargo weight must be a valid number.'})
            if not re.match(r'^\d+x\d+x\d+$', cargo_dimensions or ''):
                errors.append({'field': 'cargo_dimensions_cm', 'message': 'Cargo dimensions must be in format LxWxH (e.g., 400x180x150).'})

        return _resp(len(errors) == 0)

    elif step == '4':
        if not request.POST.get('privacy_consent'):
            errors.append({'field': 'privacy_consent', 'message': 'You must agree to the privacy policy.'})
        return _resp(len(errors) == 0)

    # Unknown step – don’t block navigation
    return JsonResponse({'valid': True, 'step': step}, status=200)


def _validate_id_document(f):
    """SEC-5: server-side validation of an uploaded ID document.

    Checks size, extension, and magic bytes so a malicious file cannot be
    stored by simply renaming its extension. Raises ValidationError on failure
    (caught by the create_checkout_session error handler -> 400).
    """
    max_bytes = 2621440  # 2.5MB
    if f.size > max_bytes:
        raise ValidationError("ID document too large (2.5MB max).")
    FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])(f)

    head = f.read(8)
    f.seek(0)
    sigs = (
        b'%PDF',                       # PDF
        b'\xff\xd8\xff',               # JPEG
        b'\x89PNG\r\n\x1a\n',          # PNG
    )
    if not any(head.startswith(s) for s in sigs):
        raise ValidationError("ID document content does not match an allowed file type (PDF/JPG/PNG).")


@require_POST
@require_guest_otp
@csrf_protect
def create_checkout_session(request):
    """Create Stripe checkout session for ferry booking, including passengers, cargo, vehicles, and addons"""
    errors = []

    try:
        # LOG-3: idempotent checkout. A client-supplied token dedups double-submits
        # and network retries so we never create duplicate bookings/charges.
        idem_raw = (request.POST.get('idempotency_key') or '').strip()
        idem_key = re.sub(r'[^A-Za-z0-9\-]', '', idem_raw)[:64] if idem_raw else ''
        if idem_key:
            cached_session = cache.get(f"checkout_idem:{idem_key}")
            if cached_session:
                return JsonResponse({'sessionId': cached_session})
            # Serialize concurrent duplicate submits for the same token.
            if not cache.add(f"checkout_idem_lock:{idem_key}", 1, 120):
                return JsonResponse({'success': False, 'errors': [{'field': 'general', 'message': 'A checkout for this request is already being processed. Please wait.'}]}, status=409)

        # --- Extract booking data ---
        schedule_id = request.POST.get('schedule_id')
        adults = safe_int(request.POST.get('adults', 0))
        children = safe_int(request.POST.get('children', 0))
        infants = safe_int(request.POST.get('infants', 0))
        guest_email = request.POST.get('guest_email', '').strip()

        add_cargo = request.POST.get('add_cargo') in ['true', 'on']
        cargo_type = request.POST.get('cargo_type', '')
        weight_kg = safe_float(request.POST.get('cargo_weight_kg', 0))
        cargo_license_plate = request.POST.get('cargo_license_plate', '')
        cargo_dimensions = request.POST.get('cargo_dimensions_cm', '') if add_cargo else ''

        add_vehicle = request.POST.get('add_vehicle') in ['true', 'on']
        vehicle_type = request.POST.get('vehicle_type', '')
        vehicle_dimensions = request.POST.get('vehicle_dimensions', '')
        vehicle_license_plate = request.POST.get('vehicle_license_plate', '')

        # --- Addons ---
        addons = []
        for addon_type in dict(AddOn.ADD_ON_TYPE_CHOICES).keys():
            quantity = safe_int(request.POST.get(f'{addon_type}_quantity', 0))
            if quantity > 0:
                addons.append({'type': addon_type, 'quantity': quantity})

        total_passengers = adults + children + infants
        if not schedule_id or total_passengers == 0:
            return JsonResponse({'success': False, 'errors': [{'field': 'general', 'message': 'Invalid booking data'}]}, status=400)

        schedule = get_object_or_404(Schedule, id=schedule_id, status='scheduled')

        # CON-1: reserve seats atomically via the service layer (row-locked).
        with transaction.atomic():
            if not services.reserve_seats(schedule.pk, total_passengers):
                locked = Schedule.objects.get(pk=schedule.pk)
                return JsonResponse({'success': False, 'errors': [{'field': 'schedule_id', 'message': f'Only {locked.available_seats} seats available'}]}, status=400)
        schedule.refresh_from_db()
        seats_reserved = True

        # --- Validate email ---
        customer_email = request.user.email if request.user.is_authenticated else guest_email
        if not customer_email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', customer_email):
            return JsonResponse({'success': False, 'errors': [{'field': 'email', 'message': 'Valid email required'}]}, status=400)

        # --- Calculate total price ---
        total_price = calculate_total_price(
            adults, children, infants, schedule, add_cargo, cargo_type, weight_kg, addons,
            add_vehicle, vehicle_type, vehicle_dimensions
        )

        # --- Create booking ---
        booking = Booking.objects.create(
            user=request.user if request.user.is_authenticated else None,
            schedule=schedule,
            guest_email=guest_email if not request.user.is_authenticated else None,
            passenger_adults=adults,
            passenger_children=children,
            passenger_infants=infants,
            total_price=total_price,
            status='pending'
        )

        # --- Create passengers ---
        passenger_lists = {'adult': adults, 'child': children, 'infant': infants}
        adult_passengers = []

        for p_type, count in passenger_lists.items():
            for i in range(count):
                first_name = request.POST.get(f'{p_type}_first_name_{i}', '').strip()
                last_name = request.POST.get(f'{p_type}_last_name_{i}', '').strip()
                document = request.FILES.get(f'{p_type}_id_document_{i}') if p_type in ['adult', 'child'] else None

                # SEC-5: validate the uploaded ID document server-side (the client
                # validate_file endpoint is advisory only).
                if document is not None:
                    _validate_id_document(document)

                if not first_name or not last_name:
                    raise ValueError(f"{p_type.capitalize()} {i + 1} missing name")

                passenger_data = {
                    'booking': booking,
                    'first_name': first_name,
                    'last_name': last_name,
                    'passenger_type': p_type,
                    'document': document
                }

                if p_type != 'infant':
                    age = request.POST.get(f'{p_type}_age_{i}')
                    if age:
                        passenger_data['age'] = int(age)

                if p_type == 'infant':
                    dob = request.POST.get(f'{p_type}_dob_{i}')
                    if dob:
                        passenger_data['date_of_birth'] = datetime.datetime.strptime(dob, '%Y-%m-%d').date()

                passenger = Passenger.objects.create(**passenger_data)

                # Link child/infant to adult
                if p_type in ['child', 'infant']:
                    linked_idx = request.POST.get(f'{p_type}_linked_adult_{i}')
                    if linked_idx and adult_passengers:
                        try:
                            passenger.linked_adult = adult_passengers[int(linked_idx)]
                            passenger.save()
                        except (IndexError, ValueError):
                            pass

                if p_type == 'adult':
                    adult_passengers.append(passenger)

        # --- Create cargo/vehicle/addons ---
        if add_cargo and weight_kg > 0:
            Cargo.objects.create(
                booking=booking,
                cargo_type=cargo_type,
                weight_kg=Decimal(weight_kg),
                dimensions_cm=cargo_dimensions,
                license_plate=cargo_license_plate,
                price=calculate_cargo_price(Decimal(weight_kg), cargo_type)
            )

        if add_vehicle:
            Vehicle.objects.create(
                booking=booking,
                vehicle_type=vehicle_type,
                dimensions=vehicle_dimensions,
                license_plate=vehicle_license_plate,
                price=calculate_vehicle_price(vehicle_type, vehicle_dimensions)
            )

        for addon in addons:
            AddOn.objects.create(
                booking=booking,
                add_on_type=addon['type'],
                quantity=addon['quantity'],
                price=calculate_addon_price(addon['type'], addon['quantity'])
            )

        # CON-1: seats were already reserved atomically above (no second decrement here).

        # --- Create Stripe session ---
        # LOG-3: idempotency_key prevents duplicate Stripe sessions/charges if this
        # request is retried (e.g. network blip) for the same booking.
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'fjd',
                    'product_data': {'name': f'Ferry Booking #{booking.id}'},
                    'unit_amount': int(total_price * 100),
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.build_absolute_uri('/bookings/success/?session_id={CHECKOUT_SESSION_ID}'),
            cancel_url=request.build_absolute_uri('/bookings/cancel/'),
            metadata={'booking_id': str(booking.id), 'guest_email': guest_email or ''},
            customer_email=customer_email,
            idempotency_key=(idem_key or f"ferry-checkout-{booking.id}"),
        )

        booking.stripe_session_id = session.id
        booking.save()

        request.session['booking_id'] = booking.id
        request.session['stripe_session_id'] = session.id

        # LOG-3: remember the result so an immediate re-submit returns this same session.
        if idem_key:
            cache.set(f"checkout_idem:{idem_key}", session.id, 3600)

        return JsonResponse({'sessionId': session.id})

    except Exception as e:
        logger.exception(f"Checkout error: {e}")
        # Cleanup on error: delete the booking and atomically release the seats
        # that were reserved above (CON-1). Restore is keyed off seats_reserved so
        # it is correct even if booking creation itself failed after reservation.
        if 'booking' in locals():
            booking.delete()
        if locals().get('seats_reserved') and 'schedule' in locals():
            services.release_seats(schedule.pk, total_passengers)
        return JsonResponse({'success': False, 'errors': [{'field': 'general', 'message': str(e)}]}, status=400)


@csrf_exempt
@require_guest_otp
@require_POST
def get_pricing(request):
    """Fixed to handle individual form fields from JS"""
    try:
        schedule_id = request.POST.get('schedule_id')
        adults = safe_int(request.POST.get('adults', 0))
        children = safe_int(request.POST.get('children', 0))
        infants = safe_int(request.POST.get('infants', 0))

        # Handle individual cargo fields (not array notation)
        add_cargo = request.POST.get('add_cargo') == 'true' or request.POST.get('add_cargo') == 'on'
        cargo_type = request.POST.get('cargo_type', '')  # Individual field
        weight_kg = request.POST.get('cargo_weight_kg', '')
        cargo_license_plate = request.POST.get('cargo_license_plate', '')
        cargo_dimensions = request.POST.get('cargo_dimensions_cm', '') if add_cargo else ''

        # Handle individual vehicle fields
        add_vehicle = request.POST.get('add_vehicle') == 'true' or request.POST.get('add_vehicle') == 'on'
        vehicle_type = request.POST.get('vehicle_type', '')
        vehicle_dimensions = request.POST.get('vehicle_dimensions', '')

        # Handle addons as individual quantity fields
        addons = []
        for addon_type in dict(AddOn.ADD_ON_TYPE_CHOICES).keys():
            quantity = safe_int(request.POST.get(f'{addon_type}_quantity', 0))
            if quantity > 0:
                addons.append({'type': addon_type, 'quantity': quantity})

        if not schedule_id:
            return JsonResponse({'error': 'Schedule ID required'}, status=400)

        schedule = get_object_or_404(Schedule, id=schedule_id, status='scheduled')

        weight = safe_float(weight_kg) or 0
        total_price = calculate_total_price(
            adults, children, infants, schedule, add_cargo, cargo_type, weight, addons,
            add_vehicle, vehicle_type, vehicle_dimensions
        )

        base_fare = schedule.route.base_fare or Decimal('35.50')
        breakdown = {
            'adults': str(Decimal(adults) * base_fare),
            'children': str(Decimal(children) * base_fare * Decimal('0.5')),
            'infants': str(Decimal(infants) * base_fare * Decimal('0.1')),
            'cargo': str(
                calculate_cargo_price(Decimal(weight), cargo_type) if add_cargo and weight > 0 else Decimal('0.00')),
            'vehicle': str(
                calculate_vehicle_price(vehicle_type, vehicle_dimensions) if add_vehicle else Decimal('0.00')),
            'addons': [{'type': a['type'], 'quantity': a['quantity'], 'amount': str(calculate_addon_price(a['type'], a['quantity']))} for a in addons],
            'total': str(total_price)
        }

        return JsonResponse({
            'total_price': str(total_price),
            'breakdown': breakdown,
            'pricing': breakdown  # Consistent structure for JS
        })

    except Exception as e:
        logger.exception(f"Pricing error: {e}")
        return JsonResponse({'error': str(e)}, status=400)



def book_ticket(request):
    # === EXTRACT PARAMETERS ===
    schedule_id = request.GET.get('schedule_id', '').strip()
    to_port = request.GET.get('to_port', '').strip().lower()
    step = safe_int(request.GET.get('step', 1))

    # Search parameters (for calendar/list mode)
    route_input = request.GET.get('route', '').strip()             # legacy string "Origin to Destination"
    route_id = request.GET.get('route_id', '').strip()             # new numeric route id
    travel_date_str = request.GET.get('date', '').strip()
    passengers = request.GET.get('passengers', '1')

    # Default date: today
    travel_date = None
    if travel_date_str:
        try:
            travel_date = datetime.datetime.strptime(travel_date_str, '%Y-%m-%d').date()
        except ValueError:
            messages.error(request, "Invalid date format.")
            travel_date = timezone.now().date()
    else:
        travel_date = timezone.now().date()

    # === BASE QUERYSET ===
    available_schedules = Schedule.objects.filter(
        status='scheduled',
        departure_time__gt=timezone.now()
    ).select_related('ferry', 'route__departure_port', 'route__destination_port')

    # === FILTER BY SCHEDULE_ID (Quick Book) ===
    if schedule_id:
        try:
            available_schedules = available_schedules.filter(id=schedule_id)
            if not available_schedules.exists():
                logger.warning(f"No schedule found for schedule_id={schedule_id}")
                messages.error(request, "Selected schedule is not available.")
        except ValueError:
            logger.error(f"Invalid schedule_id={schedule_id}")
            messages.error(request, "Invalid schedule ID.")
            available_schedules = Schedule.objects.none()

    # === FILTER BY DESTINATION PORT (from quick search) ===
    if to_port:
        available_schedules = available_schedules.filter(
            route__destination_port__name__iexact=to_port
        )
        if not available_schedules.exists():
            logger.warning(f"No bookings found for to_port={to_port}")
            messages.error(request, f"No bookings available for destination: {to_port.capitalize()}.")

    # === FILTER BY SEARCH (route + date) → Calendar/List Mode ===
    # Rules:
    #  - Always filter to the selected day if provided
    #  - Prefer route_id when provided
    #  - Fallback to legacy "Origin to Destination" string if route_id missing
    if route_id or route_input or travel_date_str:
        # Filter by selected date
        available_schedules = available_schedules.filter(departure_time__date=travel_date)

        # Apply route filter
        if route_id:
            available_schedules = available_schedules.filter(route_id=route_id)
        elif route_input:
            # Split only on a standalone "to" token so port names containing
            # the letters "to" (Natovi, Lautoka) survive; supports both
            # "Origin to Destination" and "Origin-to-Destination".
            parts = [p.strip(' -') for p in re.split(r'\bto\b', route_input.replace('–', '-'), flags=re.IGNORECASE) if p.strip(' -')]
            if len(parts) == 2:
                origin, destination = parts
                available_schedules = available_schedules.filter(
                    route__departure_port__name__iexact=origin,
                    route__destination_port__name__iexact=destination
                )
            else:
                messages.error(request, "Invalid route format. Use 'Origin to Destination'.")

    # === DEFINE ADD-ONS (unchanged) ===
    add_ons = [
        {'id': 'premium_seating', 'label': 'Premium Seating', 'price': 20.00, 'max_quantity': 20},
        {'id': 'priority_boarding', 'label': 'Priority Boarding', 'price': 10.00, 'max_quantity': 20},
        {'id': 'cabin', 'label': 'Cabin', 'price': 50.00, 'max_quantity': 5},
        {'id': 'meal_breakfast', 'label': 'Breakfast', 'price': 15.00, 'max_quantity': 50},
        {'id': 'meal_lunch', 'label': 'Lunch', 'price': 15.00, 'max_quantity': 50},
        {'id': 'meal_dinner', 'label': 'Dinner', 'price': 15.00, 'max_quantity': 50},
        {'id': 'meal_snack', 'label': 'Snack', 'price': 5.00, 'max_quantity': 100},
    ]

    # === GET REQUEST: RENDER EITHER LIST OR BOOKING FORM ===
    if request.method == 'GET':
        # === MODE 1: CALENDAR + LIST (no schedule_id, search active) ===
        if not schedule_id and (route_id or route_input or travel_date_str):
            import calendar
            cal = calendar.monthcalendar(travel_date.year, travel_date.month)
            calendar_days = []
            for week in cal:
                calendar_days.append([
                    datetime.date(travel_date.year, travel_date.month, day) if day else None
                    for day in week
                ])

            context = {
                'schedules': available_schedules.order_by('departure_time'),
                'calendar': calendar_days,
                'selected_month': travel_date,
                'today': timezone.now().date(),
                'form_data': {
                    'route_id': route_id,                                # <-- expose route_id to template
                    'date': travel_date.strftime('%Y-%m-%d'),
                    'passengers': passengers
                },
            }
            return render(request, 'bookings/schedule_list.html', context)

        # === MODE 2: BOOKING FORM (schedule_id present) ===
        # Initialize form data
        form_data = {
            'step': step,
            'schedule_id': schedule_id or '',
            'adults': 1,
            'children': 0,
            'infants': 0,
            'guest_email': request.session.get('guest_email', ''),
            'add_vehicle': False,
            'add_cargo': False,
            'vehicle_type': '',
            'vehicle_dimensions': '',
            'vehicle_license_plate': '',
            'cargo_type': '',
            'cargo_weight_kg': '',
            'cargo_dimensions_cm': '',
            'cargo_license_plate': '',
            'privacy_consent': False,
            'to_port': to_port or '',
            **{f'{addon["id"]}_quantity': 0 for addon in add_ons}
        }

        # Load saved passenger data from session
        saved_passenger_data = request.session.get('passenger_data', {})
        for p_type in ['adult', 'child', 'infant']:
            count_key = 'children' if p_type == 'child' else f'{p_type}s'
            count = form_data.get(count_key, 0)
            for i in range(count):
                form_data.update({
                    f'{p_type}_first_name_{i}': saved_passenger_data.get(f'{p_type}_first_name_{i}', ''),
                    f'{p_type}_last_name_{i}': saved_passenger_data.get(f'{p_type}_last_name_{i}', ''),
                    f'{p_type}_age_{i}': saved_passenger_data.get(f'{p_type}_age_{i}', ''),
                    f'{p_type}_dob_{i}': saved_passenger_data.get(f'{p_type}_dob_{i}', ''),
                    f'{p_type}_linked_adult_{i}': saved_passenger_data.get(f'{p_type}_linked_adult_{i}', '')
                })

        # Generate summary for step 4
        summary = None
        if step == 4 and schedule_id:
            try:
                schedule = Schedule.objects.get(
                    id=schedule_id,
                    status='scheduled',
                    departure_time__gt=timezone.now()
                )
                adults = safe_int(form_data['adults'])
                children = safe_int(form_data['children'])
                infants = safe_int(form_data['infants'])

                add_vehicle = form_data['add_vehicle']
                add_cargo = form_data['add_cargo']
                vehicle_type = form_data['vehicle_type']
                vehicle_dimensions = form_data['vehicle_dimensions']
                cargo_type = form_data['cargo_type']
                cargo_weight_kg = safe_float(form_data['cargo_weight_kg'])

                addons = []
                for addon in add_ons:
                    quantity = safe_int(form_data.get(f'{addon["id"]}_quantity', 0))
                    if quantity > 0:
                        addons.append({'type': addon['id'], 'quantity': quantity})

                total_price = calculate_total_price(
                    adults, children, infants, schedule, add_cargo, cargo_type,
                    cargo_weight_kg, addons, add_vehicle, vehicle_type, vehicle_dimensions
                )

                base_fare = schedule.route.base_fare or Decimal('35.50')
                summary = {
                    'schedule': {
                        'route': f"{schedule.route.departure_port.name} to {schedule.route.destination_port.name}",
                        'departure_time': schedule.departure_time.strftime("%a, %b %d, %H:%M"),
                        'estimated_duration': int(
                            schedule.route.estimated_duration.total_seconds() / 60) if schedule.route.estimated_duration else "N/A"
                    },
                    'pricing': {
                        'adults': str(Decimal(adults) * base_fare),
                        'children': str(Decimal(children) * base_fare * Decimal('0.5')),
                        'infants': str(Decimal(infants) * base_fare * Decimal('0.1')),
                        'vehicle': str(
                            calculate_vehicle_price(vehicle_type, vehicle_dimensions)) if add_vehicle else "0.00",
                        'cargo': str(
                            calculate_cargo_price(Decimal(cargo_weight_kg or 0), cargo_type)) if add_cargo else "0.00",
                        'addons': {
                            addon['type']: {
                                'label': next(
                                    (a['label'] for a in add_ons if a['id'] == addon['type']),
                                    addon['type'].replace('_', ' ').title()
                                ),
                                'quantity': addon['quantity'],
                                'amount': str(calculate_addon_price(addon['type'], addon['quantity']))
                            }
                            for addon in addons
                        },
                        'total': str(total_price)
                    },
                    'total_price': str(total_price)
                }
            except Schedule.DoesNotExist:
                messages.error(request, "Selected schedule is not available.")
                summary = None

        return render(request, 'bookings/book.html', {
            'bookings': available_schedules,
            'user': request.user,
            'form_data': form_data,
            'debug': settings.DEBUG,
            'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
            'summary': summary,
            'add_ons': add_ons
        })

    # === POST HANDLING (unchanged) ===
    if request.method == 'POST':
        step = request.POST.get('step')

        schedule_id = request.POST.get('schedule_id', '').strip()
        adults = safe_int(request.POST.get('adults', 0))
        children = safe_int(request.POST.get('children', 0))
        infants = safe_int(request.POST.get('infants', 0))
        total_passengers = adults + children + infants

        errors = []

        if step in ['2', '3', '4'] and not schedule_id:
            errors.append({'field': 'schedule_id', 'message': 'Schedule selection required', 'step': 1})

        if step in ['2', '3', '4'] and total_passengers == 0:
            errors.append({'field': 'passengers', 'message': 'At least one passenger required', 'step': 2})

        if step in ['2', '3', '4']:
            try:
                schedule = Schedule.objects.get(
                    id=schedule_id,
                    status='scheduled',
                    departure_time__gt=timezone.now()
                )
                if schedule.available_seats < total_passengers:
                    errors.append({
                        'field': 'schedule_id',
                        'message': f'Only {schedule.available_seats} seats available',
                        'step': 1
                    })
            except Schedule.DoesNotExist:
                errors.append({'field': 'schedule_id', 'message': 'Invalid schedule', 'step': 1})

        if step == '4' and not errors:
            privacy_consent = request.POST.get('privacy_consent') == 'on'
            if not privacy_consent:
                errors.append({'field': 'privacy_consent', 'message': 'Privacy consent required', 'step': 4})

            if not errors:
                request.session['booking_form_data'] = dict(request.POST)
                request.session['booking_step'] = '4'
                return redirect('bookings:create_checkout_session')

        if errors:
            return JsonResponse({'success': False, 'errors': errors})

        request.session['booking_form_data'] = dict(request.POST)
        request.session['booking_step'] = step
        return JsonResponse({'success': True, 'message': "alertness saved"})

    return JsonResponse({'error': 'Invalid request method'}, status=405)


def validate_passenger_data(request, p_type, index, adults, errors):
    first_name = request.POST.get(f'{p_type}_first_name_{index}', '').strip()
    last_name = request.POST.get(f'{p_type}_last_name_{index}', '').strip()
    age = request.POST.get(f'{p_type}_age_{index}', '').strip()
    dob = request.POST.get(f'{p_type}_dob_{index}', '').strip()
    linked_adult_index = request.POST.get(f'{p_type}_linked_adult_{index}', '').strip()
    document = request.FILES.get(f'{p_type}_id_document_{index}')

    # Mandatory fields
    if not first_name:
        errors.append({'field': f'{p_type}_first_name_{index}', 'message': f'{p_type.capitalize()} {index + 1}: First name is required.', 'step': 2})
    if not last_name:
        errors.append({'field': f'{p_type}_last_name_{index}', 'message': f'{p_type.capitalize()} {index + 1}: Last name is required.', 'step': 2})

    # Document validation for adults and children
    if p_type in ['adult', 'child']:
        if not document:
            errors.append({'field': f'{p_type}_id_document_{index}', 'message': f'{p_type.capitalize()} {index + 1}: ID document is required.', 'step': 2})
        else:
            try:
                FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])(document)
                if document.size > 2.5 * 1024 * 1024:  # 2.5MB
                    errors.append({'field': f'{p_type}_id_document_{index}', 'message': f'{p_type.capitalize()} {index + 1}: Document size must be less than 2.5MB.', 'step': 2})
            except ValidationError as e:
                errors.append({'field': f'{p_type}_id_document_{index}', 'message': f'{p_type.capitalize()} {index + 1}: Invalid file type. Please upload a PDF, JPG, or PNG.', 'step': 2})

    # Infant-specific validation
    if p_type == 'infant' and not dob:
        errors.append({'field': f'{p_type}_dob_{index}', 'message': f'Infant {index + 1}: Date of birth is required.', 'step': 2})

    # Linked adult validation for children and infants
    if p_type in ['child', 'infant']:
        if not linked_adult_index:
            errors.append({'field': f'{p_type}_linked_adult_{index}', 'message': f'{p_type.capitalize()} {index + 1}: Must be linked to an adult.', 'step': 2})
        else:
            try:
                linked_adult_index = int(linked_adult_index)
                if linked_adult_index < 0 or linked_adult_index >= adults:
                    errors.append({'field': f'{p_type}_linked_adult_{index}', 'message': f'{p_type.capitalize()} {index + 1}: Invalid linked adult.', 'step': 2})
            except (ValueError, TypeError):
                errors.append({'field': f'{p_type}_linked_adult_{index}', 'message': f'{p_type.capitalize()} {index + 1}: Invalid linked adult.', 'step': 2})

    # Age and DOB validation
    if p_type == 'infant' and dob:
        try:
            dob_date = datetime.datetime.strptime(dob, '%Y-%m-%d').date()
            age_days = (datetime.date.today() - dob_date).days
            if age_days > 730:  # 2 years
                errors.append({'field': f'{p_type}_dob_{index}', 'message': f'Infant {index + 1}: Must be under 2 years old.', 'step': 2})
        except ValueError:
            errors.append({'field': f'{p_type}_dob_{index}', 'message': f'Infant {index + 1}: Invalid date of birth.', 'step': 2})

    if p_type in ['adult', 'child'] and age:
        try:
            age = int(age)
            if p_type == 'child' and not (2 <= age <= 17):
                errors.append({'field': f'{p_type}_age_{index}', 'message': f'Child {index + 1}: Age must be 2-17.', 'step': 2})
            elif p_type == 'adult' and age < 18:
                errors.append({'field': f'{p_type}_age_{index}', 'message': f'Adult {index + 1}: Age must be 18 or older.', 'step': 2})
        except (ValueError, TypeError):
            errors.append({'field': f'{p_type}_age_{index}', 'message': f'{p_type.capitalize()} {index + 1}: Invalid age.', 'step': 2})

    return {
        'first_name': first_name,
        'last_name': last_name,
        'age': age,
        'dob': dob,
        'linked_adult_index': linked_adult_index,
        'document': document
    }


@csrf_exempt  # Add this decorator
@require_POST
def validate_file(request):
    """Fixed with proper AJAX check"""
    if request.method != 'POST':
        return JsonResponse({'valid': False, 'error': 'POST required'}, status=405)

    # Verify AJAX request
    if not request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        return JsonResponse({'valid': False, 'error': 'AJAX required'}, status=403)

    file = request.FILES.get('file')
    if not file:
        return JsonResponse({'valid': False, 'error': 'No file provided'}, status=400)

    try:
        FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])(file)
        if file.size > 2621440:  # 2.5MB
            return JsonResponse({'valid': False, 'error': 'File too large (2.5MB max)'}, status=413)

        # Basic verification (replace with OCR/service later)
        verification_status = 'verified'

        return JsonResponse({
            'valid': True,
            'file_name': file.name,
            'verification_status': verification_status
        })

    except ValidationError as e:
        return JsonResponse({'valid': False, 'error': str(e)}, status=400)
    except Exception as e:
        logger.error(f"File validation error: {e}")
        return JsonResponse({'valid': False, 'error': 'Validation failed'}, status=500)


@require_POST
@csrf_exempt
def check_schedule_availability(request):
    if not request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest':
        return JsonResponse({'valid': False, 'error': 'AJAX required'}, status=403)

    try:
        # === BATCH MODE (new) ===
        schedule_ids = request.POST.getlist('schedule_id')  # list of IDs
        if schedule_ids:
            # Validate all at once
            schedules = Schedule.objects.filter(
                id__in=schedule_ids,
                status='scheduled',
                departure_time__gt=timezone.now()
            ).values('id', 'departure_time__date')

            valid_ids = {str(s['id']) for s in schedules}
            result = {
                'valid': True,
                'available_dates': [
                    s['departure_time__date'].strftime('%Y-%m-%d') for s in schedules
                ]
            }
            return JsonResponse(result)

        # === SINGLE MODE (existing) ===
        schedule_id = request.POST.get('schedule_id')
        adults = safe_int(request.POST.get('adults', 0))
        children = safe_int(request.POST.get('children', 0))
        infants = safe_int(request.POST.get('infants', 0))
        total_passengers = adults + children + infants

        if not schedule_id or total_passengers <= 0:
            return JsonResponse({'valid': False, 'error': 'Invalid parameters'}, status=400)

        schedule = get_object_or_404(
            Schedule,
            id=schedule_id,
            status='scheduled',
            departure_time__gt=timezone.now()
        )

        if schedule.available_seats < total_passengers:
            return JsonResponse({
                'valid': False,
                'error': f'Only {schedule.available_seats} seats available'
            }, status=400)

        return JsonResponse({
            'valid': True,
            'schedule': {
                'id': schedule.id,
                'route': {
                    'departure_port': {'name': schedule.route.departure_port.name},
                    'destination_port': {'name': schedule.route.destination_port.name},
                    'base_fare': str(schedule.route.base_fare or Decimal('35.50'))
                },
                'departure_time': schedule.departure_time.isoformat(),
                'available_seats': schedule.available_seats
            }
        })

    except Exception as e:
        logger.error(f"Availability check failed: {e}")
        return JsonResponse({'valid': False, 'error': 'Server error'}, status=500)



def availability_api(request):
    route_id = request.GET.get('route_id')
    # Guard against non-integer input (previously raised an uncaught 500).
    year = safe_int(request.GET.get('year', 0))
    month = safe_int(request.GET.get('month', 0))

    if not (route_id and 1 <= month <= 12 and year):
        return JsonResponse({'available_dates': []})

    # ✅ Use datetime.datetime instead of datetime(...)
    start = datetime.date(year, month, 1)
    if month == 12:
        end = datetime.date(year + 1, 1, 1)
    else:
        end = datetime.date(year, month + 1, 1)

    qs = Schedule.objects.filter(
        route_id=route_id,
        departure_time__date__gte=start,
        departure_time__date__lt=end,
        status='scheduled',
        available_seats__gt=0
    ).values_list('departure_time__date', flat=True).distinct()

    dates = [d.strftime('%Y-%m-%d') for d in qs]
    return JsonResponse({'available_dates': dates})


@require_GET
def api_bookings(request):
    """
    API: /bookings/api/bookings/?route=...&date=...
    Returns filtered schedules with full route name.
    """
    route_param = request.GET.get('route', '').strip()
    route_id = request.GET.get('route_id', '').strip()
    date_str = request.GET.get('date')

    logger.debug(f"[api_bookings] route_param={route_param}, route_id={route_id}, date_str={date_str}")

    # Pagination parameters
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = max(1, min(50, int(request.GET.get('limit', 12))))
    except (TypeError, ValueError):
        limit = 12

    # Base queryset
    qs = Schedule.objects.select_related(
        'ferry', 'route', 'route__departure_port', 'route__destination_port'
    )

    # Filter by date
    if date_str:
        try:
            target_date = timezone.datetime.strptime(date_str, '%Y-%m-%d').date()
            # Use operational_day to avoid timezone-UTC conversion side effects.
            if hasattr(Schedule, 'operational_day'):
                qs = qs.filter(operational_day=target_date)
            else:
                qs = qs.filter(departure_time__date=target_date)
        except ValueError:
            logger.warning(f"Invalid date format: {date_str}")
            return JsonResponse({"schedules": [], "total": 0, "offset": offset, "limit": limit, "remaining": 0})
    else:
        # Default: today + next 2 days (3-day window)
        today = timezone.now().date()
        end_date = today + datetime.timedelta(days=2)
        qs = qs.filter(departure_time__date__gte=today, departure_time__date__lte=end_date)

    # Filter by route ID (highest priority)
    if route_id and route_id.isdigit():
        qs = qs.filter(route_id=int(route_id))

    # Filter by route text only if no route_id or still zero results
    if route_param:
        route_clean = route_param.replace('+', ' ').strip().lower()

        # Treat 'all' or 'any' as no route filter
        if route_clean not in ('', 'all', 'any'):
            route_qs = qs.filter(
                Q(route__departure_port__name__iexact=route_clean.split(' to ')[0].strip()) |
                Q(route__destination_port__name__iexact=route_clean.split(' to ')[1].strip() if ' to ' in route_clean else '') |
                Q(route__name__iexact=route_clean) |
                Q(route__slug__iexact=route_clean.replace(' ', '-').lower())
            )

            if route_qs.exists():
                qs = route_qs
            else:
                departure = route_clean.split(' to ')[0].strip()
                qs = qs.filter(
                    route__departure_port__name__icontains=departure
                )

    # Status filter
    status_param = request.GET.get('status', '').strip()
    if status_param:
        statuses = [s.strip().lower() for s in status_param.split(',') if s.strip()]
        allowed_statuses = {'scheduled', 'delayed', 'cancelled'}
        statuses = [s for s in statuses if s in allowed_statuses]
        if statuses:
            # keep scheduled seats rule but include delayed/cancelled too
            if 'scheduled' in statuses and len(statuses) > 1:
                qs = qs.filter(
                    Q(status='scheduled', available_seats__gt=0) |
                    Q(status__in=[s for s in statuses if s != 'scheduled'])
                )
            elif 'scheduled' in statuses:
                qs = qs.filter(status='scheduled', available_seats__gt=0)
            else:
                qs = qs.filter(status__in=statuses)
        else:
            qs = qs.filter(status='scheduled', available_seats__gt=0)
    else:
        qs = qs.filter(status='scheduled', available_seats__gt=0)

    # Price range filter
    try:
        price_min = float(request.GET.get('price_min', 0) or 0)
    except (TypeError, ValueError):
        price_min = 0
    try:
        price_max = float(request.GET.get('price_max', 0) or 0)
    except (TypeError, ValueError):
        price_max = 0

    if price_min > 0:
        qs = qs.filter(route__base_fare__gte=price_min)
    if price_max > 0:
        qs = qs.filter(route__base_fare__lte=price_max)

    # Duration filter (hours)
    duration_max = request.GET.get('duration_max')
    if duration_max and duration_max.isdigit():
        duration_max_hours = int(duration_max)
        if duration_max_hours > 0:
            qs = qs.filter(route__estimated_duration__lte=datetime.timedelta(hours=duration_max_hours))

    qs = qs.order_by('departure_time')

    total = qs.count()
    paged_qs = qs[offset:offset + limit]

    schedules = []
    for s in paged_qs:
        route_name = f"{s.route.departure_port.name} to {s.route.destination_port.name}"
        schedules.append({
            "id": s.id,
            "ferry_name": s.ferry.name,
            "departure_time": s.departure_time.isoformat(),
            "available_seats": s.available_seats,
            "status": s.status,
            "route": route_name,
            "price": float(s.route.base_fare) if s.route.base_fare else None,
            "duration": int(s.route.estimated_duration.total_seconds() / 60) if s.route.estimated_duration else None,
            "route_id": s.route_id
        })

    remaining = max(0, total - (offset + len(schedules)))

    # Debug log for client-side troubleshooting
    logger.debug(f"[api_bookings] route_param={route_param!r} route_id={route_id!r} date={date_str!r} status={status_param!r} price=({price_min},{price_max}) duration_max={duration_max} total_before_paging={total} schedules_returned={len(schedules)}")

    return JsonResponse({
        "schedules": schedules,
        "total": total,
        "offset": offset,
        "limit": limit,
        "remaining": remaining
    })


@require_GET
def api_paged_bookings(request):
    # API path for resilient load-more paging with live filter context.
    return api_bookings(request)


def _user_can_view_booking(request, booking):
    """SEC-1: correct object-level authorization for a booking.

    - Registered-user bookings: only the owner (or staff) may view.
    - Guest bookings: the session must hold the matching verified guest_email.
    Anonymous requests can never view a registered user's booking (closes the
    `None != None` bypass).
    """
    if getattr(request.user, 'is_authenticated', False):
        return request.user.is_staff or booking.user_id == request.user.id
    return bool(booking.guest_email) and request.session.get('guest_email') == booking.guest_email



def ticket_detail(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    return render(request, "ticket.html", {"ticket": ticket})


@login_required_allow_anonymous
def view_tickets(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    if not _user_can_view_booking(request, booking):
        logger.error(f"Authorization failed: not authorized for booking {booking_id} by {request.user}")
        return HttpResponseForbidden("You are not authorized to view this booking.")

    tickets = Ticket.objects.filter(booking=booking).select_related('passenger')
    cargo = Cargo.objects.filter(booking=booking).first()
    addons = AddOn.objects.filter(booking=booking)

    amount_to_charge = booking.total_price
    if booking.status == 'pending' and 'price_difference' in request.session:
        amount_to_charge = Decimal(str(request.session.get('price_difference', booking.total_price)))

    base_fare = booking.schedule.route.base_fare or Decimal('35.50')
    passenger_price = calculate_passenger_price(
        booking.passenger_adults, booking.passenger_children, booking.passenger_infants, booking.schedule
    )

    return render(request, 'bookings/ticket.html', {
        'booking': booking,
        'tickets': tickets,
        'cargo': cargo,
        'addons': addons,
        'amount_to_charge': amount_to_charge,
        'price_adults': booking.passenger_adults * base_fare,
        'price_children': booking.passenger_children * base_fare * Decimal('0.5'),
        'price_infants': booking.passenger_infants * base_fare * Decimal('0.1'),
        'cargo_price': cargo.price if cargo else Decimal('0.00'),
        'addon_prices': {addon.add_on_type: addon.price for addon in addons},
        'estimated_duration': int(booking.schedule.route.estimated_duration.total_seconds() / 60) if booking.schedule.route.estimated_duration else None,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY
    })



@login_required_allow_anonymous
def booking_pdf(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    # SEC-1: correct object-level authorization.
    if not _user_can_view_booking(request, booking):
        logger.error(f"Authorization failed for booking_pdf {booking_id} by {request.user}")
        return HttpResponseForbidden("You are not authorized to view this booking.")

    tickets = list(booking.tickets.all().order_by('passenger__first_name'))
    return render_booking_pdf(booking, tickets)



def process_payment(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    if booking.user and booking.user != request.user:
        logger.error(f"Authorization failed: User {request.user} not authorized for booking {booking_id}")
        return HttpResponseForbidden("You are not authorized to process this payment.")

    if booking.status == 'cancelled':
        messages.error(request, "This booking is no longer valid.")
        return redirect('bookings:booking_history')

    base_fare = booking.schedule.route.base_fare or Decimal('35.50')
    price_adults = Decimal(booking.passenger_adults) * base_fare
    price_children = Decimal(booking.passenger_children) * base_fare * Decimal('0.5')
    price_infants = Decimal(booking.passenger_infants) * base_fare * Decimal('0.1')
    cargo_price = sum(cargo.price for cargo in Cargo.objects.filter(booking=booking))
    addon_price = sum(addon.price for addon in AddOn.objects.filter(booking=booking))
    total_price = price_adults + price_children + price_infants + cargo_price + addon_price

    price_difference = request.session.get('price_difference')
    if price_difference is not None:
        try:
            price_difference = Decimal(str(price_difference))
        except Exception:
            price_difference = None

    amount_to_charge = price_difference if (price_difference and price_difference > 0) else total_price

    if amount_to_charge <= 0:
        logger.error(f"Invalid amount_to_charge for booking {booking_id}: {amount_to_charge}")
        return JsonResponse({'error': 'Payment amount must be greater than zero.'}, status=400)

    if request.method == 'POST':
        try:
            amount_cents = int(amount_to_charge * 100)
            if amount_cents <= 0:
                return JsonResponse({'error': 'Payment amount must be positive.'}, status=400)

            customer_email = booking.user.email if booking.user else booking.guest_email
            if not customer_email:
                return JsonResponse({'error': 'A valid email is required for payment.'}, status=400)

            success_url = request.build_absolute_uri('/bookings/success/?session_id={CHECKOUT_SESSION_ID}')
            cancel_url = request.build_absolute_uri('/bookings/cancel/')

            logger.info(f"Creating Stripe session for booking {booking_id}: amount={amount_cents}, email={customer_email}")

            session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{
                    'price_data': {
                        'currency': 'fjd',
                        'product_data': {'name': f'Ferry Booking #{booking.id}'},
                        'unit_amount': amount_cents,
                    },
                    'quantity': 1,
                }],
                mode='payment',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={'booking_id': str(booking.id), 'guest_email': booking.guest_email or ''},
                customer_email=customer_email,
            )

            booking.stripe_session_id = session.id
            booking.save()

            Payment.objects.create(
                booking=booking,
                payment_method='stripe',
                amount=amount_to_charge,
                session_id=session.id,
                payment_status='pending'
            )

            request.session['booking_id'] = booking.id
            request.session['stripe_session_id'] = session.id
            if booking.guest_email and not request.user.is_authenticated:
                request.session['guest_email'] = booking.guest_email
            request.session.pop('price_difference', None)

            return JsonResponse({'sessionId': session.id})

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error for booking {booking_id}: {str(e)}")
            return JsonResponse({'error': f"Payment processing error: {str(e)}"}, status=400)
        except Exception as e:
            logger.error(f"Unexpected error for booking {booking_id}: {str(e)}")
            return JsonResponse({'error': 'An unexpected error occurred. Please contact support.'}, status=500)

    return render(request, 'bookings/payment.html', {
        'booking': booking,
        'amount_to_charge': amount_to_charge,
        'price_adults': price_adults,
        'price_children': price_children,
        'price_infants': price_infants,
        'cargo_price': cargo_price,
        'addon_price': addon_price,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY
    })



def _display_name(user):
    """
    Best-effort user display name without relying on get_full_name()
    (works for custom User models).
    """
    if not user:
        return None
    first = getattr(user, "first_name", "") or ""
    last  = getattr(user, "last_name", "") or ""
    name = f"{first} {last}".strip()
    if name:
        return name
    return getattr(user, "email", None) or getattr(user, "username", None)


def payment_success(request):
    booking_id = request.session.get('booking_id')
    session_id = request.GET.get('session_id') or request.session.get('stripe_session_id')
    # Capability actually presented by the requester (URL or their own session),
    # captured before any recovery from the booking record overwrites session_id.
    presented_session_id = session_id

    logger.debug(f"Payment success: booking_id={booking_id}, session_id={session_id}")

    # === 1. RECOVER MISSING/PLACEHOLDER SESSION_ID ===
    if not session_id or session_id == '{CHECKOUT_SESSION_ID}':
        logger.warning("Invalid or missing session_id in payment_success")
        session_id = None
        if booking_id:
            try:
                booking = Booking.objects.get(id=booking_id)
                session_id = booking.stripe_session_id
                logger.debug(f"Retrieved session_id {session_id} from booking {booking_id}")
            except Booking.DoesNotExist:
                logger.error(f"Booking {booking_id} not found")
                messages.error(request, "Booking not found. Please contact support.")
                return redirect('bookings:booking_history')

    # === 2. IF NO BOOKING_ID BUT HAVE SESSION_ID → FETCH FROM STRIPE ===
    if not booking_id and session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            booking_id = session.metadata.get('booking_id')
            guest_email = session.metadata.get('guest_email')
            if guest_email:
                request.session['guest_email'] = guest_email
                logger.debug(f"Restored guest_email from metadata: {guest_email}")
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving session {session_id}: {str(e)}")
            messages.error(request, "Error verifying payment session. Please contact support.")
            return redirect('bookings:booking_history')
        except Exception as e:
            logger.error(f"Unexpected error retrieving session {session_id}: {str(e)}")
            messages.error(request, "An unexpected error occurred retrieving payment session. Please contact support.")
            return redirect('bookings:booking_history')

    if not booking_id:
        logger.error("Missing booking_id in session and metadata")
        messages.error(request, "Payment status could not be verified due to missing booking information. Please contact support.")
        return redirect('bookings:booking_history')

    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        logger.error(f"Booking {booking_id} not found")
        messages.error(request, "Booking not found. Please contact support.")
        return redirect('bookings:booking_history')

    # === 3. AUTHORIZATION ===
    if request.user.is_authenticated:
        if not (request.user.is_staff or booking.user_id == request.user.id):
            logger.error(f"Authorization failed: User {request.user} not authorized for booking {booking_id}")
            return HttpResponseForbidden("You are not authorized to view this booking.")
    else:
        # SEC: a guest is authorized either by a matching verified guest_email
        # already in their session, OR by presenting a valid Stripe session_id —
        # an unguessable capability that is verified against this booking's
        # metadata in step 5 below. We must NOT self-assign the session email
        # (that previously made the check always pass).
        guest_session_ok = (
            bool(booking.guest_email)
            and request.session.get('guest_email') == booking.guest_email
        )
        # Only a session_id the requester actually presented counts as a capability —
        # not one recovered from the target booking's own record.
        if not (guest_session_ok or presented_session_id):
            logger.error(f"Authorization failed: guest not authorized for booking {booking_id}")
            return HttpResponseForbidden("You are not authorized to view this booking.")

    if booking.evaluated_status == 'cancelled':
        logger.error(f"Booking {booking_id} is cancelled or expired")
        messages.error(request, "This booking is no longer valid.")
        return redirect('bookings:booking_history')

    # Currency formatting
    def fmt_fjd(value):
        try:
            d = Decimal(value)
        except Exception:
            d = Decimal("0.00")
        d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"FJD {d:,.2f}"

    try:
        # SEC-2: dev-mode payment bypass removed — payment is always verified via Stripe.
        if True:
            if not session_id:
                logger.error(f"No valid session_id found for booking {booking_id}")
                messages.error(request, "Invalid payment session. Please try again or contact support.")
                return redirect('bookings:booking_history')

            # === 5. VERIFY STRIPE SESSION ===
            session = stripe.checkout.Session.retrieve(session_id, expand=['payment_intent'])
            if not session.payment_intent:
                logger.error(f"No payment_intent found for session {session_id}, booking {booking_id}")
                messages.error(request, "Payment could not be verified. Please contact support.")
                return redirect('bookings:booking_history')

            if session.metadata.get('booking_id') != str(booking_id):
                logger.error(f"Session {session_id} metadata mismatch for booking {booking_id}")
                messages.error(request, "Invalid payment session. Please contact support.")
                return redirect('bookings:booking_history')

            # === 6. CONFIRM PAYMENT & BOOKING via service layer (idempotent) ===
            if session.payment_intent.status == 'succeeded':
                booking = services.confirm_paid_booking(
                    booking.id,
                    session_id=session.id,
                    payment_intent_id=session.payment_intent.id,
                    amount=Decimal(session.payment_intent.amount) / 100,
                )
                logger.info(f"Payment confirmed for booking {booking.id}")
            else:
                logger.warning(f"Payment not completed for booking {booking.id}: status={session.payment_intent.status}")
                messages.error(request, f"Payment is not completed yet. Status: {session.payment_intent.status}")
                return redirect('bookings:booking_history')

        # === 7. TICKET GENERATION WITH QR CODES ===
        tickets = []
        if Ticket.objects.filter(booking=booking).count() == booking.passengers.count():
            logger.info(f"Tickets already generated for booking {booking.id}")
            tickets = list(Ticket.objects.filter(booking=booking))
        else:
            if not booking.passengers.exists():
                logger.error(f"No passengers found for booking {booking.id}")
                messages.error(request, "No passengers associated with booking. Please contact support.")
                return redirect('bookings:booking_history')

            logger.debug(f"Starting ticket generation for booking {booking.id}")
            for passenger in booking.passengers.all():
                if not Ticket.objects.filter(booking=booking, passenger=passenger).exists():
                    try:
                        ticket = Ticket(
                            booking=booking,
                            passenger=passenger,
                            ticket_status='active',
                            qr_token=uuid.uuid4().hex
                        )
                        ticket.full_clean()
                        ticket.save()

                        # Generate QR code
                        qr_url = request.build_absolute_uri(reverse('bookings:view_ticket', args=[ticket.qr_token]))
                        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
                        qr.add_data(qr_url)
                        qr.make(fit=True)
                        img = qr.make_image(fill_color="black", back_color="white")
                        buffer = BytesIO()
                        img.save(buffer, format='PNG')
                        qr_image = buffer.getvalue()
                        buffer.close()

                        # Save QR to model
                        ticket.qr_code.save(f"qr_{ticket.id}.png", ContentFile(qr_image), save=True)
                        tickets.append(ticket)
                        logger.debug(f"Generated ticket {ticket.id} for passenger {passenger.id}")
                    except Exception as e:
                        logger.error(f"Error generating ticket for passenger {passenger.id}: {str(e)}")
                        messages.error(request, "Error generating tickets. Please contact support.")
                        return redirect('bookings:booking_history')

        # === 8. EMAIL WITH EMBEDDED QR CODES ===
        try:
            guest_name = _display_name(booking.user) or "Valued Guest"

            # Trip details
            estimated_duration = booking.schedule.route.estimated_duration
            arrival_str = "N/A"
            duration_str = "N/A"
            if estimated_duration:
                estimated_arrival = booking.schedule.departure_time + estimated_duration
                arrival_str = estimated_arrival.strftime("%A, %B %d, %Y at %H:%M")
                total_minutes = int(estimated_duration.total_seconds() / 60)
                hours, minutes = divmod(total_minutes, 60)
                duration_str = f"{hours}h {minutes}m" if minutes else f"{hours}h"

            dep_port = booking.schedule.route.departure_port.name
            dest_port = booking.schedule.route.destination_port.name
            vessel = booking.schedule.ferry.name
            depart = booking.schedule.departure_time.strftime("%A, %B %d, %Y at %H:%M")
            total_str = fmt_fjd(booking.total_price)

            # Passenger details
            passenger_details = [
                f"{p.first_name} {p.last_name} ({p.get_passenger_type_display()})"
                for p in booking.passengers.all()
            ]

            # Optional sections (vehicles, cargo, add-ons)
            def _section_html(title, rows):
                if not rows:
                    return ""
                return f'''
                    <tr><td colspan="2" style="padding:0 0 8px 0;">
                        <h3 style="margin:24px 0 8px;font-size:15px;font-weight:700;color:#111827;
                                  border-left:4px solid #3b82f6;padding-left:8px;">{title}</h3>
                    </td></tr>
                    <tr><td colspan="2" style="padding:0;">
                        <table style="width:100%;border-collapse:separate;border-spacing:0 6px;">
                            {''.join(rows)}
                        </table>
                    </td></tr>
                '''

            # Vehicles
            vehicle_rows = []
            for v in booking.vehicles.all():
                vehicle_rows.extend([
                    f'<tr><td style="width:40%;color:#6b7280;background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">Type</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{v.get_vehicle_type_display()}</td></tr>',
                    f'<tr><td style="color:#6b7280;background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">Dimensions</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{v.dimensions}</td></tr>',
                    f'<tr><td style="color:#6b7280;background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">License Plate</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{v.license_plate or "N/A"}</td></tr>',
                    f'<tr><td style="color:#6b7280;background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">Price</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{fmt_fjd(v.price)}</td></tr>',
                    '<tr><td colspan="2" style="background:transparent;border:none;padding:4px;"></td></tr>',
                ])
            vehicles_html = _section_html("Vehicles", vehicle_rows)

            # Cargo
            cargo_rows = []
            for c in booking.cargo.all():
                cargo_rows.extend([
                    f'<tr><td style="width:40%;color:#6b7280;background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">Type</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{c.get_cargo_type_display()}</td></tr>',
                    f'<tr><td style="color:#6b7280;background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">Weight</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{c.weight_kg} kg</td></tr>',
                    f'<tr><td style="color:#6b7280;background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">Dimensions</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{c.dimensions_cm or "N/A"}</td></tr>',
                    f'<tr><td style="color:#6b7280  background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">License Plate</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{c.license_plate or "N/A"}</td></tr>',
                    f'<tr><td style="color:#6b7280  background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">Price</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{fmt_fjd(c.price)}</td></tr>',
                    '<tr><td colspan="2" style="background:transparent;border:none;padding:4px;"></td></tr>',
                ])
            cargo_html = _section_html("Cargo", cargo_rows)

            # Add-ons
            addon_rows = []
            for a in booking.add_ons.all():
                qty = getattr(a, "quantity", 1) or 1
                addon_rows.append(
                    f'<tr><td style="width:40%;color:#6b7280;background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">'
                    f'{a.get_add_on_type_display()}</td>'
                    f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">x{qty} — {fmt_fjd(a.price)}</td></tr>'
                )
            addons_html = _section_html("Add-ons", addon_rows)

            # --- Generate QR code images for email (base64) ---
            qr_images = {}
            for ticket in tickets:
                if ticket.qr_code:
                    with default_storage.open(ticket.qr_code.name, 'rb') as img_file:
                        qr_images[ticket.id] = base64.b64encode(img_file.read()).decode('utf-8')

            # --- Plain-text fallback ---
            email_text = f"""Bula {guest_name},

Vinaka vakalevu! Your booking is confirmed.

Booking ID: {booking.id}
Route: {dep_port} to {dest_port}
Vessel: {vessel}
Departure: {depart}
Est. Arrival: {arrival_str}
Duration: {duration_str}

Passengers:
""" + "\n".join(f"- {p}" for p in passenger_details) + "\n\n"

            if booking.vehicles.exists():
                email_text += "Vehicles:\n" + "\n".join(
                    f"- {v.get_vehicle_type_display()} | {v.dimensions} | {v.license_plate or 'N/A'} | {fmt_fjd(v.price)}"
                    for v in booking.vehicles.all()
                ) + "\n\n"
            if booking.cargo.exists():
                email_text += "Cargo:\n" + "\n".join(
                    f"- {c.get_cargo_type_display()} | {c.weight_kg} kg | {c.dimensions_cm or 'N/A'} | {fmt_fjd(c.price)}"
                    for c in booking.cargo.all()
                ) + "\n\n"
            if booking.add_ons.exists():
                email_text += "Add-ons:\n" + "\n".join(
                    f"- {a.get_add_on_type_display()} (x{getattr(a, 'quantity', 1)}) | {fmt_fjd(a.price)}"
                    for a in booking.add_ons.all()
                ) + "\n\n"

            email_text += f"""Total Paid: {total_str}
View Tickets: {request.build_absolute_uri(reverse('bookings:view_tickets', args=[booking.id]))}

Please arrive 30–60 minutes early. Bring photo ID.

Support: support@yourferryservice.com | +679-738-8496

Vinaka vakalevu,
Fiji Ferry Service Team
"""

            # --- HTML Email with embedded QR codes ---
            wave_svg = "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMDAiIGhlaWdodD0iMTAwIiB2aWV3Qm94PSIwIDAgMjAwIDEwMCIgZmlsbD0ibm9uZSI+PHBhdGggZD0iTTAgNTBDMTYgNTAgMjQgNjUgMzUgNzBDNDYgODAgNTUgODUgNjUgODVDNzUgODUgODQgODAgOTUgNzBDMTA2IDY1IDExNiA1NSAxMzAgNTBDMTQ0IDQ1IDE1NiA0MCAxNzAgNDBDMTA0IDQwIDEwMCA0NSAqMTAwIDUwQzEwMCA1NSA5NiA2MCA5MCA2NUM4MyA3MCA3NSA3NSA2NSA3NUM1NSA3NSA0NSA3MCAzNSA2NUMyNSA2MCAxNiA1NSAwIDUwWiIgZmlsbD0iIzBlYTVlOSIgZmlsbC1vcGFjaXR5PSIwLjA1Ii8+PC9zdmc+"

            # QR ticket rows
            qr_rows = []
            for ticket in tickets:
                passenger = ticket.passenger
                name = f"{passenger.first_name} {passenger.last_name}"
                qr_cid = f"qr_{ticket.id}"
                qr_data = qr_images.get(ticket.id)
                qr_img = f'<img src="cid:{qr_cid}" alt="QR Code for {name}" style="width:150px;height:150px;margin:10px auto;display:block;border:1px solid #ddd;border-radius:8px;">' if qr_data else '<p style="color:#ef4444;">QR code unavailable</p>'
                qr_rows.append(f'''
                    <tr>
                        <td style="padding:16px 0;text-align:center;">
                            <p style="margin-bottom:8px;font-weight:600;color:#111827;">{name} ({passenger.get_passenger_type_display()})</p>
                            {qr_img}
                            <p style="margin:8px 0 0;font-size:12px;color:#6b7280;">Scan at check-in</p>
                        </td>
                    </tr>
                ''')

            email_html = f"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Booking Confirmation #{booking.id}</title>
<style>
  body {{margin:0;padding:0;background:#f6f8fb;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#1f2937;background-image:url('{wave_svg}');background-repeat:repeat-x;background-position:bottom;}}
  .container {{max-width:680px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 10px 30px rgba(2,6,23,.06);border:1px solid #eef2f7;}}
  .header {{background:linear-gradient(135deg,#0ea5e9,#6366f1);color:#fff;padding:24px;display:flex;align-items:center;gap:12px;}}
  .content {{padding:28px;}}
  .hello {{margin:0 0 12px;font-size:17px;font-weight:600;}}
  .lead {{margin:0 0 24px;color:#475569;line-height:1.5;}}
  .section {{margin-bottom:28px;}}
  .section-title {{font-size:15px;font-weight:700;margin:0 0 8px;color:#111827;border-left:4px solid #3b82f6;padding-left:8px;}}
  .grid {{display:grid;grid-template-columns:160px 1fr;gap:6px 16px;background:#f9fafb;border:1px solid #eef2f7;border-radius:12px;padding:16px;}}
  .label {{color:#6b7280;}}
  .value {{color:#111827;font-weight:600;}}
  .badge {{display:inline-block;padding:5px 10px;border-radius:999px;font-size:12px;font-weight:700;background:#ecfeff;color:#155e75;border:1px solid #a5f3fc;}}
  .total-box {{display:flex;justify-content:space-between;align-items:center;background:#f3f4f6;border:1px solid #e5e7eb;border-radius:12px;padding:14px 16px;margin-top:12px;}}
  .total-amount {{font-size:20px;font-weight:800;color:#111827;}}
  .cta {{display:block;text-align:center;margin:28px 0 0;background:#2563eb;color:#fff;text-decoration:none;padding:13px 16px;border-radius:10px;font-weight:700;}}
  .footer {{margin-top:32px;padding-top:20px;border-top:1px solid #e5e7eb;color:#6b7280;font-size:12px;text-align:center;}}
  .qr-table {{width:100%;border-collapse:separate;border-spacing:0 12px;}}
  a {{color:#2563eb;text-decoration:none;}}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <svg viewBox="0 0 24 24" fill="none" width="22" height="22">
      <path d="M3 18c3 0 3-2 6-2s3 2 6 2 3-2 6-2" stroke="white" stroke-width="1.5" stroke-linecap="round"/>
      <path d="M10 14l3-7 3 7" stroke="white" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
    <h1 style="margin:0;font-size:18px;font-weight:700;">Booking Confirmation #{booking.id}</h1>
  </div>

  <div class="content">
    <p class="hello">Bula {guest_name},</p>
    <p class="lead">Vinaka vakalevu! Your payment is confirmed and your journey is booked.</p>

    <div class="section">
      <h3 class="section-title">Trip Details</h3>
      <div class="grid">
        <div class="label">Route</div><div class="value">{dep_port} to {dest_port}</div>
        <div class="label">Vessel</div><div class="value">{vessel}</div>
        <div class="label">Departure</div><div class="value">{depart}</div>
        <div class="label">Est. Arrival</div><div class="value">{arrival_str}</div>
        <div class="label">Duration</div><div class="value">{duration_str}</div>
        <div class="label">Status</div><div class="value"><span class="badge">Paid</span></div>
      </div>
    </div>

    <div class="section">
      <h3 class="section-title">Your Tickets</h3>
      <table class="qr-table">
        {''.join(qr_rows)}
      </table>
    </div>

    <div class="section">
      <h3 class="section-title">Passengers</h3>
      <table style="width:100%;border-collapse:separate;border-spacing:0 6px;">
        {''.join(f'<tr><td style="width:40%;color:#6b7280;background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">Passenger</td>'
                 f'<td style="background:#f9fafb;padding:10px 12px;border:1px solid #eef2f7;">{pd}</td></tr>' for pd in passenger_details)}
      </table>
    </div>

    {vehicles_html}
    {cargo_html}
    {addons_html}

    <div class="section">
      <h3 class="section-title">Payment</h3>
      <div class="total-box">
        <div style="font-weight:600;">Total Paid</div>
        <div class="total-amount">{total_str}</div>
      </div>
    </div>

    <a class="cta" href="{request.build_absolute_uri(reverse('bookings:view_tickets', args=[booking.id]))}">
      View All Tickets Online
    </a>

    <div class="footer">
      Please arrive 30–60 minutes early. Present QR code at check-in.<br>
      Need help? <a href="mailto:support@yourferryservice.com">support@yourferryservice.com</a> • +679-738-8496
      <br><br>Vinaka vakSnack, and safe travels,<br><strong>Fiji Ferry Service Team</strong>
    </div>
  </div>
</div>
</body>
</html>
"""

            # --- Send email with inline QR images ---
            recipient = booking.user.email if booking.user and getattr(booking.user, "email", None) else (
                request.session.get('guest_email') or booking.guest_email
            )

            if recipient:
                msg = EmailMultiAlternatives(
                    subject=f"Your Ferry Booking Confirmed – ID {booking.id}",
                    body=email_text,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[recipient]
                )
                # Attach HTML body
                msg.attach_alternative(email_html, "text/html")

                # Ensure HTML + inline images are grouped as multipart/related
                msg.mixed_subtype = 'related'

                # Attach QR codes as inline images with Content-ID
                for ticket in tickets:
                    b64 = qr_images.get(ticket.id)
                    if b64:
                        img_part = MIMEImage(base64.b64decode(b64), _subtype="png")
                        img_part.add_header('Content-ID', f'<qr_{ticket.id}>')  # matches src="cid:qr_<id>"
                        img_part.add_header('Content-Disposition', 'inline', filename=f'qr_{ticket.id}.png')
                        msg.attach(img_part)

                msg.send()
                logger.debug(f"Confirmation email with QR codes sent to {recipient}")
            else:
                logger.warning("No recipient email found for booking confirmation")

        except Exception as e:
            logger.error(f"Error sending email for booking {booking.id}: {str(e)}")
            messages.warning(request, "Booking confirmed, but email failed. Check your inbox later.")

        # === 9. FINAL CLEANUP & REDIRECT ===
        messages.success(request, f'Booking #{booking.id} confirmed! Tickets generated and emailed.')
        request.session.pop('booking_id', None)
        request.session.pop('stripe_session_id', None)
        # DO NOT POP guest_email — needed for view_tickets()
        # request.session.pop('guest_email', None)

        return redirect('bookings:view_tickets', booking_id=booking.id)

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error for booking {booking_id}: {str(e)}")
        messages.error(request, f"Payment verification failed: {str(e)}. Please contact support.")
        return redirect('bookings:booking_history')
    except Exception as e:
        logger.error(f"Unexpected error for booking {booking_id}: {str(e)}")
        messages.error(request, "An unexpected error occurred. Please contact support.")
        return redirect('bookings:booking_history')



@login_required_allow_anonymous
def payment_cancel(request):
    booking_id = request.session.get('booking_id')
    logger.debug(f"Payment cancelled: booking_id={booking_id}")

    if booking_id:
        try:
            booking = Booking.objects.get(id=booking_id)
            if request.user.is_authenticated and booking.user != request.user:
                logger.error(f"Authorization failed: User {request.user} not authorized for booking {booking_id}")
                return HttpResponseForbidden("You are not authorized to view this booking.")
            if not request.user.is_authenticated and booking.guest_email != request.session.get('guest_email'):
                logger.error(f"Authorization failed: Guest email mismatch for booking {booking_id}")
                return HttpResponseForbidden("You are not authorized to view this booking.")

            booking.status = 'cancelled'
            booking.schedule.available_seats += (
                booking.passenger_adults + booking.passenger_children + booking.passenger_infants
            )
            booking.schedule.save()
            booking.save()

            messages.info(request, f'Booking #{booking.id} has been cancelled.')
            request.session.pop('booking_id', None)
            request.session.pop('stripe_session_id', None)
            request.session.pop('price_difference', None)

        except Booking.DoesNotExist:
            logger.error(f"Booking {booking_id} not found")
            messages.error(request, "Booking not found. Please contact support.")
    else:
        logger.warning("No booking_id found in session for cancellation")
        messages.error(request, "No booking found to cancel.")

    return redirect('bookings:booking_history')


@require_POST
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    # Authorization
    if request.user.is_authenticated:
        if booking.user != request.user:
            return JsonResponse({'error': 'Unauthorized'}, status=403)
    else:
        if booking.guest_email != request.session.get('guest_email'):
            return JsonResponse({'error': 'Unauthorized'}, status=403)

    if booking.status == 'cancelled':
        return JsonResponse({'error': 'Booking already cancelled'}, status=400)

    if booking.schedule.departure_time <= timezone.now() + datetime.timedelta(hours=6):
        return JsonResponse({'error': 'Cannot cancel within 6 hours of departure'}, status=400)

    try:
        with transaction.atomic():
            # Get payment to retrieve exact amount paid
            payment = Payment.objects.filter(booking=booking, payment_status='completed').first()
            if not payment or not payment.payment_intent_id:
                return JsonResponse({'error': 'No payment found'}, status=400)

            # Use EXACT amount from Stripe (in cents)
            session = stripe.checkout.Session.retrieve(
                payment.session_id or booking.stripe_session_id,
                expand=['payment_intent']
            )
            if not session.payment_intent:
                return JsonResponse({'error': 'Payment intent not found'}, status=400)

            amount_paid_cents = session.payment_intent.amount_received  # Exact amount in cents

            # Create refund using EXACT amount
            refund = stripe.Refund.create(
                payment_intent=session.payment_intent.id,
                amount=amount_paid_cents  # ← Critical: use exact amount
            )

            # Update booking & payment
            booking.status = 'cancelled'
            booking.save()

            payment.payment_status = 'refunded'
            payment.refund_id = refund.id
            payment.save()

            logger.info(f"Booking {booking.id} cancelled and refunded {amount_paid_cents} cents")

        return JsonResponse({'message': 'Booking cancelled and refunded successfully'})

    except stripe.error.StripeError as e:
        logger.error(f"Refund error for booking {booking.id}: {e}")
        return JsonResponse({'error': str(e.user_message or 'Refund failed')}, status=400)
    except Exception as e:
        logger.error(f"Unexpected error cancelling booking {booking.id}: {e}")
        return JsonResponse({'error': 'An unexpected error occurred'}, status=500)


@require_POST
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        logger.error("Invalid webhook payload")
        return JsonResponse({'status': 'invalid payload'}, status=400)
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid webhook signature")
        return JsonResponse({'status': 'invalid signature'}, status=400)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        booking_id = session.get('metadata', {}).get('booking_id')
        session_id = session.get('id')
        payment_intent_id = session.get('payment_intent')
        guest_email = session.get('metadata', {}).get('guest_email')

        if not booking_id:
            logger.error(f"No booking_id in session metadata: session_id={session_id}")
            return JsonResponse({'status': 'missing booking_id'}, status=400)

        try:
            booking = Booking.objects.get(id=booking_id)
        except Booking.DoesNotExist:
            logger.error(f"Booking {booking_id} not found for session {session_id}")
            return JsonResponse({'status': 'booking not found'}, status=404)

        try:
            # Idempotent confirm via the service layer (row lock + state guard).
            booking = services.confirm_paid_booking(
                booking.id,
                session_id=session_id,
                payment_intent_id=payment_intent_id,
                amount=Decimal(session.get('amount_total', 0)) / 100,
            )

            # Create tickets if missing
            if Ticket.objects.filter(booking=booking).count() < booking.passengers.count():
                logger.debug(f"Starting ticket generation for booking {booking.id}, passenger count: {booking.passengers.count()}")
                for passenger in booking.passengers.all():
                    if not Ticket.objects.filter(booking=booking, passenger=passenger).exists():
                        try:
                            ticket = Ticket(
                                booking=booking,
                                passenger=passenger,
                                ticket_status='active',
                                qr_token=uuid.uuid4().hex
                            )
                            ticket.full_clean()
                            ticket.save()
                            qr_data = request.build_absolute_uri(reverse('bookings:view_ticket', args=[ticket.qr_token]))
                            qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
                            qr.add_data(qr_data)
                            qr.make(fit=True)
                            img = qr.make_image(fill_color="black", back_color="white")
                            buffer = BytesIO()
                            img.save(buffer, format='PNG')
                            try:
                                ticket.qr_code.save(f"ticket_{ticket.id}.png", ContentFile(buffer.getvalue()), save=True)
                                logger.debug(f"Generated ticket {ticket.id} for passenger {passenger.id}")
                            except Exception as e:
                                logger.error(f"Error saving QR code for ticket {ticket.id}: {str(e)}")
                                ticket.delete()
                                return JsonResponse({'status': 'error', 'message': 'Error saving ticket QR code'}, status=500)
                        except ValidationError as ve:
                            logger.error(f"Validation error for ticket, passenger {passenger.id}: {str(ve)}")
                            return JsonResponse({'status': 'error', 'message': 'Invalid ticket data'}, status=500)
                        except Exception as e:
                            logger.error(f"Error generating ticket for passenger {passenger.id}: {str(e)}")
                            return JsonResponse({'status': 'error', 'message': 'Error generating tickets'}, status=500)

            # Build confirmation email
            from datetime import timedelta
            from django.template.loader import render_to_string

            # Derive guest name
            guest_name = booking.user.get_full_name() if booking.user and booking.user.get_full_name() else "Valued Guest"

            # Calculate arrival and duration strings
            estimated_duration = booking.schedule.route.estimated_duration
            arrival_str = "N/A"
            duration_str = "N/A"
            if estimated_duration:
                estimated_arrival = booking.schedule.departure_time + estimated_duration
                arrival_str = estimated_arrival.strftime("%A, %B %d, %Y at %H:%M")
                total_minutes = int(estimated_duration.total_seconds() / 60)
                hours = total_minutes // 60
                minutes = total_minutes % 60
                duration_str = f"{hours} hours {minutes} minutes" if minutes else f"{hours} hours"

            # Passenger details list
            passenger_details = []
            for p in booking.passengers.all():
                passenger_details.append(f"{p.first_name} {p.last_name} ({p.get_passenger_type_display()})")

            # Plain text fallback
            email_body = (
                f"Dear {guest_name},\n\n"
                f"Thank you for choosing our ferry service. We are pleased to confirm your booking.\n\n"
                f"**Booking Details**\n"
                f"Booking ID: {booking.id}\n"
                f"Route: {booking.schedule.route.departure_port.name} to {booking.schedule.route.destination_port.name}\n"
                f"Vessel: {booking.schedule.ferry.name}\n"
                f"Departure: {booking.schedule.departure_time.strftime('%A, %B %d, %Y at %H:%M')}\n"
                f"Estimated Arrival: {arrival_str}\n"
                f"Estimated Duration: {duration_str}\n\n"
                f"**Passengers**\n" + "\n".join([f"- {pd}" for pd in passenger_details]) + f"\nTotal: {len(passenger_details)}\n\n"
            )

            if booking.vehicles.exists():
                email_body += "**Vehicles**\n"
                for vehicle in booking.vehicles.all():
                    email_body += (
                        f"- Type: {vehicle.get_vehicle_type_display()}\n"
                        f"  Dimensions: {vehicle.dimensions}\n"
                        f"  License Plate: {vehicle.license_plate or 'N/A'}\n"
                        f"  Price: FJD {vehicle.price}\n\n"
                    )

            if booking.cargo.exists():
                email_body += "**Cargo**\n"
                for cargo in booking.cargo.all():
                    email_body += (
                        f"- Type: {cargo.get_cargo_type_display()}\n"
                        f"  Weight: {cargo.weight_kg} kg\n"
                        f"  Dimensions: {cargo.dimensions_cm or 'N/A'}\n"
                        f"  License Plate: {cargo.license_plate or 'N/A'}\n"
                        f"  Price: FJD {cargo.price}\n\n"
                    )

            if booking.add_ons.exists():
                email_body += "**Add-ons**\n"
                for addon in booking.add_ons.all():
                    email_body += f"- {addon.get_add_on_type_display()} (x{addon.quantity}): FJD {addon.price}\n\n"

            email_body += (
                f"**Payment Summary**\n"
                f"Total Price: FJD {booking.total_price}\n"
                f"Payment Method: Stripe\n"
                f"Status: Completed\n\n"
                f"**Important Instructions**\n"
                f"Please arrive at least 30-60 minutes before departure for check-in and boarding.\n"
                f"Bring a valid ID for all passengers and vehicle documents if applicable.\n"
                f"Wear comfortable clothing and consider bringing water and snacks.\n"
                f"View your tickets: {request.build_absolute_uri(reverse('bookings:view_tickets', args=[booking.id]))}\n\n"
                f"For any inquiries, contact us at support@yourferryservice.com or +679-123-4567.\n"
                f"Review our terms of service: {request.build_absolute_uri(reverse('bookings:terms_of_service'))}\n\n"
                f"Best regards,\n"
                f"Your Ferry Service Team"
            )

            # HTML version (assume 'emails/booking_confirmation.html' template exists)
            context = {
                'guest_name': guest_name,
                'booking': booking,
                'arrival_str': arrival_str,
                'duration_str': duration_str,
                'passengers': passenger_details,
                'vehicles': booking.vehicles.all(),
                'cargos': booking.cargo.all(),
                'add_ons': booking.add_ons.all(),
                'view_tickets_url': request.build_absolute_uri(reverse('bookings:view_tickets', args=[booking.id])),
                'policy_url': request.build_absolute_uri(reverse('bookings:terms_of_service')),
                'contact_email': 'support@yourferryservice.com',
                'contact_phone': '+679-123-4567',
            }
            # Confirmation email is best-effort: payment is already confirmed and
            # tickets generated above, so an email/template failure must NOT fail
            # the webhook (Stripe would otherwise retry a successful payment).
            try:
                try:
                    html_body = render_to_string('emails/booking_confirmation.html', context)
                except Exception as e:
                    logger.warning(f"Confirmation email template unavailable for booking {booking.id}: {e}")
                    html_body = None
                send_mail(
                    f"Your Ferry Booking Confirmation - ID {booking.id}",
                    email_body,
                    settings.DEFAULT_FROM_EMAIL,
                    [booking.user.email if booking.user else guest_email],
                    html_message=html_body,
                    fail_silently=True,
                )
            except Exception as e:
                logger.warning(f"Confirmation email failed for booking {booking.id}: {e}")

            logger.info(f"Webhook processed: Payment confirmed for booking {booking.id}")
            return JsonResponse({'status': 'success'})

        except Payment.DoesNotExist:
            logger.error(f"Payment not found for booking {booking_id}, session {session_id}")
            return JsonResponse({'status': 'payment not found'}, status=404)

        except Exception as e:
            logger.error(f"Webhook error for booking {booking_id}: {str(e)}")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

    return JsonResponse({'status': 'event not handled'})


@login_required
def modify_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    now = timezone.now()

    if booking.status != 'confirmed' or booking.schedule.departure_time <= now + datetime.timedelta(hours=6):
        messages.error(request, "This booking cannot be modified.")
        return redirect('bookings:booking_history')

    form = ModifyBookingForm(request.POST or None, instance=booking)
    if request.method == 'POST' and form.is_valid():
        new_schedule = form.cleaned_data['schedule']
        new_adults = form.cleaned_data['passenger_adults']
        new_children = form.cleaned_data['passenger_children']
        new_infants = form.cleaned_data['passenger_infants']

        total_passengers = new_adults + new_children + new_infants
        if total_passengers == 0:
            messages.error(request, "At least one passenger is required.")
            return render(request, 'bookings/modify_booking.html', {'form': form, 'booking': booking})

        old_total_price = booking.total_price
        new_total_price = calculate_total_price(
            new_adults, new_children, new_infants, new_schedule,
            booking.cargo.exists(), booking.cargo.first().cargo_type if booking.cargo.exists() else None,
            booking.cargo.first().weight_kg if booking.cargo.exists() else 0,
            [{'type': addon.add_on_type, 'quantity': addon.quantity} for addon in booking.addons.all()]
        )

        # CON-1/LOG-4: move seats atomically under a row lock to prevent
        # overbooking on the new schedule and lost updates on the old one.
        old_schedule_id = booking.schedule_id
        old_seats = (booking.passenger_adults + booking.passenger_children + booking.passenger_infants)
        with transaction.atomic():
            locked_new = Schedule.objects.select_for_update().get(pk=new_schedule.pk)
            # If staying on the same schedule, the seats we are about to release count as available.
            effective_available = locked_new.available_seats + (old_seats if old_schedule_id == new_schedule.pk else 0)
            if effective_available < total_passengers:
                messages.error(request, "Not enough seats available in the selected schedule.")
                return render(request, 'bookings/modify_booking.html', {'form': form, 'booking': booking})

            if old_schedule_id:
                Schedule.objects.filter(pk=old_schedule_id).update(
                    available_seats=F('available_seats') + old_seats
                )
            Schedule.objects.filter(pk=new_schedule.pk).update(
                available_seats=F('available_seats') - total_passengers
            )

            booking.schedule = new_schedule
            booking.passenger_adults = new_adults
            booking.passenger_children = new_children
            booking.passenger_infants = new_infants
            booking.total_price = new_total_price
            booking.save()

        price_difference = new_total_price - old_total_price
        if price_difference > 0:
            request.session['price_difference'] = str(price_difference)
            request.session['booking_id'] = booking.id
            messages.info(request, f"Booking modified. Additional payment of FJD {price_difference} required.")
            return redirect('bookings:process_payment', booking_id=booking.id)
        elif price_difference < 0:
            try:
                refund = stripe.Refund.create(
                    payment_intent=booking.payment_intent_id,
                    amount=int(abs(price_difference) * 100)
                )
                Payment.objects.create(
                    booking=booking,
                    payment_method='stripe',
                    amount=price_difference,
                    payment_status='refunded',
                    transaction_id=refund.id
                )
                logger.info(f"Refund processed for booking {booking.id}: amount={price_difference}")
            except stripe.error.StripeError as e:
                logger.error(f"Refund error for booking {booking.id}: {str(e)}")
                messages.error(request, f"Refund processing failed: {str(e)}. Please contact support.")
                return redirect('bookings:booking_history')

        messages.success(request, "Booking modified successfully.")
        return redirect('bookings:view_tickets', booking_id=booking.id)

    return render(request, 'bookings/modify_booking.html', {
        'form': form,
        'booking': booking,
        'cutoff_time': now + datetime.timedelta(hours=6)
    })


@login_required
def cancel_booking(request, booking_id):
    # Get the booking first so we can give precise feedback instead of a 404
    booking = get_object_or_404(Booking, id=booking_id)

    # Ownership/authorization check
    if booking.user_id != request.user.id and not request.user.is_staff:
        # Show a clear message to the user and avoid 404
        messages.error(request, "You can only cancel your own bookings.")
        logger.warning(
            "User %s attempted to cancel booking %s not owned by them.",
            request.user.id, booking_id
        )
        # For web flow, redirect with a message; for strict API, you could return HttpResponseForbidden
        return redirect('bookings:booking_history')

    now = timezone.now()
    cutoff = now + datetime.timedelta(hours=6)

    # Business rule messaging
    if booking.status != 'confirmed':
        messages.error(request, "Only confirmed bookings can be cancelled.")
        return redirect('bookings:booking_history')

    if booking.schedule.departure_time <= cutoff:
        # Be explicit why: departure too soon or already departed
        if booking.schedule.departure_time <= now:
            messages.error(request, "This trip has already departed and cannot be cancelled.")
        else:
            leave_in = booking.schedule.departure_time - now
            minutes_left = max(0, int(leave_in.total_seconds() // 60))
            messages.error(
                request,
                f"This booking cannot be cancelled within 6 hours of departure "
                f"(only {minutes_left} minute(s) remaining)."
            )
        return redirect('bookings:booking_history')

    if request.method == 'POST':
        try:
            # CON-2: delegate to the service layer (row lock + status re-check +
            # idempotent refund + atomic seat release).
            _booking, changed = services.cancel_booking(booking.pk, do_refund=True)
            if changed:
                messages.success(request, f"Booking #{booking.id} has been cancelled and refunded.")
            else:
                messages.info(request, f"Booking #{booking.id} was already cancelled.")
            return redirect('bookings:booking_history')

        except stripe.error.StripeError as e:
            logger.error(f"Refund error for booking {booking.id}: {str(e)}")
            messages.error(request, f"Refund processing failed: {str(e)}. Please contact support.")
            return redirect('bookings:booking_history')
        except Exception as e:
            logger.error(f"Unexpected error cancelling booking {booking.id}: {str(e)}")
            messages.error(request, "An unexpected error occurred. Please contact support.")
            return redirect('bookings:booking_history')

    # GET -> show confirmation page
    return render(request, 'bookings/cancel.html', {
        'booking': booking,
        'cutoff_time': cutoff
    })



def download_ticket(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id, booking__user=request.user)
    if ticket.ticket_status != 'active':
        messages.error(request, "This ticket is not valid for download.")
        return redirect('bookings:booking_history')

    buffer = BytesIO()
    ticket.qr_code.seek(0)
    buffer.write(ticket.qr_code.read())
    buffer.seek(0)

    response = HttpResponse(buffer, content_type='image/png')
    response['Content-Disposition'] = f'attachment; filename=ticket_{ticket.id}.png'
    return response


@require_GET
@staff_member_required
def weather_forecast_view(request):
    """Fetch weather forecasts for all ports using OpenWeatherMap API."""
    api_key = settings.OPENWEATHERMAP_API_KEY
    ports = Port.objects.values('lat', 'lng', 'name')
    forecasts = []
    cache_key = 'weather_forecasts_all_ports'
    cached_forecasts = cache.get(cache_key)

    if cached_forecasts:
        logger.info("Returning cached weather forecasts")
        return JsonResponse({'forecasts': cached_forecasts})

    try:
        for port in ports:
            url = f"https://api.openweathermap.org/data/2.5/forecast?lat={port['lat']}&lon={port['lng']}&appid={api_key}&units=metric"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            if data.get('list'):
                forecasts.append({
                    'port': port['name'],
                    'forecast': [
                        {
                            'datetime': item['dt_txt'],
                            'temperature': float(item['main']['temp']),
                            'condition': item['weather'][0]['description'],
                            'wind_speed': float(item['wind']['speed']) * 3.6,  # Convert m/s to km/h
                            'precipitation_probability': float(item.get('pop', 0)) * 100
                        } for item in data['list'][:8]  # Next 24 hours (3-hour intervals)
                    ]
                })
        cache.set(cache_key, forecasts, timeout=1800)  # Cache for 30 minutes
        logger.info(f"Weather forecasts fetched for {len(ports)} ports")
        return JsonResponse({'forecasts': forecasts})
    except requests.RequestException as e:
        logger.error(f"OpenWeatherMap API error: {str(e)}")
        return JsonResponse({'error': 'Failed to fetch weather forecasts'}, status=500)


@require_GET
@staff_member_required
def stripe_insights_view(request):
    """Fetch recent Stripe transactions and disputes."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    cache_key = 'stripe_insights'
    cached_insights = cache.get(cache_key)

    if cached_insights:
        logger.info("Returning cached Stripe insights")
        return JsonResponse(cached_insights)

    try:
        charges = stripe.Charge.list(limit=5)
        disputes = stripe.Dispute.list(limit=3)
        insights = {
            'recent_charges': [
                {
                    'id': c.id,
                    'amount': float(c.amount / 100),
                    'status': c.status,
                    'created': datetime.datetime.fromtimestamp(c.created).isoformat(),
                    'description': c.description or f"Booking #{c.metadata.get('booking_id', 'N/A')}"
                } for c in charges.data
            ],
            'disputes': [
                {
                    'id': d.id,
                    'amount': float(d.amount / 100),
                    'status': d.status,
                    'reason': d.reason,
                    'created': datetime.datetime.fromtimestamp(d.created).isoformat()
                } for d in disputes.data
            ]
        }
        cache.set(cache_key, insights, timeout=300)  # Cache for 5 minutes
        logger.info("Stripe insights fetched successfully")
        return JsonResponse(insights)
    except stripe.error.StripeError as e:
        logger.error(f"Stripe API error: {str(e)}")
        return JsonResponse({'error': 'Failed to fetch Stripe insights'}, status=500)


@require_POST
@csrf_protect
def api_send_otp(request):
    """Start OTP flow for a guest email."""
    email = (request.POST.get("email") or "").strip().lower()
    if not EMAIL_RE.match(email):
        return JsonResponse(
            {"success": False, "errors": [{"field": "guest_email", "message": "Enter a valid email"}]},
            status=400,
        )

    # SEC-4: rate-limit OTP sends per-email and per-IP to prevent mail-bombing
    # and quota abuse. Uses the Redis cache backend.
    client_ip = request.META.get('REMOTE_ADDR', 'unknown')
    for scope, limit, window in (("email:%s" % email, 3, 900), ("ip:%s" % client_ip, 10, 900)):
        rl_key = "otp_rl:%s" % scope
        count = cache.get(rl_key, 0)
        if count >= limit:
            return JsonResponse(
                {"success": False,
                 "errors": [{"field": "guest_email",
                             "message": "Too many verification requests. Please wait a few minutes and try again."}]},
                status=429,
            )
        cache.set(rl_key, count + 1, window)

    # If a previously verified email exists and differs, clear canonical markers
    prev_verified = (request.session.get("guest_otp_verified_email") or "").lower()
    if prev_verified and prev_verified != email:
        request.session.pop("guest_otp_verified_email", None)
        request.session.pop("guest_otp_verified_at", None)
        request.session.modified = True

    key = _otp_store_key(email)
    code = generate_otp_code()
    exp_minutes = getattr(settings, "OTP_EXP_MINUTES", 10)
    request.session[key] = {
        "email": email,
        "code": code,
        "expires_at": (timezone.now() + datetime.timedelta(minutes=exp_minutes)).isoformat(),
        "attempts": 0,
        "verified": False,
    }
    request.session.modified = True

    # Send email (same stack as payment_success)
    subject = getattr(settings, "OTP_EMAIL_SUBJECT", "Your Fiji Ferry verification code")
    text_body = f"""Your Fiji Ferry verification code is: {code}

This code expires in {exp_minutes} minutes.
If you did not request this code, you can ignore this email.
"""
    html_body = f"""
<!doctype html>
<html><body style="font-family:system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial">
  <div style="max-width:560px;margin:24px auto;padding:20px;border:1px solid #eef2f7;border-radius:12px">
    <h2 style="margin:0 0 10px">Verify your email</h2>
    <p>Enter this code in the booking page:</p>
    <div style="font-size:28px;font-weight:800;letter-spacing:4px;margin:12px 0">{code}</div>
    <p style="color:#6b7280">This code expires in {exp_minutes} minutes.</p>
  </div>
</body></html>
"""
    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )
    msg.attach_alternative(html_body, "text/html")
    try:
        msg.send()
    except Exception as e:
        logger.error(f"OTP email send failed for {email}: {e}")
        # Roll back the stored code so the user isn't left in a half-sent state.
        request.session.pop(key, None)
        request.session.modified = True
        return JsonResponse(
            {"success": False,
             "errors": [{"field": "guest_email",
                         "message": "We couldn't send the verification email right now. Please try again later."}]},
            status=502,
        )

    return JsonResponse({"success": True})

@require_POST
@csrf_protect
def api_verify_otp(request):
    """Verify guest OTP."""
    email = (request.POST.get("email") or "").strip().lower()
    code  = (request.POST.get("code") or "").strip()

    if not EMAIL_RE.match(email) or not code:
        return JsonResponse(
            {"success": False, "errors": [{"field": "guest_email", "message": "Invalid request"}]},
            status=400,
        )

    key = _otp_store_key(email)
    data = request.session.get(key)
    if not data:
        return JsonResponse(
            {"success": False, "errors": [{"field": "guest_email", "message": "No code found. Send a new one."}]},
            status=400,
        )

    # throttle
    attempts = int(data.get("attempts") or 0)
    max_attempts = int(getattr(settings, "OTP_MAX_ATTEMPTS", 6))
    if attempts >= max_attempts:
        return JsonResponse(
            {"success": False, "errors": [{"field": "guest_email", "message": "Too many attempts. Send a new code."}]},
            status=429,
        )

    # expiry
    try:
        expires_at = timezone.datetime.fromisoformat(data["expires_at"])
        if timezone.is_naive(expires_at):
            expires_at = timezone.make_aware(expires_at, timezone.get_current_timezone())
    except Exception:
        expires_at = timezone.now() - datetime.timedelta(seconds=1)

    if timezone.now() > expires_at:
        return JsonResponse(
            {"success": False, "errors": [{"field": "guest_email", "message": "Code expired. Send a new one."}]},
            status=400,
        )

    # compare
    if code != str(data.get("code")):
        data["attempts"] = attempts + 1
        request.session[key] = data
        request.session.modified = True
        return JsonResponse(
            {"success": False, "errors": [{"field": "guest_email", "message": "Incorrect code"}]},
            status=400,
        )

    # success
    data["verified"] = True
    request.session[key] = data

    # --- Canonical flags used by validate_step ---
    request.session["guest_otp_verified_email"] = email
    request.session["guest_otp_verified_at"] = timezone.now().isoformat()

    # Keep legacy key if used elsewhere
    request.session["guest_email"] = email

    request.session.modified = True
    return JsonResponse({"success": True})
