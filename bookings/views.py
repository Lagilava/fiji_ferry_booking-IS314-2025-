import logging
import os
import stripe
from datetime import timedelta
import requests
from django.conf import settings
from django.core.cache import cache
from django.core.validators import FileExtensionValidator
from django.db.models import Subquery, Max, OuterRef
from datetime import datetime
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseForbidden, HttpResponse, StreamingHttpResponse
from django.contrib import messages
from django.views.decorators.cache import cache_page
from django.views.decorators.http import require_POST, require_GET
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from io import BytesIO
from django.core.files.base import ContentFile
import qrcode
import json
import time
import uuid

from .models import Schedule, Booking, Passenger, Payment, Ticket, Cargo, Route, DocumentVerification, WeatherCondition
from .decorators import login_required_allow_anonymous
from .forms import CargoBookingForm, ModifyBookingForm

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

def calculate_cargo_price(weight_kg, cargo_type):
    base_rate = Decimal('5.00')
    type_multiplier = {
        'parcel': Decimal('1.0'),
        'pallet': Decimal('1.2'),
        'vehicle': Decimal('3.0'),
        'bulk': Decimal('1.5')
    }
    return weight_kg * base_rate * type_multiplier.get(cargo_type, Decimal('1.0'))


def calculate_passenger_price(adults, youths, children, infants, schedule):
    base_fare = schedule.route.base_fare or Decimal('35.50')
    return (
        adults * base_fare +
        youths * base_fare * Decimal('0.75') +  # Youths pay 75% of adult fare
        children * base_fare * Decimal('0.5') +
        infants * base_fare * Decimal('0.1')
    )

def calculate_total_price(adults, youths, children, infants, schedule, add_cargo, cargo_type, weight_kg, is_emergency):
    passenger_price = calculate_passenger_price(adults, youths, children, infants, schedule)
    cargo_price = calculate_cargo_price(Decimal(weight_kg), cargo_type) if add_cargo and cargo_type and weight_kg else Decimal('0.00')
    emergency_surcharge = Decimal('50.00') if is_emergency else Decimal('0.00')
    return passenger_price + cargo_price + emergency_surcharge

@require_GET
def weather_stream(request):
    def stream():
        since = request.GET.get('since')
        last_sent = None
        if since:
            try:
                last_sent = timezone.datetime.fromisoformat(since.replace('Z', '+00:00'))
                if not timezone.is_aware(last_sent):
                    last_sent = timezone.make_aware(last_sent)
            except ValueError:
                logger.error(f"Invalid 'since' parameter: {since}")
                yield f"data: {json.dumps({'weather': [], 'error': 'Invalid since parameter'})}\n\n"
                time.sleep(5)
                return

        while True:
            try:
                # Get routes for active schedules only
                now = timezone.now()
                schedules = Schedule.objects.filter(
                    status='scheduled',
                    departure_time__gt=now
                ).select_related('route')
                route_ids = schedules.values_list('route_id', flat=True).distinct()
                routes = Route.objects.filter(id__in=route_ids).select_related('departure_port')

                weather_data = []
                # Subquery to get the latest updated_at for each route_id
                latest_conditions_subquery = WeatherCondition.objects.filter(
                    route_id=OuterRef('route_id'),
                    expires_at__gt=timezone.now()
                ).values('route_id').annotate(
                    latest_updated=Max('updated_at')
                ).values('latest_updated')

                # Main query to get the latest WeatherCondition for scheduled routes
                latest_conditions = WeatherCondition.objects.filter(
                    route_id__in=route_ids,
                    expires_at__gt=timezone.now(),
                    updated_at__in=Subquery(latest_conditions_subquery)
                )
                if last_sent:
                    latest_conditions = latest_conditions.filter(updated_at__gt=last_sent)

                latest_per_route = {wc.route_id: wc for wc in latest_conditions}

                for route in routes:
                    wc = latest_per_route.get(route.id)
                    if wc:
                        weather_data.append({
                            'route_id': route.id,
                            'condition': wc.condition,
                            'temperature': safe_float(wc.temperature),
                            'wind_speed': safe_float(wc.wind_speed),
                            'precipitation_probability': safe_float(wc.precipitation_probability),
                            'port': wc.port.name,
                            'is_expired': wc.is_expired(),
                            'updated_at': wc.updated_at.isoformat(),
                            'expires_at': wc.expires_at.isoformat(),
                            'error': None
                        })
                    elif not last_sent:
                        # Only include missing data if no 'since' filter is applied
                        weather_data.append({
                            'route_id': route.id,
                            'condition': None,
                            'temperature': None,
                            'wind_speed': None,
                            'precipitation_probability': None,
                            'port': route.departure_port.name,
                            'is_expired': True,
                            'updated_at': None,
                            'expires_at': None,
                            'error': 'No valid weather data available'
                        })

                if weather_data:
                    yield f"data: {json.dumps({'weather': weather_data})}\n\n"
                yield ":\n\n"  # keep-alive
                last_sent = timezone.now() if weather_data else last_sent
                time.sleep(30)
            except Exception as e:
                logger.error(f"SSE stream error: {str(e)}")
                yield f"data: {json.dumps({'weather': [], 'error': str(e)})}\n\n"
                time.sleep(5)

    response = StreamingHttpResponse(stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


@require_GET
@cache_page(60 * 10)  # Cache for 10 minutes
def get_weather_conditions(request):
    # Parse 'since' parameter
    since = request.GET.get('since')
    last_updated = None
    if since:
        try:
            last_updated = timezone.datetime.fromisoformat(since.replace('Z', '+00:00'))
            if not timezone.is_aware(last_updated):
                last_updated = timezone.make_aware(last_updated)
        except ValueError:
            logger.error(f"Invalid 'since' parameter: {since}")
            return JsonResponse({'weather': [], 'error': 'Invalid since parameter'}, status=400)

    # Get routes for active schedules only
    now = timezone.now()
    schedules = Schedule.objects.filter(
        status='scheduled',
        departure_time__gt=now
    ).select_related('route')
    route_ids = schedules.values_list('route_id', flat=True).distinct()
    routes = Route.objects.filter(id__in=route_ids).select_related('departure_port')

    weather_data = []

    # Prefetch existing weather conditions for scheduled routes
    weather_conditions = WeatherCondition.objects.filter(
        route_id__in=route_ids,
        expires_at__gt=timezone.now()
    )
    if last_updated:
        weather_conditions = weather_conditions.filter(updated_at__gt=last_updated)

    weather_cache = {(w.route_id, w.port_id): w for w in weather_conditions}

    for route in routes:
        key = (route.id, route.departure_port.id)
        weather = weather_cache.get(key)

        if weather:
            # Use cached data
            weather_data.append({
                'route_id': route.id,
                'port': route.departure_port.name,
                'temperature': safe_float(weather.temperature),
                'wind_speed': safe_float(weather.wind_speed),
                'precipitation_probability': safe_float(weather.precipitation_probability),
                'condition': weather.condition,
                'updated_at': weather.updated_at.isoformat(),
                'expires_at': weather.expires_at.isoformat()
            })
            continue

        if not last_updated:
            # Fetch fresh data from WeatherAPI only if no 'since' filter
            try:
                response = requests.get(
                    'https://api.weatherapi.com/v1/current.json',
                    params={
                        'key': settings.WEATHER_API_KEY,
                        'q': f"{route.departure_port.lat},{route.departure_port.lng}",
                        'aqi': 'no'
                    },
                    timeout=5  # prevent hanging requests
                )
                response.raise_for_status()
                data = response.json()

                temperature = data['current']['temp_c']
                wind_speed = data['current']['wind_kph']
                condition = data['current']['condition']['text']
                precipitation_probability = data['current'].get('precip_in', 0) * 100  # Convert inches to percentage

                # Save/update in DB
                WeatherCondition.objects.update_or_create(
                    route=route,
                    port=route.departure_port,
                    defaults={
                        'temperature': temperature,
                        'wind_speed': wind_speed,
                        'precipitation_probability': precipitation_probability,
                        'condition': condition,
                        'expires_at': timezone.now() + timedelta(minutes=30),
                        'updated_at': timezone.now()
                    }
                )

                weather_data.append({
                    'route_id': route.id,
                    'port': route.departure_port.name,
                    'temperature': temperature,
                    'wind_speed': wind_speed,
                    'precipitation_probability': precipitation_probability,
                    'condition': condition,
                    'updated_at': timezone.now().isoformat(),
                    'expires_at': (timezone.now() + timedelta(minutes=30)).isoformat()
                })

            except requests.RequestException as e:
                logger.error(f"WeatherAPI error for {route.departure_port.name}: {str(e)}")
                weather_data.append({
                    'route_id': route.id,
                    'port': route.departure_port.name,
                    'temperature': None,
                    'wind_speed': None,
                    'precipitation_probability': None,
                    'condition': None,
                    'updated_at': None,
                    'expires_at': None,
                    'error': 'Weather data unavailable'
                })

    return JsonResponse({'weather': weather_data})


def privacy_policy(request):
    return render(request, 'privacy_policy.html')


def generate_cargo_qr(request, cargo):
    qr_data = request.build_absolute_uri(
        reverse('bookings:view_cargo', args=[
            f"CargoID:{cargo.id}|Booking:{cargo.booking.id}|Type:{cargo.cargo_type}|Weight:{cargo.weight_kg}kg"
        ])
    )
    qr = qrcode.make(qr_data)
    buffer = BytesIO()
    qr.save(buffer, format='PNG')
    cargo.qr_code.save(f"cargo_{cargo.id}.png", ContentFile(buffer.getvalue()))


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
                'estimated_duration': int(route.estimated_duration.total_seconds()) if route.estimated_duration else None,
                'base_fare': float(route.base_fare) if route.base_fare else None,
                'schedule_id': route.schedules.first().id if route.schedules.exists() else None,
                'waypoints': route.waypoints or [
                    [route.departure_lat, route.departure_lng],
                    [route.destination_lat, route.destination_lng]
                ]
            }
            for route in routes
        ]
        return JsonResponse({'routes': routes_data})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def homepage(request):
    now = timezone.now()
    schedules = Schedule.objects.filter(
        status='scheduled',
        departure_time__gt=now
    ).select_related('ferry', 'route', 'route__departure_port', 'route__destination_port').order_by('departure_time')

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
            travel_date_obj = datetime.strptime(travel_date, '%Y-%m-%d')
            travel_date_start = timezone.make_aware(travel_date_obj)
            travel_date_end = travel_date_start + timezone.timedelta(days=1)
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
            'schedule_id': next_departure.id
        }

    # Fetch weather data for scheduled routes
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
    logger.debug(f"Messages: {list(messages.get_messages(request))}")

    if request.method == 'POST':
        guest_email = request.POST.get('guest_email', '').strip()
        if guest_email:
            request.session['guest_email'] = guest_email
            logger.debug(f"Set guest_email in session: {guest_email}")

    if request.user.is_authenticated:
        bookings = Booking.objects.filter(user=request.user).select_related('schedule__ferry',
                                                                          'schedule__route').order_by('-booking_date')
    else:
        guest_email = request.session.get('guest_email')
        bookings = Booking.objects.filter(guest_email=guest_email).select_related('schedule__ferry',
                                                                                'schedule__route').order_by(
            '-booking_date') if guest_email else []

    logger.debug(f"Found {bookings.count()} bookings: {[b.id for b in bookings]}")

    for booking in bookings:
        booking.update_status_if_expired()

    return render(request, 'bookings/history.html', {
        'bookings': bookings,
        'cutoff_time': timezone.now() + timezone.timedelta(hours=6),
        'is_guest': not request.user.is_authenticated
    })


