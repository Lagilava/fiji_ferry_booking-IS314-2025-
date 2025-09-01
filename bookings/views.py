import datetime
import hashlib
import io, os
import json
import logging
import re
import time
import uuid
from decimal import Decimal
from io import BytesIO
from reportlab.lib.pagesizes import A4
import stripe
import qrcode
import requests
from reportlab.pdfgen import canvas
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile, File
from django.core.mail import send_mail
from django.core.validators import FileExtensionValidator
from django.db.models import Subquery, Max, OuterRef
from django.http import JsonResponse, HttpResponseForbidden, StreamingHttpResponse, HttpResponse, FileResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_POST, require_GET

from .decorators import login_required_allow_anonymous
from .forms import CargoBookingForm, ModifyBookingForm
from .models import Schedule, Booking, Passenger, Payment, Ticket, Cargo, Route, WeatherCondition, AddOn, Vehicle

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

# Helper to support multiple possible POST field names (frontend uses simple names, some code expects array-like names)
def get_post_field(request, names, default=''):
    """Return the first non-empty POST value for any of the provided names.
    names: list/tuple of possible field names to check in order.
    """
    for name in names:
        val = request.POST.get(name)
        if val is not None and str(val).strip() != '':
            return str(val).strip()
    return default

# Helper to interpret checkbox-like POST values as booleans
def post_bool(request, name):
    val = request.POST.get(name)
    if val is None:
        return False
    return str(val).strip().lower() in ('true', '1', 'on', 'yes')

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

def calculate_cargo_price(weight_kg, cargo_type):
    try:
        weight_kg = Decimal(str(weight_kg))
        if weight_kg <= 0:
            raise ValueError("Weight must be positive")

        base_rate = Decimal('5.00')  # base price per kg

        # Multipliers for cargo categories
        type_multiplier = {
            'Light Cargo': Decimal('1.2'),   # parcels, boxes
            'Heavy Cargo': Decimal('2.0'),   # machinery, materials
            'Bulk Cargo': Decimal('1.5'),    # produce, sand, fuel
            'Livestock': Decimal('2.5')      # animals require special handling
        }

        multiplier = type_multiplier.get(cargo_type, Decimal('1.0'))
        return weight_kg * base_rate * multiplier

    except (ValueError, TypeError) as e:
        logger.error(
            f"Invalid cargo weight or type: weight_kg={weight_kg}, cargo_type={cargo_type}, error={str(e)}"
        )
        raise ValueError("Invalid cargo weight or type")

def calculate_addon_price(addon_type, quantity):
    try:
        quantity = int(quantity)
        if quantity < 0:
            raise ValueError("Quantity cannot be negative")
        if addon_type not in dict(AddOn.ADD_ON_TYPE_CHOICES).keys():
            raise ValueError(f"Invalid add-on type: {addon_type}")
        prices = {
            'premium_seating': Decimal('20.00'),
            'priority_boarding': Decimal('10.00'),
            'cabin': Decimal('50.00'),
            'meal_breakfast': Decimal('15.00'),
            'meal_lunch': Decimal('15.00'),
            'meal_dinner': Decimal('15.00'),
            'meal_snack': Decimal('5.00')
        }
        return prices.get(addon_type, Decimal('0.00')) * Decimal(quantity)
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid addon quantity: addon_type={addon_type}, quantity={quantity}, error={str(e)}")
        raise ValueError("Invalid addon quantity")

def calculate_passenger_price(adults, children, infants, schedule):
    base_fare = schedule.route.base_fare or Decimal('35.50')
    return (
        Decimal(adults) * base_fare +
        Decimal(children) * base_fare * Decimal('0.5') +
        Decimal(infants) * base_fare * Decimal('0.1')
    )


def calculate_vehicle_price(vehicle_type, dimensions):
    try:
        # Example pricing logic based on vehicle type and dimensions
        base_price = Decimal('50.00')  # Base price for vehicles
        type_multiplier = {
            'car': Decimal('1.0'),
            'sedan': Decimal('1.0'),
            'truck': Decimal('1.5'),
            'van': Decimal('1.5'),
            'motorcycle': Decimal('0.5')
        }
        multiplier = type_multiplier.get(vehicle_type.lower(), Decimal('1.0'))

        # Optional: Adjust price based on dimensions (e.g., LxWxH in cm)
        if dimensions and re.match(r'^\d+x\d+x\d+$', dimensions):
            length, width, height = map(int, dimensions.split('x'))
            volume = length * width * height / 1_000_000  # Convert to cubic meters
            volume_surcharge = Decimal(volume) * Decimal('10.00')  # $10 per cubic meter
        else:
            volume_surcharge = Decimal('0.00')

        return base_price * multiplier + volume_surcharge
    except (ValueError, TypeError) as e:
        logger.error(f"Invalid vehicle data: vehicle_type={vehicle_type}, dimensions={dimensions}, error={str(e)}")
        raise ValueError("Invalid vehicle type or dimensions")


def calculate_total_price(adults, children, infants, schedule, add_cargo, cargo_type, weight_kg, addons,
                          add_vehicle=False, vehicle_type=None, vehicle_dimensions=None):
    passenger_price = calculate_passenger_price(adults, children, infants, schedule)
    cargo_price = calculate_cargo_price(weight_kg, cargo_type) if add_cargo and cargo_type and weight_kg else Decimal(
        '0.00')
    vehicle_price = calculate_vehicle_price(vehicle_type,
                                            vehicle_dimensions) if add_vehicle and vehicle_type and vehicle_dimensions else Decimal(
        '0.00')
    addon_price = sum(calculate_addon_price(addon['type'], addon['quantity']) for addon in addons)
    return passenger_price + cargo_price + vehicle_price + addon_price