@login_required
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
                ticket_status='active'
            )
            qr_data = request.build_absolute_uri(reverse('bookings:view_ticket', args=[ticket.qr_token]))
            qr = qrcode.make(qr_data)
            buffer = BytesIO()
            qr.save(buffer, format='PNG')
            ticket.qr_code.save(f"ticket_{ticket.id}.png", ContentFile(buffer.getvalue()))

    messages.success(request, f"Tickets generated for Booking #{booking.id}.")
    return redirect('bookings:view_tickets', booking_id=booking.id)


@login_required
def view_cargo(request, qr_data):
    parts = dict(x.split(':') for x in qr_data.split('|'))
    cargo_id = parts.get('CargoID')
    if not cargo_id:
        messages.error(request, "Invalid cargo QR code.")
        return redirect('bookings:booking_history')
    cargo = get_object_or_404(Cargo, id=cargo_id, booking__user=request.user)
    return render(request, 'bookings/view_cargo.html', {'cargo': cargo})


@login_required_allow_anonymous
def view_ticket(request, qr_token):
    try:
        ticket = Ticket.objects.select_related('booking', 'passenger', 'booking__schedule__ferry',
                                               'booking__schedule__route').get(qr_token=qr_token)
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
    ).select_related('ferry', 'route').order_by('departure_time')
    data = {
        'schedules': [
            {
                'id': s.id,
                'route_id': s.route.id,
                'departure_time': s.departure_time.isoformat(),
                'status': s.status,
                'available_seats': s.available_seats,
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
        if not schedule_id:
            return JsonResponse({'error': 'Schedule ID is required.'}, status=400)

        adults = safe_int(request.POST.get('adults'))
        youths = safe_int(request.POST.get('youths'))
        children = safe_int(request.POST.get('children'))
        infants = safe_int(request.POST.get('infants'))
        add_cargo = request.POST.get('add_cargo') == 'true'
        cargo_type = request.POST.get('cargo_type', '')
        weight_kg = safe_float(request.POST.get('weight_kg', '0'))
        is_emergency = request.POST.get('is_emergency') == 'true'

        if any(n < 0 for n in [adults, youths, children, infants, weight_kg]):
            return JsonResponse({'error': 'Passenger counts and weight cannot be negative.'}, status=400)

        if add_cargo and not cargo_type:
            return JsonResponse({'error': 'Cargo type is required when adding cargo.'}, status=400)

        schedule = get_object_or_404(Schedule, id=schedule_id)

        total_price = calculate_total_price(
            adults, youths, children, infants, schedule, add_cargo, cargo_type, weight_kg, is_emergency
        )

        breakdown = {
            'adults': str(Decimal(adults) * (schedule.route.base_fare or Decimal('35.50'))),
            'youths': str(Decimal(youths) * (schedule.route.base_fare or Decimal('35.50')) * Decimal('0.75')),
            'children': str(Decimal(children) * (schedule.route.base_fare or Decimal('35.50')) * Decimal('0.5')),
            'infants': str(Decimal(infants) * (schedule.route.base_fare or Decimal('35.50')) * Decimal('0.1')),
            'cargo': str(calculate_cargo_price(Decimal(weight_kg), cargo_type) if add_cargo else Decimal('0.00')),
            'emergency_surcharge': str(Decimal('50.00') if is_emergency else Decimal('0.00'))
        }

        logger.debug(f"Pricing calculated: schedule_id={schedule_id}, total_price={total_price}, breakdown={breakdown}")

        return JsonResponse({'total_price': str(total_price), 'breakdown': breakdown})

    except Exception as e:
        logger.exception(f"Pricing error: {e}")
        return JsonResponse({'error': f"An error occurred: {str(e)}"}, status=400)



def generate_manifest(booking, passengers):
    manifest = {
        'booking_id': booking.id,
        'schedule': {
            'ferry': booking.schedule.ferry.name,
            'route': f"{booking.schedule.route.departure_port} → {booking.schedule.route.destination_port}",
            'departure_time': booking.schedule.departure_time.isoformat(),
        },
        'passengers': [],
        'group_leader': None,
        'total_passengers': booking.number_of_passengers,
        'is_emergency': booking.is_emergency,
        'is_unaccompanied_minor': booking.is_unaccompanied_minor,
        'cargo': None,
        'consent_form': booking.consent_form.url if booking.consent_form else None,
        'responsibility_declaration': booking.responsibility_declaration.url if booking.responsibility_declaration else None
    }

    for passenger in passengers:
        passenger_data = {
            'type': passenger.passenger_type,
            'first_name': passenger.first_name,
            'last_name': passenger.last_name,
            'age': passenger.age,
            'is_group_leader': passenger.is_group_leader,
            'document_status': passenger.verification_status,
            'document': passenger.document.url if passenger.document else None,
            'verification_id': passenger.documentverification_set.first().id if passenger.documentverification_set.exists() else None
        }
        manifest['passengers'].append(passenger_data)
        if passenger.is_group_leader:
            manifest['group_leader'] = f"{passenger.first_name} {passenger.last_name}"

    if hasattr(booking, 'cargo'):
        cargo = booking.cargo
        manifest['cargo'] = {
            'type': cargo.cargo_type,
            'weight_kg': str(cargo.weight_kg),
            'dimensions_cm': cargo.dimensions_cm,
            'price': str(cargo.price),
        }

    return manifest

@require_POST
def validate_step(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'errors': [{'field': 'general', 'message': 'Invalid request method'}], 'step': 1})

    step = request.POST.get('step')
    errors = []

    if step == '1':
        schedule_id = request.POST.get('schedule_id', '').strip()
        guest_email = request.POST.get('guest_email', '').strip()
        is_authenticated = request.user.is_authenticated

        cache_key = f'schedule_exists_{schedule_id}'
        schedule_exists = cache.get(cache_key)
        if schedule_exists is None:
            schedule_exists = Schedule.objects.filter(id=schedule_id, status='scheduled', departure_time__gt=timezone.now()).exists()
            cache.set(cache_key, schedule_exists, timeout=3600)

        if not schedule_id or not schedule_exists:
            errors.append({'field': 'schedule_id', 'message': 'Please select a valid ferry schedule.'})

        if not is_authenticated and not guest_email:
            errors.append({'field': 'guest_email', 'message': 'Guest email is required.'})

    elif step == '2':
        adults = safe_int(request.POST.get('adults', '0'))
        youths = safe_int(request.POST.get('youths', '0'))
        children = safe_int(request.POST.get('children', '0'))
        infants = safe_int(request.POST.get('infants', '0'))

        total_passengers = adults + youths + children + infants
        if total_passengers == 0:
            errors.append({'field': 'general', 'message': 'At least one passenger is required.'})
        if (infants > 0 or children > 0 or youths > 0) and adults == 0:
            errors.append({'field': 'general', 'message': 'Minors must be accompanied by an adult.'})

        for field, value in [('adults', adults), ('youths', youths), ('children', children), ('infants', infants)]:
            if value < 0:
                errors.append({'field': field, 'message': f'{field.capitalize()} count cannot be negative.'})

        for type in ['adult', 'youth', 'child', 'infant']:
            count = (
                adults if type == 'adult' else
                youths if type == 'youth' else
                children if type == 'child' else
                infants
            )
            for i in range(count):
                first_name = request.POST.get(f'{type}_first_name_{i}', '').strip()
                last_name = request.POST.get(f'{type}_last_name_{i}', '').strip()
                age = request.POST.get(f'{type}_age_{i}', '').strip()
                is_group_leader = request.POST.get(f'{type}_is_group_leader_{i}') == 'true'

                if not first_name:
                    errors.append({'field': f'{type}_first_name_{i}', 'message': f'{type.capitalize()} {i + 1}: First name is required.'})
                if not last_name:
                    errors.append({'field': f'{type}_last_name_{i}', 'message': f'{type.capitalize()} {i + 1}: Last name is required.'})
                try:
                    age = int(age)
                    if type == 'infant' and not (0 <= age <= 2):
                        errors.append({'field': f'{type}_age_{i}', 'message': f'Infant {i + 1}: Age must be 0-2.'})
                    elif type == 'child' and not (2 <= age <= 11):
                        errors.append({'field': f'{type}_age_{i}', 'message': f'Child {i + 1}: Age must be 2-11.'})
                    elif type == 'youth' and not (12 <= age <= 17):
                        errors.append({'field': f'{type}_is_group_leader_{i}', 'message': f'Youth {i + 1}: Youth cannot be group leader.'})
                    elif type == 'adult' and age < 18:
                        errors.append({'field': f'{type}_age_{i}', 'message': f'Adult {i + 1}: Age must be 18 or older.'})
                except (ValueError, TypeError):
                    errors.append({'field': f'{type}_age_{i}', 'message': f'{type.capitalize()} {i + 1}: Invalid age.'})

        has_minors = children > 0 or infants > 0 or youths > 0
        has_parent = any(
            request.POST.get(f'{type}_is_parent_guardian_{i}') == 'true'
            for type in ['adult', 'youth']
            for i in range(adults if type == 'adult' else youths)
        )
        responsibility_declaration = request.FILES.get('responsibility_declaration')
        if has_minors and adults > 0 and not has_parent and not responsibility_declaration:
            errors.append({'field': 'responsibility_declaration', 'message': 'Responsibility declaration is required if no adult is a parent.'})

    elif step == '3':
        is_unaccompanied_minor = request.POST.get('is_unaccompanied_minor') == 'true'
        has_minors = safe_int(request.POST.get('children', 0)) > 0 or safe_int(request.POST.get('infants', 0)) > 0 or safe_int(request.POST.get('youths', 0)) > 0
        if is_unaccompanied_minor and has_minors:
            if not request.POST.get('guardian_contact', '').strip():
                errors.append({'field': 'guardian_contact', 'message': 'Guardian contact is required for unaccompanied minors.'})
            if not request.FILES.get('consent_form'):
                errors.append({'field': 'consent_form', 'message': 'Consent form is required for unaccompanied minors.'})
        if request.POST.get('add_cargo') == 'true':
            if not request.POST.get('cargo_type', '').strip():
                errors.append({'field': 'cargo_type', 'message': 'Cargo type is required.'})
            try:
                weight = float(request.POST.get('weight_kg', 0))
                if weight <= 0:
                    errors.append({'field': 'weight_kg', 'message': 'Cargo weight must be a positive number.'})
            except ValueError:
                errors.append({'field': 'weight_kg', 'message': 'Cargo weight must be a valid number.'})

    elif step == '4':
        if request.POST.get('privacy_consent') != 'true':
            errors.append({'field': 'privacy_consent', 'message': 'You must agree to the privacy policy.'})

    if errors:
        return JsonResponse({'success': False, 'errors': errors, 'step': step})
    return JsonResponse({'success': True, 'step': step})


@csrf_exempt
def validate_file(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid request method.'}, status=405)

    file = request.FILES.get('file')
    if not file:
        logger.error('No file provided for validation')
        return JsonResponse({'error': 'No file provided.'}, status=400)

    file_validator = FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])

    try:
        # Validate file extension
        file_validator(file)

        # Validate file size
        if file.size > 5 * 1024 * 1024:
            return JsonResponse({'error': 'File size must be less than 5MB.'}, status=400)

        # Ensure temp directory exists
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads')
        os.makedirs(temp_dir, exist_ok=True)

        # Sanitize filename
        import re
        safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', file.name)

        # Save file
        file_id = str(uuid.uuid4())
        file_path = os.path.join(temp_dir, f'{file_id}_{safe_name}')
        with open(file_path, 'wb+') as dest:
            for chunk in file.chunks():
                dest.write(chunk)

        temp_url = f'/media/temp_uploads/{file_id}_{safe_name}'
        return JsonResponse({'success': True, 'file_id': file_id, 'temp_url': temp_url})

    except ValidationError as e:
        return JsonResponse({'error': 'File must be PDF, JPG, JPEG, or PNG.'}, status=400)
    except Exception as e:
        import traceback
        logger.error(f'File upload error: {traceback.format_exc()}')
        return JsonResponse({'error': 'Unexpected server error. Please try again.'}, status=500)



@require_POST
def create_checkout_session(request):
    try:
        # Retrieve POST data
        schedule_id = request.POST.get('schedule_id')
        total_price = request.POST.get('total_price')
        adults = safe_int(request.POST.get('adults', '0'))
        youths = safe_int(request.POST.get('youths', '0'))
        children = safe_int(request.POST.get('children', '0'))
        infants = safe_int(request.POST.get('infants', '0'))
        add_cargo = request.POST.get('add_cargo') == 'true'
        cargo_type = request.POST.get('cargo_type', '')
        weight_kg = request.POST.get('weight_kg', '0')
        is_emergency = request.POST.get('is_emergency', '').lower() in ('true', '1', 'on')
        guest_email = request.POST.get('guest_email', '')

        # Log incoming data for debugging
        logger.debug(f"create_checkout_session POST data: {dict(request.POST)}, is_emergency={is_emergency}")

        # Validate inputs
        if not schedule_id:
            logger.error("Missing schedule_id")
            return JsonResponse({'errors': [{'field': 'schedule_id', 'message': 'Schedule ID is required.'}]}, status=400)

        # Validate passenger counts
        total_passengers = adults + youths + children + infants
        if total_passengers <= 0:
            logger.error("No passengers specified")
            return JsonResponse({'errors': [{'field': 'passengers', 'message': 'At least one passenger is required.'}]}, status=400)

        # Validate cargo if present
        if add_cargo:
            if not cargo_type or not weight_kg:
                logger.error(f"Missing cargo details: cargo_type={cargo_type}, weight_kg={weight_kg}")
                return JsonResponse({'errors': [{'field': 'cargo', 'message': 'Cargo type and weight are required when adding cargo.'}]}, status=400)
            try:
                weight_kg = float(weight_kg)
                if weight_kg <= 0:
                    logger.error(f"Invalid cargo weight: {weight_kg}")
                    return JsonResponse({'errors': [{'field': 'weight_kg', 'message': 'Cargo weight must be greater than zero.'}]}, status=400)
            except ValueError:
                logger.error(f"Invalid cargo weight format: {weight_kg}")
                return JsonResponse({'errors': [{'field': 'weight_kg', 'message': 'Cargo weight must be a valid number.'}]}, status=400)

        # Validate passenger details
        errors = []
        for p_type in ['adult', 'youth', 'child', 'infant']:
            count = safe_int(request.POST.get(f'{p_type}s', '0'))
            for i in range(count):
                first_name = request.POST.get(f'{p_type}_first_name_{i}', '').strip()
                last_name = request.POST.get(f'{p_type}_last_name_{i}', '').strip()
                age = request.POST.get(f'{p_type}_age_{i}', '').strip()
                if not first_name:
                    errors.append({'field': f'{p_type}_first_name_{i}', 'message': f'{p_type.capitalize()} {i + 1}: First name is required.'})
                if not last_name:
                    errors.append({'field': f'{p_type}_last_name_{i}', 'message': f'{p_type.capitalize()} {i + 1}: Last name is required.'})
                try:
                    age = int(age)
                    if p_type == 'infant' and not (0 <= age <= 2):
                        errors.append({'field': f'{p_type}_age_{i}', 'message': f'Infant {i + 1}: Age must be 0-2.'})
                    elif p_type == 'child' and not (2 <= age <= 11):
                        errors.append({'field': f'{p_type}_age_{i}', 'message': f'Child {i + 1}: Age must be 2-11.'})
                    elif p_type == 'youth' and not (12 <= age <= 17):
                        errors.append({'field': f'{p_type}_age_{i}', 'message': f'Youth {i + 1}: Age must be 12-17.'})
                    elif p_type == 'adult' and age < 18:
                        errors.append({'field': f'{p_type}_age_{i}', 'message': f'Adult {i + 1}: Age must be 18 or older.'})
                except (ValueError, TypeError):
                    errors.append({'field': f'{p_type}_age_{i}', 'message': f'{p_type.capitalize()} {i + 1}: Invalid age.'})

        if errors:
            logger.error(f"Passenger validation errors: {errors}")
            return JsonResponse({'success': False, 'errors': errors}, status=400)

        # Verify schedule exists and has enough seats
        try:
            schedule = Schedule.objects.select_related('route', 'route__departure_port', 'route__destination_port').get(id=schedule_id)
            if schedule.available_seats < total_passengers:
                logger.error(f"Not enough seats: schedule_id={schedule_id}, available_seats={schedule.available_seats}, requested={total_passengers}")
                return JsonResponse({'errors': [{'field': 'schedule_id', 'message': 'Not enough seats available for this schedule.'}]}, status=400)
            if schedule.status != 'scheduled' or schedule.departure_time <= timezone.now():
                logger.error(f"Invalid schedule status or time: schedule_id={schedule_id}, status={schedule.status}")
                return JsonResponse({'errors': [{'field': 'schedule_id', 'message': 'Selected schedule is not available.'}]}, status=400)
        except Schedule.DoesNotExist:
            logger.error(f"Schedule not found: schedule_id={schedule_id}")
            return JsonResponse({'errors': [{'field': 'schedule_id', 'message': 'Invalid schedule ID.'}]}, status=400)

        # Get booking_id from session
        booking_id = request.session.get('booking_id')
        if not booking_id:
            logger.error("No booking_id in session")
            return JsonResponse({'errors': [{'field': 'general', 'message': 'No booking found. Please start over.'}]}, status=400)

        try:
            booking = Booking.objects.get(id=booking_id)
        except Booking.DoesNotExist:
            logger.error(f"Booking {booking_id} not found")
            return JsonResponse({'errors': [{'field': 'general', 'message': 'Booking not found.'}]}, status=404)

        # Authorization check
        if request.user.is_authenticated and booking.user != request.user:
            logger.error(f"User {request.user} not authorized for booking {booking_id}")
            return JsonResponse({'errors': [{'field': 'general', 'message': 'Unauthorized'}]}, status=403)
        if not request.user.is_authenticated and booking.guest_email != guest_email:
            logger.error(f"Guest email mismatch for booking {booking_id}, expected={booking.guest_email}, got={guest_email}")
            return JsonResponse({'errors': [{'field': 'guest_email', 'message': 'Unauthorized'}]}, status=403)

        # Check for existing checkout session to prevent duplicates
        lock_key = f"checkout_lock_{booking_id}"
        if cache.get(lock_key):
            logger.warning(f"Checkout session already in progress for booking {booking_id}")
            return JsonResponse({'errors': [{'field': 'general', 'message': 'A checkout session is already in progress. Please wait.'}]}, status=429)
        cache.set(lock_key, True, timeout=300)  # Lock for 5 minutes

        # Recalculate total price to ensure consistency
        try:
            calculated_price = calculate_total_price(
                adults, youths, children, infants, schedule, add_cargo, cargo_type, weight_kg, is_emergency
            )
            price_breakdown = {
                'adults': str(Decimal(adults) * (schedule.route.base_fare or Decimal('35.50'))),
                'youths': str(Decimal(youths) * (schedule.route.base_fare or Decimal('35.50')) * Decimal('0.75')),
                'children': str(Decimal(children) * (schedule.route.base_fare or Decimal('35.50')) * Decimal('0.5')),
                'infants': str(Decimal(infants) * (schedule.route.base_fare or Decimal('35.50')) * Decimal('0.1')),
                'cargo': str(calculate_cargo_price(Decimal(weight_kg), cargo_type) if add_cargo else Decimal('0.00')),
                'emergency_surcharge': str(Decimal('50.00') if is_emergency else Decimal('0.00'))
            }
            logger.debug(f"Calculated price: {calculated_price}, breakdown={price_breakdown}, inputs: adults={adults}, youths={youths}, children={children}, infants={infants}, add_cargo={add_cargo}, cargo_type={cargo_type}, weight_kg={weight_kg}, is_emergency={is_emergency}")

            if not total_price:
                logger.warning("No total_price provided, using calculated price")
                total_price = calculated_price
            else:
                total_price = Decimal(total_price)
                if abs(total_price - calculated_price) > Decimal('0.01'):
                    logger.error(f"Price mismatch: provided={total_price}, calculated={calculated_price}, breakdown={price_breakdown}")
                    cache.delete(lock_key)  # Release lock on error
                    return JsonResponse({
                        'errors': [{
                            'field': 'total_price',
                            'message': f'Provided total price ({total_price}) does not match calculated price ({calculated_price}). Breakdown: {price_breakdown}'
                        }]
                    }, status=400)
            if total_price <= 0:
                logger.error(f"Invalid total_price: {total_price}")
                cache.delete(lock_key)  # Release lock on error
                return JsonResponse({'errors': [{'field': 'total_price', 'message': 'Total price must be greater than zero.'}]}, status=400)
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid total_price format: {total_price}, error: {str(e)}")
            cache.delete(lock_key)  # Release lock on error
            return JsonResponse({'errors': [{'field': 'total_price', 'message': 'Total price must be a valid number.'}]}, status=400)

        # Create Stripe checkout session
        try:
            amount_cents = int(total_price * 100)
            if amount_cents <= 0:
                logger.error(f"Invalid amount_cents: {amount_cents}")
                cache.delete(lock_key)  # Release lock on error
                return JsonResponse({'errors': [{'field': 'total_price', 'message': 'Payment amount must be positive.'}]}, status=400)

            customer_email = booking.user.email if booking.user else guest_email
            if not customer_email:
                logger.error("No valid email for payment")
                cache.delete(lock_key)  # Release lock on error
                return JsonResponse({'errors': [{'field': 'guest_email', 'message': 'A valid email is required for payment.'}]}, status=400)

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
                metadata={'booking_id': str(booking.id), 'guest_email': guest_email or ''},
                customer_email=customer_email,
            )

            # Update booking with session ID
            booking.stripe_session_id = session.id
            booking.total_price = total_price  # Ensure booking reflects the validated price
            booking.save()

            # Create or update Payment object
            payment, created = Payment.objects.get_or_create(
                booking=booking,
                session_id=session.id,
                defaults={
                    'payment_method': 'stripe',
                    'amount': total_price,
                    'payment_status': 'pending'
                }
            )
            if not created:
                payment.amount = total_price
                payment.payment_status = 'pending'
                payment.save()

            # Store session data
            request.session['stripe_session_id'] = session.id
            logger.info(f"Stripe session created for booking {booking_id}: session_id={session.id}")

            cache.delete(lock_key)  # Release lock on success
            return JsonResponse({'sessionId': session.id})

        except stripe.error.StripeError as e:
            logger.error(f"Stripe error for booking {booking_id}: {str(e)}")
            cache.delete(lock_key)  # Release lock on error
            return JsonResponse({'errors': [{'field': 'general', 'message': f"Payment processing error: {str(e)}"}]}, status=400)
        except Exception as e:
            logger.exception(f"Unexpected error creating checkout session for booking {booking_id}: {str(e)}")
            cache.delete(lock_key)  # Release lock on error
            return JsonResponse({'errors': [{'field': 'general', 'message': 'An unexpected error occurred. Please contact support.'}]}, status=500)

    except Exception as e:
        logger.exception(f"Checkout session error: {e}")
        cache.delete(lock_key)  # Release lock on error
        return JsonResponse({'errors': [{'field': 'general', 'message': f"An error occurred: {str(e)}"}]}, status=400)