def routes_api(request):
    try:
        routes = Route.objects.select_related('departure_port', 'destination_port').prefetch_related('schedules').all()
        routes_data = [
            {
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
                'schedule_id': route.schedules.first().id if route.schedules.exists() else None,
                'waypoints': route.waypoints or [
                    [route.departure_port.lat, route.departure_port.lng],
                    [route.destination_port.lat, route.destination_port.lng]
                ]
            }
            for route in routes
        ]
        return JsonResponse({'routes': routes_data})
    except Exception as e:
        logger.error(f"Routes API error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)

@require_GET
def homepage(request):
    now = timezone.now()
    schedules = Schedule.objects.filter(
        status='scheduled',
        departure_time__gt=now
    ).select_related('ferry', 'route__departure_port', 'route__destination_port').order_by('departure_time')

    route_input = request.GET.get('route', '').strip().lower()
    travel_date = request.GET.get('date', '').strip()

    logger.debug(f"Search parameters: route={route_input}, travel_date={travel_date}")

    if route_input:
        try:
            origin, destination = route_input.split('-to-')
            schedules = schedules.filter(
                route__departure_port__name__iexact=origin.strip(),
                route__destination_port__name__iexact=destination.strip()
            )
        except ValueError:
            messages.error(request, "Invalid route format. Use 'origin-to-destination' (e.g., nadi-to-suva).")

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

    routes = Route.objects.select_related('departure_port', 'destination_port').all()

    next_departure = schedules.first()
    next_departure_info = None
    if next_departure:
        next_departure_info = {
            'time': next_departure.departure_time.strftime('%a, %b %d, %H:%M'),
            'route': f"{next_departure.route.departure_port.name} to {next_departure.route.destination_port.name}",
            'schedule_id': next_departure.id,
            'estimated_duration': int(next_departure.route.estimated_duration.total_seconds() / 60) if next_departure.route.estimated_duration else None
        }

    weather_data = []
    schedule_route_ids = schedules.values_list('route_id', flat=True).distinct()
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
            weather_data.append({
                'route_id': schedule.route_id,
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
            weather_data.append({
                'route_id': schedule.route_id,
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

    context = {
        'schedules': schedules,
        'routes': routes,
        'form_data': {'route': route_input, 'date': travel_date},
        'weather_data': weather_data,
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
        status='scheduled',
        departure_time__gt=now
    ).select_related('ferry', 'route__departure_port', 'route__destination_port').order_by('departure_time')
    data = {
        'schedules': [
            {
                'id': s.id,
                'route_id': s.route.id,
                'departure_time': s.departure_time.isoformat(),
                'status': s.status,
                'available_seats': s.available_seats,
                'estimated_duration': int(s.route.estimated_duration.total_seconds() / 60) if s.route.estimated_duration else None,
                'route': {
                    'base_fare': str(s.route.base_fare),
                    'departure_port': s.route.departure_port.name,
                    'destination_port': s.route.destination_port.name
                }
            } for s in schedules
        ]
    }
    return JsonResponse(data)

@require_POST
def get_pricing(request):
    try:
        schedule_id = request.POST.get('schedule_id')
        adults = safe_int(request.POST.get('adults'))
        children = safe_int(request.POST.get('children'))
        infants = safe_int(request.POST.get('infants'))
        add_cargo = post_bool(request, 'add_cargo')
        cargo_type = request.POST.get('cargo_type', '')
        # support both cargo_weight_kg and weight_kg
        weight_kg = safe_float(request.POST.get('cargo_weight_kg', request.POST.get('weight_kg', 0)))
        license_plate = request.POST.get('cargo_license_plate', request.POST.get('license_plate', ''))
        addons = []
        for addon_type in dict(AddOn.ADD_ON_TYPE_CHOICES).keys():
            quantity = safe_int(request.POST.get(f'{addon_type}_quantity', 0))
            if quantity > 0:
                addons.append({'type': addon_type, 'quantity': quantity})

        if not schedule_id:
            return JsonResponse({'error': 'Schedule ID is required.'}, status=400)

        if any(n < 0 for n in [adults, children, infants, weight_kg]):
            return JsonResponse({'error': 'Passenger counts and weight cannot be negative.'}, status=400)

        if add_cargo and not (cargo_type and weight_kg and license_plate):
            return JsonResponse({'error': 'Cargo type, weight, and license plate are required when adding cargo.'}, status=400)

        schedule = get_object_or_404(Schedule, id=schedule_id)

        total_price = calculate_total_price(
            adults, children, infants, schedule, add_cargo, cargo_type, weight_kg, addons
        )

        breakdown = {
            'adults': str(Decimal(adults) * (schedule.route.base_fare or Decimal('35.50'))),
            'children': str(Decimal(children) * (schedule.route.base_fare or Decimal('35.50')) * Decimal('0.5')),
            'infants': str(Decimal(infants) * (schedule.route.base_fare or Decimal('35.50')) * Decimal('0.1')),
            'cargo': str(calculate_cargo_price(Decimal(weight_kg), cargo_type) if add_cargo else Decimal('0.00')),
            'addons': {addon['type']: str(calculate_addon_price(addon['type'], addon['quantity'])) for addon in addons}
        }

        return JsonResponse({'total_price': str(total_price), 'breakdown': breakdown})

    except Exception as e:
        logger.exception(f"Pricing error: {str(e)}")
        return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=400)



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

@require_POST
@csrf_protect
def validate_step(request):
    step = request.POST.get('step')
    errors = []

    if step == '1':
        schedule_id = request.POST.get('schedule_id', '').strip()
        guest_email = request.POST.get('guest_email', '').strip()
        is_authenticated = request.user.is_authenticated
        total_passengers = safe_int(request.POST.get('adults', '0')) + safe_int(request.POST.get('children', '0')) + safe_int(request.POST.get('infants', '0'))

        cache_key = f'schedule_exists_{schedule_id}'
        schedule_exists = cache.get(cache_key)
        if schedule_exists is None:
            try:
                schedule = Schedule.objects.get(id=schedule_id, status='scheduled', departure_time__gt=timezone.now())
                schedule_exists = True
                if total_passengers > schedule.available_seats:
                    errors.append({'field': 'schedule_id', 'message': f'Not enough seats available ({schedule.available_seats} remaining).'})
                cache.set(cache_key, schedule_exists, timeout=3600)
            except Schedule.DoesNotExist:
                schedule_exists = False
                errors.append({'field': 'schedule_id', 'message': 'Please select a valid ferry schedule.'})
                cache.set(cache_key, schedule_exists, timeout=3600)

        if not schedule_id or not schedule_exists:
            errors.append({'field': 'schedule_id', 'message': 'Please select a valid ferry schedule.'})

        if not is_authenticated:
            if not guest_email:
                errors.append({'field': 'guest_email', 'message': 'Guest email is required.'})
            elif not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', guest_email):
                errors.append({'field': 'guest_email', 'message': 'Please enter a valid email address.'})

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

        for p_type in ['adult', 'child', 'infant']:
            count = adults if p_type == 'adult' else children if p_type == 'child' else infants
            for i in range(count):
                validate_passenger_data(request, p_type, i, adults, errors)

    elif step == '3':
        add_vehicle = request.POST.get('add_vehicle') == 'true'
        add_cargo = request.POST.get('add_cargo') == 'true'

        # Validate vehicle fields
        if add_vehicle:
            # Support both array-like names and simple names from the frontend
            vehicle_type = get_post_field(request, ['vehicles[0][vehicle_type]', 'vehicle_type'], '').strip()
            vehicle_dimensions = get_post_field(request, ['vehicles[0][dimensions]', 'vehicle_dimensions'], '').strip()
            if not vehicle_type:
                errors.append({'field': 'vehicle_type', 'message': 'Vehicle type is required.'})
            if not vehicle_dimensions or not re.match(r'^\d+x\d+x\d+$', vehicle_dimensions):
                errors.append({'field': 'vehicle_dimensions', 'message': 'Vehicle dimensions must be in format LxWxH (e.g., 400x180x150).'})

        # Validate cargo fields
        if add_cargo:
            cargo_type = get_post_field(request, ['cargo[0][cargo_type]', 'cargo_type'], '').strip()
            cargo_weight = get_post_field(request, ['cargo[0][weight_kg]', 'cargo_weight_kg', 'weight_kg'], '').strip()
            cargo_dimensions = get_post_field(request, ['cargo[0][dimensions_cm]', 'cargo_dimensions_cm', 'dimensions_cm'], '').strip()
            if not cargo_type:
                errors.append({'field': 'cargo_type', 'message': 'Cargo type is required.'})
            try:
                weight = float(cargo_weight)
                if weight <= 0:
                    errors.append({'field': 'cargo_weight_kg', 'message': 'Cargo weight must be a positive number.'})
            except ValueError:
                errors.append({'field': 'cargo_weight_kg', 'message': 'Cargo weight must be a valid number.'})
            if not cargo_dimensions or not re.match(r'^\d+x\d+x\d+$', cargo_dimensions):
                errors.append({'field': 'cargo_dimensions_cm', 'message': 'Cargo dimensions must be in format LxWxH (e.g., 400x180x150).'})

    elif step == '4':
        if not request.POST.get('privacy_consent'):
            errors.append({'field': 'privacy-consent', 'message': 'You must agree to the privacy policy.'})

    if errors:
        return JsonResponse({'valid': False, 'errors': errors, 'step': step}, status=400)
    return JsonResponse({'valid': True, 'step': step})

@csrf_exempt
def validate_file(request):
    if request.method != 'POST':
        return JsonResponse({'valid': False, 'error': 'Invalid request method.'}, status=405)

    file = request.FILES.get('file')
    if not file:
        logger.error('No file provided for validation')
        return JsonResponse({'valid': False, 'error': 'No file provided.'}, status=400)

    try:
        FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])(file)
        if file.size > 2621440:  # 2.5MB
            logger.error(f"File too large: {file.name}, size: {file.size} bytes")
            return JsonResponse({'valid': False, 'error': 'File size exceeds 2.5MB limit. Please upload a smaller file.'}, status=413)
        # Placeholder for document verification logic
        verification_status = 'verified'  # Replace with actual verification (e.g., OCR or manual check)
        logger.info(f"File validated successfully: {file.name}")
        return JsonResponse({'valid': True, 'file_name': file.name, 'verification_status': verification_status})
    except ValidationError as e:
        logger.error(f"File validation error: {str(e)}")
        return JsonResponse({'valid': False, 'error': str(e)}, status=400)
    except Exception as e:
        logger.error(f"Unexpected file upload error: {str(e)}")
        return JsonResponse({'valid': False, 'error': 'Unexpected error during file validation. Please try again.'}, status=500)

@require_POST
def create_checkout_session(request):
    try:
        schedule_id = request.POST.get('schedule_id')
        total_price = request.POST.get('total_price')
        adults = safe_int(request.POST.get('adults', '0'))
        children = safe_int(request.POST.get('children', '0'))
        infants = safe_int(request.POST.get('infants', '0'))
        add_vehicle = request.POST.get('add_vehicle') == 'true'
        vehicle_type = get_post_field(request, ['vehicles[0][vehicle_type]', 'vehicle_type'])
        vehicle_dimensions = get_post_field(request, ['vehicles[0][dimensions]', 'vehicle_dimensions'])
        vehicle_license_plate = get_post_field(request, ['vehicles[0][license_plate]', 'vehicle_license_plate'])
        add_cargo = request.POST.get('add_cargo') == 'true'
        cargo_type = get_post_field(request, ['cargo[0][cargo_type]', 'cargo_type'])
        weight_kg = get_post_field(request, ['cargo[0][weight_kg]', 'cargo_weight_kg', 'weight_kg'])
        dimensions_cm = get_post_field(request, ['cargo[0][dimensions_cm]', 'cargo_dimensions_cm', 'dimensions_cm'])
        cargo_license_plate = get_post_field(request, ['cargo[0][license_plate]', 'cargo_license_plate', 'license_plate'])
        guest_email = request.POST.get('guest_email', '')
        addons = []
        for addon_type in dict(AddOn.ADD_ON_TYPE_CHOICES).keys():
            quantity = safe_int(request.POST.get(f'{addon_type}_quantity', 0))
            if quantity > 0:
                addons.append({'type': addon_type, 'quantity': quantity})

        logger.debug(f"create_checkout_session POST data: {dict(request.POST)}")

        errors = []
        if not schedule_id:
            errors.append({'field': 'schedule_id', 'message': 'Schedule ID is required.'})

        total_passengers = adults + children + infants
        if total_passengers <= 0:
            errors.append({'field': 'passengers', 'message': 'At least one passenger is required.'})

        # Validate vehicle fields
        if add_vehicle:
            if not vehicle_type:
                errors.append({'field': 'vehicle_type', 'message': 'Vehicle type is required when adding vehicle.'})
            if not vehicle_dimensions:
                errors.append({'field': 'vehicle_dimensions', 'message': 'Vehicle dimensions are required when adding vehicle.'})

        # Validate cargo fields
        if add_cargo:
            if not cargo_type:
                errors.append({'field': 'cargo_type', 'message': 'Cargo type is required when adding cargo.'})
            if not weight_kg:
                errors.append({'field': 'cargo_weight_kg', 'message': 'Cargo weight is required when adding cargo.'})
            else:
                try:
                    weight_kg_float = float(weight_kg)
                    if weight_kg_float <= 0:
                        errors.append({'field': 'cargo_weight_kg', 'message': 'Cargo weight must be greater than zero.'})
                except (ValueError, TypeError):
                    errors.append({'field': 'cargo_weight_kg', 'message': 'Cargo weight must be a valid number.'})

        # Validate passenger data
        for p_type in ['adult', 'child', 'infant']:
            count = adults if p_type == 'adult' else children if p_type == 'child' else infants
            for i in range(count):
                validate_passenger_data(request, p_type, i, adults, errors)

        if errors:
            logger.error(f"Validation errors: {errors}")
            return JsonResponse({'success': False, 'errors': errors}, status=400)

        schedule = get_object_or_404(Schedule, id=schedule_id)
        if schedule.available_seats < total_passengers:
            logger.error(f"Not enough seats: schedule_id={schedule_id}, available_seats={schedule.available_seats}, requested={total_passengers}")
            return JsonResponse({'errors': [{'field': 'schedule_id', 'message': 'Not enough seats available for this schedule.'}]}, status=400)
        if schedule.status != 'scheduled' or schedule.departure_time <= timezone.now():
            logger.error(f"Invalid schedule status or time: schedule_id={schedule_id}, status={schedule.status}")
            return JsonResponse({'errors': [{'field': 'schedule_id', 'message': 'Selected schedule is not available.'}]}, status=400)

        try:
            calculated_price = calculate_total_price(
                adults, children, infants, schedule, add_cargo, cargo_type, float(weight_kg) if weight_kg and add_cargo else 0, addons,
                add_vehicle, vehicle_type, vehicle_dimensions
            )
            if not total_price:
                total_price = calculated_price
            else:
                total_price = Decimal(total_price)
                if abs(total_price - calculated_price) > Decimal('0.01'):
                    logger.error(f"Price mismatch: provided={total_price}, calculated={calculated_price}")
                    return JsonResponse({'errors': [{'field': 'total_price', 'message': 'Provided total price does not match calculated price.'}]}, status=400)
            if total_price <= 0:
                logger.error(f"Invalid total_price: {total_price}")
                return JsonResponse({'errors': [{'field': 'total_price', 'message': 'Total price must be greater than zero.'}]}, status=400)
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid total_price format: {total_price}, error: {str(e)}")
            return JsonResponse({'errors': [{'field': 'total_price', 'message': 'Total price must be a valid number.'}]}, status=400)

        customer_email = request.user.email if request.user.is_authenticated else guest_email
        if not customer_email:
            return JsonResponse({'errors': [{'field': 'guest_email', 'message': 'A valid email is required for payment.'}]}, status=400)

        # Create Booking
        booking_kwargs = {
            'user': request.user if request.user.is_authenticated else None,
            'schedule': schedule,
            'guest_email': guest_email if not request.user.is_authenticated else None,
            'passenger_adults': adults,
            'passenger_children': children,
            'passenger_infants': infants,
            'total_price': total_price,
            'status': 'pending'
        }

        try:
            booking = Booking.objects.create(**booking_kwargs)
            booking.clean()
        except ValidationError as e:
            logger.error(f"Booking creation error: {str(e)}")
            return JsonResponse({'errors': [{'field': 'general', 'message': f'Failed to create booking: {str(e)}'}]}, status=400)

        # Create Passengers
        adult_passengers = []
        for p_type in ['adult', 'child', 'infant']:
            count = adults if p_type == 'adult' else children if p_type == 'child' else infants
            for i in range(count):
                passenger_data = validate_passenger_data(request, p_type, i, adults, [])
                passenger_kwargs = {
                    'booking': booking,
                    'first_name': passenger_data['first_name'],
                    'last_name': passenger_data['last_name'],
                    'passenger_type': p_type,
                    'document': passenger_data['document']
                }
                if p_type in ['adult', 'child'] and passenger_data['age']:
                    passenger_kwargs['age'] = int(passenger_data['age'])
                if p_type == 'infant' and passenger_data['dob']:
                    passenger_kwargs['date_of_birth'] = datetime.datetime.strptime(passenger_data['dob'], '%Y-%m-%d').date()

                try:
                    passenger = Passenger.objects.create(**passenger_kwargs)
                    passenger.clean()
                    if p_type in ['child', 'infant'] and passenger_data['linked_adult_index']:
                        try:
                            linked_adult = adult_passengers[int(passenger_data['linked_adult_index'])]
                            passenger.linked_adult = linked_adult
                            passenger.save()
                        except (IndexError, ValueError):
                            passenger.delete()
                            booking.delete()
                            errors.append({'field': f'{p_type}_linked_adult_{i}', 'message': f'{p_type.capitalize()} {i + 1}: Invalid linked adult.'})
                            return JsonResponse({'success': False, 'errors': errors}, status=400)
                    if p_type == 'adult':
                        adult_passengers.append(passenger)
                except ValidationError as e:
                    logger.error(f"Passenger creation error: {str(e)}")
                    passenger.delete()
                    booking.delete()
                    errors.append({'field': f'{p_type}_{i}', 'message': f'{p_type.capitalize()} {i + 1}: {str(e)}'})
                    return JsonResponse({'success': False, 'errors': errors}, status=400)

        # Create Vehicle
        if add_vehicle and vehicle_type and vehicle_dimensions:
            try:
                Vehicle.objects.create(
                    booking=booking,
                    vehicle_type=vehicle_type,
                    dimensions=vehicle_dimensions,
                    license_plate=vehicle_license_plate or '',
                    price=calculate_vehicle_price(vehicle_type, vehicle_dimensions)
                )
            except ValueError as e:
                logger.error(f"Vehicle creation error: {str(e)}")
                booking.delete()
                errors.append({'field': 'vehicle', 'message': f'Invalid vehicle data: {str(e)}'})
                return JsonResponse({'success': False, 'errors': errors}, status=400)

        # Create Cargo
        if add_cargo and cargo_type and weight_kg:
            try:
                weight_kg_float = float(weight_kg)
                if weight_kg_float <= 0:
                    errors.append({'field': 'cargo_weight_kg', 'message': 'Cargo weight must be greater than zero.'})
                    booking.delete()
                    return JsonResponse({'success': False, 'errors': errors}, status=400)
                Cargo.objects.create(
                    booking=booking,
                    cargo_type=cargo_type,
                    weight_kg=Decimal(weight_kg_float),
                    dimensions_cm=dimensions_cm or '',
                    license_plate=cargo_license_plate or '',
                    price=calculate_cargo_price(Decimal(weight_kg_float), cargo_type)
                )
            except (ValueError, TypeError) as e:
                logger.error(f"Cargo creation error: {str(e)}")
                booking.delete()
                errors.append({'field': 'cargo_weight_kg', 'message': 'Cargo weight must be a valid number.'})
                return JsonResponse({'success': False, 'errors': errors}, status=400)

        # Create Add-ons
        for addon in addons:
            try:
                AddOn.objects.create(
                    booking=booking,
                    add_on_type=addon['type'],
                    quantity=addon['quantity'],
                    price=calculate_addon_price(addon['type'], addon['quantity'])
                )
            except ValueError as e:
                logger.error(f"Add-on creation error: {str(e)}")
                booking.delete()
                errors.append({'field': 'addons', 'message': f'Invalid add-on: {str(e)}'})
                return JsonResponse({'success': False, 'errors': errors}, status=400)

        # Update available seats
        schedule.available_seats -= total_passengers
        schedule.save()

        # Create Stripe session
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
        )

        # Save session ID to booking
        booking.stripe_session_id = session.id
        booking.save()

        # Store booking_id in session
        request.session['booking_id'] = booking.id
        request.session['stripe_session_id'] = session.id
        if guest_email and not request.user.is_authenticated:
            request.session['guest_email'] = guest_email

        return JsonResponse({'sessionId': session.id})

    except Exception as e:
        logger.exception(f"Checkout session error: {str(e)}")
        return JsonResponse({'errors': [{'field': 'general', 'message': f"Checkout error: {str(e)}"}]}, status=400)

@login_required_allow_anonymous
def book_ticket(request):
    schedule_id = request.GET.get('schedule_id', '').strip()
    to_port = request.GET.get('to_port', '').strip().lower()

    available_schedules = Schedule.objects.filter(
        status='scheduled',
        departure_time__gt=timezone.now()
    ).select_related('ferry', 'route__departure_port', 'route__destination_port')

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

    if to_port:
        available_schedules = available_schedules.filter(
            route__destination_port__name__iexact=to_port
        )
        if not available_schedules.exists():
            logger.warning(f"No schedules found for to_port={to_port}")
            messages.error(request, f"No schedules available for destination: {to_port.capitalize()}.")

    form_data = {
        'step': request.GET.get('step', 1),
        'schedule_id': schedule_id or '',
        'adults': 0,
        'children': 0,
        'infants': 0,
        'guest_email': request.session.get('guest_email', ''),
        'add_vehicle': False,
        'add_cargo': False,
        'vehicle_type': '',
        'vehicle_dimensions': '',
        'vehicle_license_plate': '',
        'cargo_type': '',
        'weight_kg': '',
        'dimensions_cm': '',
        'license_plate': '',
        'privacy_consent': False,
        'to_port': to_port or '',
        **{f'{addon_type}_quantity': 0 for addon_type in dict(AddOn.ADD_ON_TYPE_CHOICES).keys()}
    }

    # Load passenger data from session if available
    passenger_data = request.session.get('passenger_data', [])
    for p_type in ['adult', 'child', 'infant']:
        key = 'children' if p_type == 'child' else f'{p_type}s'
        count = form_data.get(key, 0)
        for i in range(count):
            form_data.update({
                f'passenger_{p_type}_{i}_first_name': request.session.get(f'passenger_{p_type}_{i}_first_name', ''),
                f'passenger_{p_type}_{i}_last_name': request.session.get(f'passenger_{p_type}_{i}_last_name', ''),
                f'passenger_{p_type}_{i}_age': request.session.get(f'passenger_{p_type}_{i}_age', ''),
                f'passenger_{p_type}_{i}_dob': request.session.get(f'passenger_{p_type}_{i}_dob', ''),
                f'passenger_{p_type}_{i}_linked_adult': request.session.get(f'passenger_{p_type}_{i}_linked_adult', '')
            })

    if request.method == 'POST':
        logger.debug(f'POST data: {request.POST}')
        logger.debug(f'FILES data: {request.FILES}')
        errors = []

        adults = safe_int(request.POST.get('adults', '0'))
        children = safe_int(request.POST.get('children', '0'))
        infants = safe_int(request.POST.get('infants', '0'))
        schedule_id = request.POST.get('schedule_id')
        guest_email = request.POST.get('guest_email')
        add_vehicle = request.POST.get('add_vehicle') == 'true'
        add_cargo = request.POST.get('add_cargo') == 'true'
        # Support both array-like names and simple names from the frontend
        vehicle_type = get_post_field(request, ['vehicles[0][vehicle_type]', 'vehicle_type'])
        vehicle_dimensions = get_post_field(request, ['vehicles[0][dimensions]', 'vehicle_dimensions'])
        vehicle_license_plate = get_post_field(request, ['vehicles[0][license_plate]', 'vehicle_license_plate'])
        cargo_type = get_post_field(request, ['cargo[0][cargo_type]', 'cargo_type'])
        weight_kg = get_post_field(request, ['cargo[0][weight_kg]', 'cargo_weight_kg', 'weight_kg'])
        dimensions_cm = get_post_field(request, ['cargo[0][dimensions_cm]', 'cargo_dimensions_cm', 'dimensions_cm'])
        license_plate = get_post_field(request, ['cargo[0][license_plate]', 'cargo_license_plate', 'license_plate'])
        privacy_consent = request.POST.get('privacy_consent') == 'true'
        addons = []
        for addon_type in dict(AddOn.ADD_ON_TYPE_CHOICES).keys():
            quantity = safe_int(request.POST.get(f'{addon_type}_quantity', 0))
            if quantity > 0:
                addons.append({'type': addon_type, 'quantity': quantity, 'description': request.POST.get(f'{addon_type}_description', '')})

        if adults < 0 or children < 0 or infants < 0:
            errors.append({'field': 'general', 'message': 'Passenger counts cannot be negative.', 'step': 2})

        total_passengers = adults + children + infants
        if total_passengers == 0:
            errors.append({'field': 'general', 'message': 'At least one passenger is required.', 'step': 2})

        if (children > 0 or infants > 0) and adults == 0:
            errors.append({'field': 'general', 'message': 'Children and infants must be accompanied by an adult.', 'step': 2})

        form_data = {
            'schedule_id': schedule_id,
            'adults': adults,
            'children': children,
            'infants': infants,
            'guest_email': guest_email,
            'add_vehicle': add_vehicle,
            'add_cargo': add_cargo,
            'vehicle_type': vehicle_type,
            'vehicle_dimensions': vehicle_dimensions,
            'vehicle_license_plate': vehicle_license_plate,
            'cargo_type': cargo_type,
            'weight_kg': weight_kg,
            'dimensions_cm': dimensions_cm,
            'license_plate': license_plate,
            'privacy_consent': privacy_consent,
            'addons': addons
        }

        passenger_data = []
        for p_type in ['adult', 'child', 'infant']:
            count = adults if p_type == 'adult' else children if p_type == 'child' else infants
            for i in range(count):
                passenger = validate_passenger_data(request, p_type, i, adults, errors)
                passenger_data.append({
                    'type': p_type,
                    'first_name': passenger['first_name'],
                    'last_name': passenger['last_name'],
                    'age': passenger['age'],
                    'dob': passenger['dob'],
                    'linked_adult_index': passenger['linked_adult_index']
                })
                form_data.update({
                    f'passenger_{p_type}_{i}_first_name': passenger['first_name'],
                    f'passenger_{p_type}_{i}_last_name': passenger['last_name'],
                    f'passenger_{p_type}_{i}_age': passenger['age'],
                    f'passenger_{p_type}_{i}_dob': passenger['dob'],
                    f'passenger_{p_type}_{i}_linked_adult': passenger['linked_adult_index'],
                    f'passenger_{p_type}_{i}_document': passenger['document']
                })
                # Store passenger data in session
                request.session[f'passenger_{p_type}_{i}_first_name'] = passenger['first_name']
                request.session[f'passenger_{p_type}_{i}_last_name'] = passenger['last_name']
                request.session[f'passenger_{p_type}_{i}_age'] = passenger['age']
                request.session[f'passenger_{p_type}_{i}_dob'] = passenger['dob']
                request.session[f'passenger_{p_type}_{i}_linked_adult'] = passenger['linked_adult_index']

        if not schedule_id:
            errors.append({'field': 'schedule_id', 'message': 'Please select a valid ferry schedule.', 'step': 1})

        if not request.user.is_authenticated and not guest_email:
            errors.append({'field': 'guest_email', 'message': 'Guest email is required.', 'step': 1})

        if add_vehicle and not (vehicle_type and vehicle_dimensions):
            errors.append({'field': 'vehicle', 'message': 'Vehicle type and dimensions are required.', 'step': 3})

        if add_cargo and not (cargo_type and weight_kg):
            errors.append({'field': 'cargo', 'message': 'Cargo type and weight are required.', 'step': 3})
        if add_cargo and weight_kg:
            try:
                weight_kg_float = float(weight_kg)
                if weight_kg_float <= 0:
                    errors.append({'field': 'weight_kg', 'message': 'Cargo weight must be a positive number.', 'step': 3})
            except ValueError:
                errors.append({'field': 'weight_kg', 'message': 'Cargo weight must be a valid number.', 'step': 3})

        if not privacy_consent:
            errors.append({'field': 'privacy_consent', 'message': 'You must agree to the privacy policy.', 'step': 4})

        if errors:
            return JsonResponse({'success': False, 'errors': errors})

        schedule = get_object_or_404(Schedule, id=schedule_id, status='scheduled', departure_time__gt=timezone.now())
        if schedule.available_seats < total_passengers:
            errors.append({'field': 'schedule_id', 'message': 'Not enough seats available.', 'step': 1})
            return JsonResponse({'success': False, 'errors': errors})

        total_price = calculate_total_price(
            adults, children, infants, schedule, add_cargo, cargo_type, weight_kg, addons, add_vehicle, vehicle_type, vehicle_dimensions
        )

        base_fare = schedule.route.base_fare or Decimal('35.50')
        summary = {
            'schedule': {
                'route': f"{schedule.route.departure_port.name} to {schedule.route.destination_port.name}",
                'departure_time': schedule.departure_time.strftime("%a, %b %d, %H:%M"),
                'estimated_duration': int(schedule.route.estimated_duration.total_seconds() / 60) if schedule.route.estimated_duration else "N/A"
            },
            'passengers': passenger_data,
            'vehicle': {
                'type': vehicle_type,
                'dimensions': vehicle_dimensions,
                'license_plate': vehicle_license_plate,
                'price': str(calculate_vehicle_price(vehicle_type, vehicle_dimensions)) if add_vehicle else None
            } if add_vehicle else None,
            'cargo': {
                'type': cargo_type,
                'weight_kg': weight_kg,
                'license_plate': license_plate,
                'price': str(calculate_cargo_price(Decimal(weight_kg), cargo_type)) if add_cargo and weight_kg else None
            } if add_cargo else None,
            'addons': [
                {'type': addon['type'], 'quantity': addon['quantity'], 'price': str(calculate_addon_price(addon['type'], addon['quantity']))}
                for addon in addons
            ],
            'pricing': {
                'adults': str(Decimal(adults) * base_fare),
                'children': str(Decimal(children) * base_fare * Decimal('0.5')),
                'infants': str(Decimal(infants) * base_fare * Decimal('0.1')),
                'vehicle': str(calculate_vehicle_price(vehicle_type, vehicle_dimensions)) if add_vehicle else "0.00",
                'cargo': str(calculate_cargo_price(Decimal(weight_kg), cargo_type)) if add_cargo and weight_kg else "0.00",
                'addons': str(sum(calculate_addon_price(addon['type'], addon['quantity']) for addon in addons)),
                'total': str(total_price)
            }
        }

        request.session['passenger_data'] = passenger_data
        request.session.modified = True

        return JsonResponse({
            'success': True,
            'summary': summary
        })

    summary = None
    if form_data['step'] == '4' and schedule_id:
        try:
            schedule = Schedule.objects.get(id=schedule_id, status='scheduled', departure_time__gt=timezone.now())
            adults = safe_int(form_data['adults'])
            children = safe_int(form_data['children'])
            infants = safe_int(form_data['infants'])
            add_vehicle = form_data['add_vehicle']
            add_cargo = form_data['add_cargo']
            vehicle_type = form_data['vehicle_type']
            vehicle_dimensions = form_data['vehicle_dimensions']
            vehicle_license_plate = form_data['vehicle_license_plate']
            cargo_type = form_data['cargo_type']
            weight_kg = safe_float(form_data['weight_kg'])
            license_plate = form_data['license_plate']
            addons = form_data['addons']

            # Populate passenger_data from session or form_data
            passenger_data = []
            for p_type in ['adult', 'child', 'infant']:
                count = adults if p_type == 'adult' else children if p_type == 'child' else infants
                for i in range(count):
                    passenger = {
                        'type': p_type,
                        'first_name': form_data.get(f'passenger_{p_type}_{i}_first_name', request.session.get(f'passenger_{p_type}_{i}_first_name', 'Unknown')),
                        'last_name': form_data.get(f'passenger_{p_type}_{i}_last_name', request.session.get(f'passenger_{p_type}_{i}_last_name', '')),
                        'age': form_data.get(f'passenger_{p_type}_{i}_age', request.session.get(f'passenger_{p_type}_{i}_age', '')),
                        'dob': form_data.get(f'passenger_{p_type}_{i}_dob', request.session.get(f'passenger_{p_type}_{i}_dob', '')),
                        'linked_adult_index': form_data.get(f'passenger_{p_type}_{i}_linked_adult', request.session.get(f'passenger_{p_type}_{i}_linked_adult', ''))
                    }
                    passenger_data.append(passenger)

            total_price = calculate_total_price(
                adults, children, infants, schedule, add_cargo, cargo_type, weight_kg, addons, add_vehicle, vehicle_type, vehicle_dimensions
            )
            base_fare = schedule.route.base_fare or Decimal('35.50')
            summary = {
                'schedule': {
                    'route': f"{schedule.route.departure_port.name} to {schedule.route.destination_port.name}",
                    'departure_time': schedule.departure_time.strftime("%a, %b %d, %H:%M"),
                    'estimated_duration': int(schedule.route.estimated_duration.total_seconds() / 60) if schedule.route.estimated_duration else "N/A"
                },
                'passengers': passenger_data,
                'vehicle': {
                    'type': vehicle_type,
                    'dimensions': vehicle_dimensions,
                    'license_plate': vehicle_license_plate,
                    'price': str(calculate_vehicle_price(vehicle_type, vehicle_dimensions)) if add_vehicle else None
                } if add_vehicle else None,
                'cargo': {
                    'type': cargo_type,
                    'weight_kg': weight_kg,
                    'license_plate': license_plate,
                    'price': str(calculate_cargo_price(Decimal(weight_kg), cargo_type)) if add_cargo and weight_kg else None
                } if add_cargo else None,
                'addons': [
                    {'type': addon['type'], 'quantity': addon['quantity'], 'price': str(calculate_addon_price(addon['type'], addon['quantity']))}
                    for addon in addons
                ],
                'pricing': {
                    'adults': str(Decimal(adults) * base_fare),
                    'children': str(Decimal(children) * base_fare * Decimal('0.5')),
                    'infants': str(Decimal(infants) * base_fare * Decimal('0.1')),
                    'vehicle': str(calculate_vehicle_price(vehicle_type, vehicle_dimensions)) if add_vehicle else "0.00",
                    'cargo': str(calculate_cargo_price(Decimal(weight_kg), cargo_type)) if add_cargo and weight_kg else "0.00",
                    'addons': str(sum(calculate_addon_price(addon['type'], addon['quantity']) for addon in addons)),
                    'total': str(total_price)
                }
            }
        except Schedule.DoesNotExist:
            messages.error(request, "Selected schedule is not available.")

    return render(request, 'bookings/book.html', {
        'schedules': available_schedules,
        'user': request.user,
        'form_data': form_data,
        'debug': settings.DEBUG,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY,
        'summary': summary
    })

def ticket_detail(request, ticket_id):
    ticket = get_object_or_404(Ticket, id=ticket_id)
    return render(request, "ticket.html", {"ticket": ticket})

@login_required_allow_anonymous
def view_tickets(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    if request.user.is_authenticated and booking.user != request.user:
        logger.error(f"Authorization failed: User {request.user} not authorized for booking {booking_id}")
        return HttpResponseForbidden("You are not authorized to view this booking.")
    if not request.user.is_authenticated and booking.guest_email != request.session.get('guest_email'):
        logger.error(f"Authorization failed: Guest email mismatch for booking {booking_id}")
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

def booking_pdf(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)
    tickets = booking.tickets.all()

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Path to logo
    logo_path = os.path.join(settings.BASE_DIR, "static/logo.png")

    # Loop through each ticket in the booking
    for ticket in tickets:
        # Add Logo
        if os.path.exists(logo_path):
            p.drawImage(logo_path, 40, height - 120, width=120, height=60, mask='auto')

        # Header Title
        p.setFont("Helvetica-Bold", 20)
        p.drawString(180, height - 80, "Fiji Ferry Boarding Pass")

        # Passenger Info
        p.setFont("Times-Roman", 12)  # more professional than plain Helvetica
        y = height - 150
        passenger_name = getattr(ticket.passenger, "first_name", "") + " " + getattr(ticket.passenger, "last_name", "")
        if passenger_name.strip():
            p.drawString(40, y, f"Passenger: {passenger_name} ({ticket.passenger.passenger_type.title()})")
        else:
            p.drawString(40, y, f"Passenger Type: {ticket.passenger.passenger_type.title()}")
        y -= 20
        p.drawString(40, y, f"Booking ID: #{ticket.booking.id}")
        y -= 20
        p.drawString(40, y, f"Ticket Status: {ticket.ticket_status.title()}")
        y -= 20
        p.drawString(40, y, f"Issued: {ticket.issued_at.strftime('%b %d, %Y %H:%M')}")

        # Schedule Section
        y -= 40
        p.setFont("Helvetica-Bold", 14)
        p.drawString(40, y, "Schedule")
        p.setFont("Times-Roman", 12)
        y -= 20
        p.drawString(40, y, f"Ferry: {ticket.booking.schedule.ferry.name}")
        y -= 20
        p.drawString(40, y, f"Route: {ticket.booking.schedule.route.departure_port} → {ticket.booking.schedule.route.destination_port}")
        y -= 20
        p.drawString(40, y, f"Departure: {ticket.booking.schedule.departure_time.strftime('%b %d, %Y %H:%M')}")
        y -= 20
        p.drawString(40, y, f"Arrival: {ticket.booking.schedule.arrival_time.strftime('%b %d, %Y %H:%M')}")

        # QR Code (bigger)
        if ticket.qr_code:
            qr_path = ticket.qr_code.path
            p.drawImage(qr_path, width - 220, height - 320, width=180, height=180)

        # Footer
        p.setFont("Helvetica-Oblique", 10)
        p.drawString(40, 40, "⚓ Please present this boarding pass with a valid ID when boarding.")

        # New page for next ticket
        p.showPage()

    p.save()
    buffer.seek(0)

    return FileResponse(buffer, as_attachment=True, filename=f"Booking_{booking.id}_Tickets.pdf")

@login_required
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

def payment_success(request):
    booking_id = request.session.get('booking_id')
    session_id = request.GET.get('session_id') or request.session.get('stripe_session_id')

    logger.debug(f"Payment success: booking_id={booking_id}, session_id={session_id}")

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

    if not booking_id and session_id:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            booking_id = session.metadata.get('booking_id')
            guest_email = session.metadata.get('guest_email')
            if guest_email and not request.session.get('guest_email'):
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

    if request.user.is_authenticated and booking.user != request.user:
        logger.error(f"Authorization failed: User {request.user} not authorized for booking {booking_id}")
        return HttpResponseForbidden("You are not authorized to view this booking.")
    if not request.user.is_authenticated and booking.guest_email != request.session.get('guest_email'):
        logger.error(f"Authorization failed: Guest email mismatch for booking {booking_id}")
        return HttpResponseForbidden("You are not authorized to view this booking.")

    if booking.evaluated_status == 'cancelled':
        logger.error(f"Booking {booking_id} is cancelled or expired")
        messages.error(request, "This booking is no longer valid.")
        return redirect('bookings:booking_history')

    try:
        if session_id == 'debug-mode' and settings.DEBUG:
            payment, _ = Payment.objects.get_or_create(
                booking=booking,
                session_id='debug-session',
                defaults={
                    'payment_method': 'stripe',
                    'amount': booking.total_price,
                    'payment_status': 'completed',
                    'transaction_id': 'debug-transaction',
                    'payment_intent_id': 'debug-transaction'
                }
            )
            booking.status = 'confirmed'
            booking.payment_intent_id = 'debug-transaction'
            booking.save()
            logger.info(f"Debug mode payment processed for booking {booking.id}")
        else:
            if not session_id:
                logger.error(f"No valid session_id found for booking {booking_id}")
                messages.error(request, "Invalid payment session. Please try again or contact support.")
                return redirect('bookings:booking_history')

            session = stripe.checkout.Session.retrieve(session_id, expand=['payment_intent'])
            if not session.payment_intent:
                logger.error(f"No payment_intent found for session {session_id}, booking {booking_id}")
                messages.error(request, "Payment could not be verified. Please contact support.")
                return redirect('bookings:booking_history')

            if session.metadata.get('booking_id') != str(booking_id):
                logger.error(f"Session {session_id} metadata mismatch for booking {booking_id}")
                messages.error(request, "Invalid payment session. Please contact support.")
                return redirect('bookings:booking_history')

            payment, created = Payment.objects.get_or_create(
                booking=booking,
                session_id=session.id,
                defaults={
                    'payment_method': 'stripe',
                    'amount': Decimal(session.amount_total) / 100,
                    'payment_status': 'pending'
                }
            )

            payment.payment_intent_id = session.payment_intent.id
            payment.transaction_id = session.payment_intent.id
            payment.amount = Decimal(session.payment_intent.amount) / 100
            if session.payment_intent.status == 'succeeded':
                payment.payment_status = 'completed'
                booking.status = 'confirmed'
                booking.payment_intent_id = session.payment_intent.id
                booking.stripe_session_id = session.id
                booking.save()
                logger.info(f"Payment confirmed for booking {booking.id}")
            else:
                logger.warning(f"Payment not completed for booking {booking.id}: status={session.payment_intent.status}")
                messages.error(request, f"Payment is not completed yet. Status: {session.payment_intent.status}")
                return redirect('bookings:booking_history')
            payment.save()

        # Check if tickets already exist
        if Ticket.objects.filter(booking=booking).count() == booking.passengers.count():
            logger.info(f"Tickets already generated for booking {booking.id}")
            messages.success(request, f'Booking #{booking.id} confirmed! Tickets already generated.')
        else:
            # Verify passengers exist
            if not booking.passengers.exists():
                logger.error(f"No passengers found for booking {booking.id}")
                messages.error(request, "No passengers associated with booking. Please contact support.")
                return redirect('bookings:booking_history')

            # Generate tickets
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
                        ticket.full_clean()  # Validate model before saving
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
                            messages.error(request, "Error saving ticket QR code. Please contact support.")
                            return redirect('bookings:booking_history')
                    except ValidationError as ve:
                        logger.error(f"Validation error for ticket, passenger {passenger.id}: {str(ve)}")
                        messages.error(request, "Error generating tickets: Invalid ticket data. Please contact support.")
                        return redirect('bookings:booking_history')
                    except Exception as e:
                        logger.error(f"Error generating ticket for passenger {passenger.id}: {str(e)}")
                        messages.error(request, "Error generating tickets. Please contact support.")
                        return redirect('bookings:booking_history')

        # Send confirmation email
        try:
            email_subject = f'Booking Confirmation #{booking.id}'
            email_body = (
                f'Your booking has been confirmed!\n\n'
                f'Booking ID: {booking.id}\n'
                f'Route: {booking.schedule.route.departure_port.name} to {booking.schedule.route.destination_port.name}\n'
                f'Departure: {booking.schedule.departure_time.strftime("%a, %b %d, %H:%M")}\n'
                f'Estimated Duration: {int(booking.schedule.route.estimated_duration.total_seconds() / 60) if booking.schedule.route.estimated_duration else "N/A"} minutes\n'
                f'Passengers: {booking.passenger_adults} Adults, {booking.passenger_children} Children, {booking.passenger_infants} Infants\n'
                f'Total Price: FJD {booking.total_price}\n'
            )
            if booking.cargo.exists():
                cargo = booking.cargo.first()
                email_body += (
                    f'\nCargo Details:\n'
                    f'Type: {cargo.cargo_type.capitalize()}\n'
                    f'Weight: {cargo.weight_kg} kg\n'
                    f'License Plate: {cargo.license_plate or "N/A"}\n'
                    f'Price: FJD {cargo.price}\n'
                )
            if booking.addons.exists():
                email_body += '\nAdd-ons:\n'
                for addon in booking.addons.all():
                    email_body += f'- {addon.get_add_on_type_display()}: FJD {addon.price}\n'

            email_body += (
                f'\nView your tickets: {request.build_absolute_uri(reverse("bookings:view_tickets", args=[booking.id]))}\n'
                'Thank you for choosing our ferry service!'
            )

            send_mail(
                email_subject,
                email_body,
                settings.DEFAULT_FROM_EMAIL,
                [booking.user.email if booking.user else booking.guest_email],
                fail_silently=True
            )
            logger.info(f"Confirmation email sent for booking {booking.id}")
        except Exception as e:
            logger.error(f"Error sending confirmation email for booking {booking.id}: {str(e)}")
            messages.warning(request, "Booking confirmed, but there was an issue sending the confirmation email. Please check your email later or contact support.")

        messages.success(request, f'Booking #{booking.id} confirmed! Tickets have been generated and emailed.')
        request.session.pop('booking_id', None)
        request.session.pop('stripe_session_id', None)
        request.session.pop('guest_email', None)

        return redirect('bookings:view_tickets', booking_id=booking.id)

    except stripe.error.StripeError as e:
        logger.error(f"Stripe error for booking {booking_id}: {str(e)}")
        messages.error(request, f"Payment verification failed: {str(e)}. Please contact support.")
        return redirect('bookings:booking_history')
    except Exception as e:
        logger.error(f"Unexpected error for booking {booking_id}: {str(e)}")
        messages.error(request, "An unexpected error occurred during payment processing. Please contact support.")
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
            payment, created = Payment.objects.get_or_create(
                booking=booking,
                session_id=session_id,
                defaults={
                    'payment_method': 'stripe',
                    'amount': Decimal(session.get('amount_total', 0)) / 100,
                    'payment_status': 'pending'
                }
            )
            payment.payment_intent_id = payment_intent_id
            payment.transaction_id = payment_intent_id
            payment.amount = Decimal(session.get('amount_total', 0)) / 100
            payment.payment_status = 'completed'
            payment.save()

            booking.status = 'confirmed'
            booking.payment_intent_id = payment_intent_id
            booking.stripe_session_id = session_id
            booking.save()

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
            email_subject = f'Booking Confirmation #{booking.id}'
            email_body = (
                f'Your booking has been confirmed!\n\n'
                f'Booking ID: {booking.id}\n'
                f'Route: {booking.schedule.route.departure_port.name} → {booking.schedule.route.destination_port.name}\n'
                f'Departure: {booking.schedule.departure_time.strftime("%a, %b %d, %H:%M")}\n'
                f'Estimated Duration: {int(booking.schedule.route.estimated_duration.total_seconds() / 60) if booking.schedule.route.estimated_duration else "N/A"} minutes\n'
                f'Passengers: {booking.passenger_adults} Adults, {booking.passenger_children} Children, {booking.passenger_infants} Infants\n'
                f'Total Price: FJD {booking.total_price}\n'
            )

            if booking.cargo.exists():
                cargo = booking.cargo.first()
                email_body += (
                    f'\nCargo Details:\n'
                    f'Type: {cargo.cargo_type.capitalize()}\n'
                    f'Weight: {cargo.weight_kg} kg\n'
                    f'License Plate: {cargo.license_plate}\n'
                    f'Price: FJD {cargo.price}\n'
                )

            if booking.addons.exists():
                email_body += '\nAdd-ons:\n'
                for addon in booking.addons.all():
                    email_body += f'- {addon.get_add_on_type_display()}: FJD {addon.price}\n'

            email_body += (
                f'\nView your tickets: {request.build_absolute_uri(reverse("bookings:view_tickets", args=[booking.id]))}\n'
                'Thank you for choosing our ferry service!'
            )

            send_mail(
                email_subject,
                email_body,
                settings.DEFAULT_FROM_EMAIL,
                [booking.user.email if booking.user else booking.guest_email],
                fail_silently=True
            )

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
            return render(request, 'bookings/modify.html', {'form': form, 'booking': booking})

        if new_schedule.available_seats < total_passengers:
            messages.error(request, "Not enough seats available in the selected schedule.")
            return render(request, 'bookings/modify.html', {'form': form, 'booking': booking})

        old_total_price = booking.total_price
        new_total_price = calculate_total_price(
            new_adults, new_children, new_infants, new_schedule,
            booking.cargo.exists(), booking.cargo.first().cargo_type if booking.cargo.exists() else None,
            booking.cargo.first().weight_kg if booking.cargo.exists() else 0,
            [{'type': addon.add_on_type, 'quantity': addon.quantity} for addon in booking.addons.all()]
        )

        booking.schedule.available_seats += (
                    booking.passenger_adults + booking.passenger_children + booking.passenger_infants)
        booking.schedule.save()

        booking.schedule = new_schedule
        booking.passenger_adults = new_adults
        booking.passenger_children = new_children
        booking.passenger_infants = new_infants
        booking.total_price = new_total_price
        booking.save()

        new_schedule.available_seats -= total_passengers
        new_schedule.save()

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

    return render(request, 'bookings/modify.html', {
        'form': form,
        'booking': booking,
        'cutoff_time': now + datetime.timedelta(hours=6)
    })

@login_required
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    now = timezone.now()

    if booking.status != 'confirmed' or booking.schedule.departure_time <= now + datetime.timedelta(hours=6):
        messages.error(request, "This booking cannot be cancelled.")
        return redirect('bookings:booking_history')

    if request.method == 'POST':
        try:
            if booking.payment_intent_id:
                refund = stripe.Refund.create(
                    payment_intent=booking.payment_intent_id,
                    amount=int(booking.total_price * 100)
                )
                Payment.objects.create(
                    booking=booking,
                    payment_method='stripe',
                    amount=-booking.total_price,
                    payment_status='refunded',
                    transaction_id=refund.id
                )

            booking.status = 'cancelled'
            booking.schedule.available_seats += (
                booking.passenger_adults + booking.passenger_children + booking.passenger_infants
            )
            booking.schedule.save()
            booking.save()

            for ticket in booking.tickets.all():
                ticket.ticket_status = 'cancelled'
                ticket.save()

            messages.success(request, f"Booking #{booking.id} has been cancelled and refunded.")
            return redirect('bookings:booking_history')

        except stripe.error.StripeError as e:
            logger.error(f"Refund error for booking {booking.id}: {str(e)}")
            messages.error(request, f"Refund processing failed: {str(e)}. Please contact support.")
            return redirect('bookings:booking_history')
        except Exception as e:
            logger.error(f"Unexpected error cancelling booking {booking.id}: {str(e)}")
            messages.error(request, "An unexpected error occurred. Please contact support.")
            return redirect('bookings:booking_history')

    return render(request, 'bookings/cancel.html', {
        'booking': booking,
        'cutoff_time': now + datetime.timedelta(hours=6)
    })

@login_required
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