@login_required_allow_anonymous
def book_ticket(request):
    # Handle query parameters
    schedule_id = request.GET.get('schedule_id', '').strip()
    to_port = request.GET.get('to_port', '').strip().lower()

    # Filter schedules based on query parameters
    available_schedules = Schedule.objects.filter(
        status='scheduled',
        departure_time__gt=timezone.now()
    ).select_related('ferry', 'route', 'route__departure_port', 'route__destination_port')

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

    if request.method == 'POST':
        logger.debug(f'POST data: {request.POST}')
        logger.debug(f'FILES data: {request.FILES}')
        errors = []

        # Parse and validate passenger counts
        adults = safe_int(request.POST.get('adults', '0'))
        youths = safe_int(request.POST.get('youths', '0'))
        children = safe_int(request.POST.get('children', '0'))
        infants = safe_int(request.POST.get('infants', '0'))

        if adults < 0 or youths < 0 or children < 0 or infants < 0:
            errors.append({'field': 'general', 'message': 'Passenger counts cannot be negative.', 'step': 2})

        total_passengers = adults + youths + children + infants
        if total_passengers == 0:
            errors.append({'field': 'general', 'message': 'At least one passenger is required.', 'step': 2})

        if (youths > 0 or children > 0 or infants > 0) and adults == 0:
            errors.append({'field': 'general', 'message': 'Minors must be accompanied by an adult.', 'step': 2})

        schedule_id = request.POST.get('schedule_id')
        guest_email = request.POST.get('guest_email')
        is_unaccompanied_minor = request.POST.get('is_unaccompanied_minor') == 'true'
        guardian_contact = request.POST.get('guardian_contact')
        consent_form = request.FILES.get('consent_form')
        is_group_booking = request.POST.get('is_group_booking') == 'true'
        add_cargo = request.POST.get('add_cargo') == 'true'
        cargo_type = request.POST.get('cargo_type')
        weight_kg = request.POST.get('weight_kg')
        dimensions_cm = request.POST.get('dimensions_cm')
        is_emergency = request.POST.get('is_emergency') == 'true'
        privacy_consent = request.POST.get('privacy_consent') == 'true'
        responsibility_declaration = request.FILES.get('responsibility_declaration')

        # Validate files
        file_validator = FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])
        if consent_form:
            try:
                file_validator(consent_form)
            except ValidationError as e:
                errors.append({'field': 'consent_form', 'message': 'Consent form must be a PDF, JPG, JPEG, or PNG file.', 'step': 3})
        if responsibility_declaration:
            try:
                file_validator(responsibility_declaration)
            except ValidationError as e:
                errors.append({'field': 'responsibility_declaration', 'message': 'Responsibility declaration must be a PDF, JPG, JPEG, or PNG file.', 'step': 2})

        # Form data for passenger details
        form_data = {
            'schedule_id': schedule_id,
            'adults': adults,
            'youths': youths,
            'children': children,
            'infants': infants,
            'guest_email': guest_email,
            'is_unaccompanied_minor': is_unaccompanied_minor,
            'guardian_contact': guardian_contact,
            'is_group_booking': is_group_booking,
            'add_cargo': add_cargo,
            'cargo_type': cargo_type,
            'weight_kg': weight_kg,
            'dimensions_cm': dimensions_cm,
            'is_emergency': is_emergency,
            'privacy_consent': privacy_consent,
        }

        # Validate passenger details
        passenger_types = [('adult', adults), ('youth', youths), ('child', children), ('infant', infants)]
        for p_type, count in passenger_types:
            for i in range(count):
                first_name = request.POST.get(f'{p_type}_first_name_{i}', '').strip()
                last_name = request.POST.get(f'{p_type}_last_name_{i}', '').strip()
                age = request.POST.get(f'{p_type}_age_{i}', '').strip()
                is_group_leader = request.POST.get(f'{p_type}_is_group_leader_{i}') == 'true'
                is_parent_guardian = request.POST.get(f'{p_type}_is_parent_guardian_{i}') == 'true'
                document = request.FILES.get(f'{p_type}_document_{i}')

                form_data[f'passenger_{p_type}_{i}_first_name'] = first_name
                form_data[f'passenger_{p_type}_{i}_last_name'] = last_name
                form_data[f'passenger_{p_type}_{i}_age'] = age
                form_data[f'passenger_{p_type}_{i}_is_group_leader'] = is_group_leader
                form_data[f'passenger_{p_type}_{i}is_parent_guardian'] = is_parent_guardian
                form_data[f'passenger_{p_type}_{i}_document'] = document

                if not first_name:
                    errors.append({'field': f'{p_type}_first_name_{i}', 'message': f'{p_type.capitalize()} {i + 1}: First name is required.', 'step': 2})
                if not last_name:
                    errors.append({'field': f'{p_type}_last_name_{i}', 'message': f'{p_type.capitalize()} {i + 1}: Last name is required.', 'step': 2})
                try:
                    age = int(age)
                    if p_type == 'infant' and not (0 <= age <= 2):
                        errors.append({'field': f'{p_type}_age_{i}', 'message': f'Infant {i + 1}: Age must be 0-2.', 'step': 2})
                    elif p_type == 'child' and not (2 <= age <= 11):
                        errors.append({'field': f'{p_type}_age_{i}', 'message': f'Child {i + 1}: Age must be 2-11.', 'step': 2})
                    elif p_type == 'youth' and not (12 <= age <= 17):
                        errors.append({'field': f'{p_type}_age_{i}', 'message': f'Youth {i + 1}: Age must be 12-17.', 'step': 2})
                    elif p_type == 'adult' and age < 18:
                        errors.append({'field': f'{p_type}_age_{i}', 'message': f'Adult {i + 1}: Age must be 18 or older.', 'step': 2})
                    if p_type == 'youth' and is_group_leader:
                        errors.append({'field': f'{p_type}_is_group_leader_{i}', 'message': f'Youth {i + 1}: Youth cannot be group leader.', 'step': 2})
                except (ValueError, TypeError):
                    errors.append({'field': f'{p_type}_age_{i}', 'message': f'{p_type.capitalize()} {i + 1}: Invalid age.', 'step': 2})

                if document:
                    try:
                        file_validator(document)
                    except ValidationError as e:
                        errors.append({'field': f'{p_type}_document_{i}', 'message': f'Document for {p_type.capitalize()} {i + 1} must be a PDF, JPG, JPEG, or PNG file.', 'step': 2})

        # Other validations
        if not schedule_id:
            errors.append({'field': 'schedule_id', 'message': 'Please select a valid ferry schedule.', 'step': 1})

        if not request.user.is_authenticated and not guest_email:
            errors.append({'field': 'guest_email', 'message': 'Guest email is required.', 'step': 1})

        has_minors = youths > 0 or children > 0 or infants > 0
        has_parent = any(form_data.get(f'passenger_{t}_{i}is_parent_guardian') for t in ['adult', 'youth'] for i in range(adults if t == 'adult' else youths))
        if has_minors and adults > 0 and not has_parent and not responsibility_declaration:
            errors.append({'field': 'responsibility_declaration', 'message': 'Responsibility declaration is required if no adult is a parent.', 'step': 2})

        if is_unaccompanied_minor and has_minors:
            if not guardian_contact:
                errors.append({'field': 'guardian_contact', 'message': 'Guardian contact is required for unaccompanied minors.', 'step': 3})
            if not consent_form:
                errors.append({'field': 'consent_form', 'message': 'Consent form is required for unaccompanied minors.', 'step': 3})

        if add_cargo and not cargo_type:
            errors.append({'field': 'cargo_type', 'message': 'Cargo type is required.', 'step': 3})
        if add_cargo and weight_kg:
            try:
                weight_kg = float(weight_kg)
                if weight_kg <= 0:
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

        # Calculate total price
        total_price = calculate_total_price(
            adults, youths, children, infants, schedule,
            add_cargo, cargo_type, float(weight_kg) if weight_kg else 0, is_emergency
        )

        # Create booking, mapping youths to passenger_children
        booking_kwargs = {
            'user': request.user if request.user.is_authenticated else None,
            'schedule': schedule,
            'guest_email': guest_email if not request.user.is_authenticated else None,
            'passenger_adults': adults,
            'passenger_children': youths + children,  # Combine youths and children
            'passenger_infants': infants,
            'number_of_passengers': total_passengers,
            'total_price': total_price,
            'is_unaccompanied_minor': is_unaccompanied_minor,
            'guardian_contact': guardian_contact,
            'consent_form': consent_form,
            'is_group_booking': is_group_booking,
            'is_emergency': is_emergency,
            'status': 'pending'
        }
        if responsibility_declaration:
            booking_kwargs['responsibility_declaration'] = responsibility_declaration

        try:
            booking = Booking.objects.create(**booking_kwargs)
        except Exception as e:
            logger.error(f"Booking creation error: {str(e)}")
            errors.append({'field': 'general', 'message': 'Failed to create booking due to invalid data.', 'step': 4})
            return JsonResponse({'success': False, 'errors': errors})

        # Create passengers
        group_leader = None
        passengers = []
        for p_type, count in passenger_types:
            # Map youth to child in Passenger model
            db_type = 'child' if p_type == 'youth' else p_type
            for i in range(count):
                first_name = form_data[f'passenger_{p_type}_{i}_first_name']
                last_name = form_data[f'passenger_{p_type}_{i}_last_name']
                age = int(form_data[f'passenger_{p_type}_{i}_age'])
                is_group_leader_flag = form_data[f'passenger_{p_type}_{i}_is_group_leader']
                is_parent_guardian = form_data[f'passenger_{p_type}_{i}is_parent_guardian']
                document = form_data[f'passenger_{p_type}_{i}_document']
                verification_status = 'pending' if document else 'missing'

                passenger = Passenger.objects.create(
                    booking=booking,
                    first_name=first_name,
                    last_name=last_name,
                    age=age,
                    passenger_type=db_type,
                    document=document,
                    verification_status=verification_status,
                    is_group_leader=is_group_leader_flag,
                    is_parent_guardian=is_parent_guardian
                )
                if is_group_booking and is_group_leader_flag:
                    group_leader = passenger
                if document:
                    DocumentVerification.objects.create(
                        passenger=passenger,
                        document=document,
                        verification_status='pending',
                        expires_at=schedule.departure_time + timezone.timedelta(days=1) if not request.user.is_authenticated else None
                    )
                passengers.append(passenger)

        if group_leader:
            booking.group_leader = group_leader
            booking.save()

        if is_group_booking:
            manifest = generate_manifest(booking, passengers)
            request.session['manifest'] = manifest
            logger.info(f"Group booking manifest generated: Booking #{booking.id}")

        # Create cargo
        if add_cargo and cargo_type and weight_kg:
            try:
                weight_kg = float(weight_kg)
                if weight_kg <= 0:
                    errors.append({'field': 'weight_kg', 'message': 'Cargo weight must be greater than zero.', 'step': 3})
                    return JsonResponse({'success': False, 'errors': errors})
                cargo = Cargo.objects.create(
                    booking=booking,
                    cargo_type=cargo_type,
                    weight_kg=Decimal(weight_kg),
                    dimensions_cm=dimensions_cm or '',
                    price=calculate_cargo_price(Decimal(weight_kg), cargo_type)
                )
                generate_cargo_qr(request, cargo)
            except ValueError:
                errors.append({'field': 'weight_kg', 'message': 'Cargo weight must be a valid number.', 'step': 3})
                return JsonResponse({'success': False, 'errors': errors})

        # Handle emergency and unaccompanied minor notifications
        if is_emergency:
            booking.notes = "Emergency booking: Verify child/infant/youth documents on-site if missing."
            booking.save()
            send_mail(
                'Emergency Booking Notification',
                f'Emergency Booking #{booking.id} created. Please prioritize processing and verify documents on-site if missing.',
                settings.DEFAULT_FROM_EMAIL,
                [settings.ADMIN_EMAIL],
                fail_silently=True
            )

        if is_unaccompanied_minor:
            send_mail(
                'Unaccompanied Minor Notification',
                f'Booking #{booking.id} includes unaccompanied minors. Guardian contact: {guardian_contact}. Please ensure staff supervision.',
                settings.DEFAULT_FROM_EMAIL,
                [settings.ADMIN_EMAIL],
                fail_silently=True
            )

        # Update schedule seats
        schedule.available_seats -= total_passengers
        schedule.save()

        if is_group_booking:
            logger.info(f"Group booking created: Booking #{booking.id}, Passengers: {total_passengers}")

        # Store booking_id and guest_email in session
        request.session['booking_id'] = booking.id
        if not request.user.is_authenticated and guest_email:
            request.session['guest_email'] = guest_email

        return JsonResponse({
            'success': True,
            'booking_id': booking.id  # Include booking_id for client-side use
        })

    # GET request
    form_data = {
        'step': 1,
        'schedule_id': schedule_id or '',
        'adults': 0,
        'youths': 0,
        'children': 0,
        'infants': 0,
        'guest_email': request.session.get('guest_email', ''),
        'is_unaccompanied_minor': False,
        'guardian_contact': '',
        'is_group_booking': False,
        'add_cargo': False,
        'cargo_type': '',
        'weight_kg': '',
        'dimensions_cm': '',
        'is_emergency': False,
        'privacy_consent': False,
        'to_port': to_port or ''  # Include to_port in form_data
    }
    return render(request, 'bookings/book.html', {
        'schedules': available_schedules,
        'user': request.user,
        'form_data': form_data,
        'debug': settings.DEBUG,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY
    })


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

    # Calculate amount to charge for pending payments
    amount_to_charge = booking.total_price
    if booking.status == 'pending' and 'price_difference' in request.session:
        amount_to_charge = Decimal(str(request.session.get('price_difference', booking.total_price)))

    # Calculate passenger breakdown
    youths = sum(1 for p in booking.passengers.all() if p.passenger_type == 'child' and 12 <= p.age <= 17)
    children = booking.passenger_children - youths
    passenger_price = calculate_passenger_price(
        booking.passenger_adults, youths, children, booking.passenger_infants, booking.schedule
    )

    return render(request, 'bookings/ticket.html', {
        'booking': booking,
        'tickets': tickets,
        'cargo': cargo,
        'amount_to_charge': amount_to_charge,
        'price_adults': booking.passenger_adults * (booking.schedule.route.base_fare or Decimal('35.50')),
        'price_youths': youths * (booking.schedule.route.base_fare or Decimal('35.50')) * Decimal('0.75'),
        'price_children': children * (booking.schedule.route.base_fare or Decimal('35.50')) * Decimal('0.5'),
        'price_infants': booking.passenger_infants * (booking.schedule.route.base_fare or Decimal('35.50')) * Decimal('0.1'),
        'cargo_price': cargo.price if cargo else Decimal('0.00'),
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY
    })

@login_required
def process_payment(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    # Authorization checks
    if booking.user and booking.user != request.user:
        logger.error(f"Authorization failed: User {request.user} not authorized for booking {booking_id}")
        return HttpResponseForbidden("You are not authorized to process this payment.")

    # Booking status checks
    if booking.status == 'cancelled':
        messages.error(request, "This booking is no longer valid.")
        return redirect('bookings:booking_history')

    # Calculate total amount
    price_adults = Decimal(booking.passenger_adults) * Decimal('35.50')
    price_children = Decimal(booking.passenger_children) * Decimal('20.00')
    price_infants = Decimal(booking.passenger_infants) * Decimal('0.00')

    cargo_price = Decimal('0.00')
    if hasattr(booking, 'cargo_set'):
        cargo_price = sum((cargo.price or Decimal('0.00')) for cargo in booking.cargo_set.all())

    total_price = price_adults + price_children + price_infants + cargo_price

    # Handle price difference from modification
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

    # Handle POST: create Stripe session
    if request.method == 'POST':
        try:
            amount_cents = int(amount_to_charge * 100)
            if amount_cents <= 0:
                return JsonResponse({'error': 'Payment amount must be positive.'}, status=400)

            # Determine email for Stripe
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

            # Save session ID to booking
            booking.stripe_session_id = session.id
            booking.save()

            # Create Payment object
            Payment.objects.create(
                booking=booking,
                payment_method='stripe',
                amount=amount_to_charge,
                session_id=session.id,
                payment_status='pending'
            )

            # Store booking/session in Django session
            request.session['booking_id'] = booking.id
            request.session['stripe_session_id'] = session.id
            if booking.guest_email and not request.user.is_authenticated:
                request.session['guest_email'] = booking.guest_email
            request.session.pop('price_difference', None)

            return JsonResponse({'sessionId': session.id})

        except stripe.error.StripeError as e:
            body = getattr(e, 'json_body', None)
            err = body.get('error') if body else str(e)
            logger.error(f"Stripe error for booking {booking_id}: {err}")
            return JsonResponse({'error': f"Payment processing error: {err}"}, status=400)
        except Exception as e:
            logger.error(f"Unexpected error for booking {booking_id}: {str(e)}")
            return JsonResponse({'error': 'An unexpected error occurred. Please contact support.'}, status=500)

    # GET: render payment page
    return render(request, 'bookings/payment.html', {
        'booking': booking,
        'amount_to_charge': amount_to_charge,
        'price_adults': price_adults,
        'price_children': price_children,
        'price_infants': price_infants,
        'cargo_price': cargo_price,
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY
    })



@login_required_allow_anonymous
def payment_success(request):
    booking_id = request.session.get('booking_id')
    session_id = request.GET.get('session_id') or request.session.get('stripe_session_id')

    logger.debug(f"Payment success: booking_id={booking_id}, session_id={session_id}, session={dict(request.session)}")

    # Fallback to retrieve booking_id and guest_email from Stripe metadata
    if not booking_id and session_id and session_id != '{CHECKOUT_SESSION_ID}':
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY
            session = stripe.checkout.Session.retrieve(session_id)
            booking_id = session.metadata.get('booking_id')
            guest_email = session.metadata.get('guest_email')
            if guest_email and not request.session.get('guest_email'):
                request.session['guest_email'] = guest_email
                logger.debug(f"Restored guest_email from metadata: {guest_email}")
            logger.debug(f"Retrieved booking_id from metadata: {booking_id}")
        except stripe.error.StripeError as e:
            logger.error(f"Stripe error retrieving session {session_id}: {str(e)}")
            messages.error(request, "Error verifying payment session. Please contact support.")
            return redirect('bookings:booking_history')

    # Check for missing booking_id
    if not booking_id:
        logger.error("Missing booking_id in session and metadata")
        messages.error(request, "Payment status could not be verified due to missing booking information. Please contact support.")
        return redirect('bookings:booking_history')

    # Fetch booking
    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        logger.error(f"Booking {booking_id} not found")
        messages.error(request, "Booking not found. Please contact support.")
        return redirect('bookings:booking_history')

    # Authorization checks
    if request.user.is_authenticated and booking.user != request.user:
        logger.error(f"Authorization failed: User {request.user} not authorized for booking {booking_id}")
        return HttpResponseForbidden("You are not authorized to view this booking.")
    if not request.user.is_authenticated and booking.guest_email != request.session.get('guest_email'):
        logger.error(f"Authorization failed: Guest email mismatch for booking {booking_id}, expected={booking.guest_email}, got={request.session.get('guest_email')}")
        return HttpResponseForbidden("You are not authorized to view this booking.")

    # Check booking status
    if booking.evaluated_status == 'cancelled':
        logger.error(f"Booking {booking_id} is cancelled or expired")
        messages.error(request, "This booking is no longer valid.")
        return redirect('bookings:booking_history')

    # Handle missing or invalid session_id
    if not session_id or session_id == '{CHECKOUT_SESSION_ID}':
        logger.warning(f"Invalid or missing session_id, falling back to booking.stripe_session_id for booking {booking_id}")
        session_id = booking.stripe_session_id
        if not session_id:
            logger.error(f"No valid session_id found for booking {booking_id}")
            messages.error(request, "Invalid payment session. Please try again or contact support.")
            return redirect('bookings:booking_history')

    try:
        # Initialize passengers list
        passengers = []

        # Debug mode for testing
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
            # Try all Payment objects associated with the booking
            payments = Payment.objects.filter(booking=booking).order_by('-payment_date')  # Fixed: Use payment_date
            session_found = False
            for payment in payments:
                try:
                    session = stripe.checkout.Session.retrieve(payment.session_id, expand=['payment_intent'])
                    if session.metadata.get('booking_id') != str(booking_id):
                        logger.warning(f"Session {payment.session_id} metadata mismatch for booking {booking_id}")
                        continue
                    if not session.payment_intent:
                        logger.warning(f"No payment_intent found for session {payment.session_id}, booking {booking_id}")
                        continue
                    session_found = True
                    break
                except stripe.error.InvalidRequestError as e:
                    logger.error(f"InvalidRequestError for session {payment.session_id}, booking {booking_id}: {str(e)}")
                    continue

            if not session_found:
                logger.error(f"No valid session with payment_intent found for booking {booking_id}")
                messages.error(request, "Payment could not be verified. Please contact support.")
                return redirect('bookings:booking_history')

            # Update or create Payment object
            payment, created = Payment.objects.get_or_create(
                booking=booking,
                session_id=session.id,
                defaults={
                    'payment_method': 'stripe',
                    'amount': Decimal(session.amount_total) / 100,
                    'payment_status': 'pending'
                }
            )

            if created:
                logger.info(f"Created new Payment object for booking {booking.id}: session_id={session.id}")
            else:
                logger.info(f"Found existing Payment object for booking {booking.id}: session_id={session.id}")

            payment.payment_intent_id = session.payment_intent.id
            payment.transaction_id = session.payment_intent.id
            payment.amount = Decimal(session.payment_intent.amount) / 100
            if session.payment_intent.status == 'succeeded':
                payment.payment_status = 'completed'
                booking.status = 'confirmed'
                booking.payment_intent_id = session.payment_intent.id
                booking.stripe_session_id = session.id
                booking.save()
                logger.info(f"Payment confirmed for booking {booking.id}: payment_intent_id={session.payment_intent.id}")
            else:
                logger.warning(f"Payment not completed for booking {booking.id}: status={session.payment_intent.status}")
                messages.error(request, f"Payment is not completed yet. Status: {session.payment_intent.status}")
                return redirect('bookings:booking_history')
            payment.save()

        # Synchronize passengers and tickets
        existing_passengers = list(Passenger.objects.filter(booking=booking).order_by('id'))
        total_existing = len(existing_passengers)
        desired_passengers = (
            [('adult', 30)] * booking.passenger_adults +
            [('child', 10)] * booking.passenger_children +
            [('infant', 1)] * booking.passenger_infants
        )

        # Populate passengers list with existing passengers
        passengers.extend(existing_passengers)

        for i, (ptype, age) in enumerate(desired_passengers):
            if i < total_existing:
                p = existing_passengers[i]
                p.passenger_type = ptype
                p.age = age
                p.first_name = f"{ptype.capitalize()}{i + 1}" if not p.first_name else p.first_name
                p.last_name = "Passenger" if not p.last_name else p.last_name
                p.save()
            else:
                # Create new passenger if needed
                passenger = Passenger.objects.create(
                    booking=booking,
                    passenger_type=ptype,
                    first_name=f"{ptype.capitalize()}{i + 1}",
                    last_name="Passenger",
                    age=age,
                    verification_status='missing'
                )
                passengers.append(passenger)

        # Delete extra passengers if any
        if total_existing > len(desired_passengers):
            for p in existing_passengers[len(desired_passengers):]:
                p.delete()
                if p in passengers:
                    passengers.remove(p)

        # Generate tickets for confirmed booking
        for passenger in passengers:
            if not Ticket.objects.filter(booking=booking, passenger=passenger).exists():
                ticket = Ticket.objects.create(
                    booking=booking,
                    passenger=passenger,
                    ticket_status='active',
                    qr_token=str(uuid.uuid4())
                )
                qr_data = request.build_absolute_uri(reverse('bookings:view_ticket', args=[ticket.qr_token]))
                qr = qrcode.make(qr_data)
                buffer = BytesIO()
                qr.save(buffer, format='PNG')
                ticket.qr_code.save(f"ticket_{ticket.id}.png", ContentFile(buffer.getvalue()))

        # Generate cargo QR if applicable
        cargo = Cargo.objects.filter(booking=booking).first()
        if cargo and not cargo.qr_code:
            generate_cargo_qr(request, cargo)

        # Send confirmation email
        try:
            recipient = booking.user.email if booking.user else booking.guest_email
            if recipient:
                send_mail(
                    subject=f'Booking Confirmation #{booking.id}',
                    message=(
                        f'Your booking #{booking.id} for {booking.schedule.route} on '
                        f'{booking.schedule.departure_time.strftime("%Y-%m-%d %H:%M")} '
                        f'has been confirmed.\n\n'
                        f'Total Passengers: {booking.number_of_passengers}\n'
                        f'Total Amount: FJD {booking.total_price}\n'
                        f'View your tickets at: {request.build_absolute_uri(reverse("bookings:view_tickets", args=[booking.id]))}'
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[recipient],
                    fail_silently=True
                )
                logger.info(f"Confirmation email sent for booking {booking.id} to {recipient}")
            else:
                logger.warning(f"No recipient email for booking {booking.id}")
        except Exception as e:
            logger.error(f"Failed to send confirmation email for booking {booking.id}: {str(e)}")

        # Clear session data
        request.session.pop('booking_id', None)
        request.session.pop('stripe_session_id', None)
        request.session.pop('price_difference', None)

        messages.success(request, f"Payment successful! Booking #{booking.id} confirmed.")
        return redirect('bookings:view_tickets', booking_id=booking.id)

    except Exception as e:
        logger.exception(f"Unexpected error in payment_success for booking {booking_id}: {str(e)}")
        messages.error(request, "An error occurred while processing your payment. Please contact support.")
        return redirect('bookings:booking_history')

@login_required
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    # Check if booking is cancellable
    if booking.status != 'pending':
        messages.error(request, "Only pending bookings can be cancelled.")
        return redirect('bookings:booking_history')

    cutoff_time = booking.schedule.departure_time - timezone.timedelta(hours=6)
    if timezone.now() > cutoff_time:
        messages.error(request, "Cannot cancel booking within 6 hours of departure.")
        return redirect('bookings:booking_history')

    try:
        # Refund payment if completed
        payment = Payment.objects.filter(booking=booking, payment_status='completed').first()
        if payment and payment.payment_intent_id:
            try:
                refund = stripe.Refund.create(
                    payment_intent=payment.payment_intent_id,
                    amount=int(payment.amount * 100)
                )
                payment.payment_status = 'refunded'
                payment.save()
                logger.info(f"Refund processed for booking {booking.id}: refund_id={refund.id}")
            except stripe.error.StripeError as e:
                logger.error(f"Stripe refund error for booking {booking.id}: {str(e)}")
                messages.error(request, "Failed to process refund. Please contact support.")
                return redirect('bookings:booking_history')

        # Update booking status
        booking.status = 'cancelled'
        booking.save()

        # Restore seats
        schedule = booking.schedule
        schedule.available_seats += booking.number_of_passengers
        schedule.save()

        # Notify user
        send_mail(
            subject=f'Booking Cancellation #{booking.id}',
            message=(
                f'Your booking #{booking.id} for {booking.schedule.route} on '
                f'{booking.schedule.departure_time.strftime("%Y-%m-%d %H:%M")} '
                f'has been cancelled.\n'
                f'Refunded Amount: FJD {payment.amount if payment else 0}'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[request.user.email],
            fail_silently=True
        )

        messages.success(request, f"Booking #{booking.id} has been cancelled.")
        return redirect('bookings:booking_history')

    except Exception as e:
        logger.exception(f"Error cancelling booking {booking.id}: {str(e)}")
        messages.error(request, "An error occurred while cancelling your booking. Please contact support.")
        return redirect('bookings:booking_history')


@login_required
def modify_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    # Check if booking can be modified
    cutoff_time = booking.schedule.departure_time - timezone.timedelta(hours=6)
    if timezone.now() > cutoff_time:
        messages.error(request, "Cannot modify booking within 6 hours of departure.")
        return redirect('bookings:booking_history')

    if booking.status != 'confirmed':
        messages.error(request, "Only confirmed bookings can be modified.")
        return redirect('bookings:booking_history')

    form = ModifyBookingForm(request.POST or None, instance=booking)
    if request.method == 'POST' and form.is_valid():
        try:
            # Calculate price difference
            old_price = booking.total_price
            new_schedule = form.cleaned_data['schedule']
            adults = form.cleaned_data['passenger_adults']
            children = form.cleaned_data['passenger_children']
            infants = form.cleaned_data['passenger_infants']

            # Map youths from form to children in model
            youths = safe_int(request.POST.get('youths', '0'))
            children += youths

            new_price = calculate_total_price(
                adults=adults,
                youths=youths,
                children=children - youths,
                infants=infants,
                schedule=new_schedule,
                add_cargo=booking.cargo is not None,
                cargo_type=booking.cargo.cargo_type if booking.cargo else '',
                weight_kg=booking.cargo.weight_kg if booking.cargo else 0,
                is_emergency=booking.is_emergency
            )

            price_difference = new_price - old_price

            # Update booking
            booking.passenger_adults = adults
            booking.passenger_children = children
            booking.passenger_infants = infants
            booking.schedule = new_schedule
            booking.total_price = new_price
            booking.save()

            # Adjust passenger records
            existing_passengers = list(Passenger.objects.filter(booking=booking).order_by('id'))
            total_existing = len(existing_passengers)
            desired_passengers = (
                    [('adult', 30)] * adults +
                    [('child', 10)] * children +
                    [('infant', 1)] * infants
            )

            for i, (ptype, age) in enumerate(desired_passengers):
                if i < total_existing:
                    p = existing_passengers[i]
                    p.passenger_type = ptype
                    p.age = age
                    p.first_name = f"{ptype.capitalize()}{i + 1}" if not p.first_name else p.first_name
                    p.last_name = "Passenger" if not p.last_name else p.last_name
                    p.save()
                else:
                    Passenger.objects.create(
                        booking=booking,
                        passenger_type=ptype,
                        first_name=f"{ptype.capitalize()}{i + 1}",
                        last_name="Passenger",
                        age=age,
                        verification_status='missing'
                    )

            if total_existing > len(desired_passengers):
                for p in existing_passengers[len(desired_passengers):]:
                    p.delete()

            # Update schedule seats
            old_schedule = Schedule.objects.get(id=booking.schedule_id)
            old_schedule.available_seats += booking.number_of_passengers
            old_schedule.save()

            new_schedule.available_seats -= (adults + children + infants)
            new_schedule.save()

            # Store price difference for payment
            if price_difference > 0:
                request.session['price_difference'] = str(price_difference)
                return redirect('bookings:process_payment', booking_id=booking.id)
            else:
                # If no additional payment needed, regenerate tickets
                Ticket.objects.filter(booking=booking).delete()
                for passenger in booking.passengers.all():
                    ticket = Ticket.objects.create(
                        booking=booking,
                        passenger=passenger,
                        ticket_status='active',
                        qr_token=str(uuid.uuid4())
                    )
                    qr_data = request.build_absolute_uri(reverse('bookings:view_ticket', args=[ticket.qr_token]))
                    qr = qrcode.make(qr_data)
                    buffer = BytesIO()
                    qr.save(buffer, format='PNG')
                    ticket.qr_code.save(f"ticket_{ticket.id}.png", ContentFile(buffer.getvalue()))

                messages.success(request, f"Booking #{booking.id} has been modified.")
                return redirect('bookings:view_tickets', booking_id=booking.id)

        except Exception as e:
            logger.exception(f"Error modifying booking {booking.id}: {str(e)}")
            messages.error(request, "An error occurred while modifying your booking. Please contact support.")
            return redirect('bookings:booking_history')

    return render(request, 'bookings/modify_booking.html', {
        'form': form,
        'booking': booking,
        'schedules': Schedule.objects.filter(status='scheduled', departure_time__gt=timezone.now())
    })


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
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        logger.error("Invalid webhook signature")
        return HttpResponse(status=400)

    logger.debug(f"Webhook event received: type={event['type']}, id={event['id']}")

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        booking_id = session.get('metadata', {}).get('booking_id')
        if not booking_id:
            logger.error("No booking_id in webhook metadata")
            return HttpResponse(status=400)

        try:
            booking = Booking.objects.get(id=booking_id)
            payment = Payment.objects.filter(booking=booking, session_id=session['id']).first()
            if not payment:
                logger.error(f"No Payment object found for session {session['id']}, booking {booking_id}")
                return HttpResponse(status=400)

            if session.get('payment_intent'):
                payment.payment_intent_id = session['payment_intent']
                payment.transaction_id = session['payment_intent']
                payment.amount = Decimal(session['amount_total']) / 100
                if session.get('payment_status') == 'paid':
                    payment.payment_status = 'completed'
                    booking.status = 'confirmed'
                    booking.payment_intent_id = session['payment_intent']
                    booking.stripe_session_id = session['id']
                    booking.save()
                    payment.save()
                    logger.info(f"Webhook processed: booking {booking_id} confirmed")
                else:
                    logger.warning(f"Webhook payment not completed for booking {booking_id}: status={session['payment_status']}")
            else:
                logger.error(f"No payment_intent in webhook for session {session['id']}, booking {booking_id}")
        except Booking.DoesNotExist:
            logger.error(f"Booking {booking_id} not found in webhook")
            return HttpResponse(status=404)

    return HttpResponse(status=200)


def cancel_payment(request):
    booking_id = request.session.get('booking_id')
    if booking_id:
        try:
            booking = Booking.objects.get(id=booking_id)
            if booking.status == 'pending':
                booking.status = 'cancelled'
                booking.save()
                schedule = booking.schedule
                schedule.available_seats += booking.number_of_passengers
                schedule.save()
                logger.info(f"Payment cancelled for booking {booking.id}")
                messages.success(request, f"Booking #{booking.id} has been cancelled.")
        except Booking.DoesNotExist:
            logger.error(f"Booking {booking_id} not found during cancel_payment")
            messages.error(request, "Booking not found.")

        # Clear session
        request.session.pop('booking_id', None)
        request.session.pop('stripe_session_id', None)
        request.session.pop('price_difference', None)

    return redirect('bookings:booking_history')
