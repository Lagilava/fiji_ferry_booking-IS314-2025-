import logging
import stripe
from datetime import timedelta
import requests
from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db.models import Subquery, Max, OuterRef
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


# Pricing helper functions
def calculate_cargo_price(weight, cargo_type):
    base_rate = Decimal('5.00')
    type_multiplier = {
        'parcel': Decimal('1.0'),
        'pallet': Decimal('1.2'),
        'vehicle': Decimal('3.0'),
        'bulk': Decimal('1.5')
    }
    return weight * base_rate * type_multiplier.get(cargo_type, Decimal('1.0'))


def calculate_passenger_price(adults, children, infants, schedule):
    base_fare = schedule.route.base_fare or Decimal('35.50')
    return (adults * base_fare) + (children * base_fare * Decimal('0.5')) + (infants * base_fare * Decimal('0.1'))


def calculate_total_price(adults, children, infants, schedule, add_cargo, cargo_type, weight_kg, is_emergency):
    passenger_price = calculate_passenger_price(adults, children, infants, schedule)
    cargo_price = calculate_cargo_price(Decimal(weight_kg),
                                       cargo_type) if add_cargo and cargo_type and weight_kg else Decimal('0.00')
    emergency_surcharge = Decimal('50.00') if is_emergency else Decimal('0.00')
    return passenger_price + cargo_price + emergency_surcharge


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


def homepage(request):
    now = timezone.now()
    schedules = Schedule.objects.filter(
        status='scheduled',
        departure_time__gt=now
    ).select_related('ferry', 'route').order_by('departure_time')

    route_input = request.GET.get('route', '').strip()
    travel_date = request.GET.get('date', '').strip()

    logger.debug(f"Search parameters: route={route_input}, travel_date={travel_date}")

    if route_input:
        try:
            origin, destination = route_input.split('-to-')
            schedules = schedules.filter(
                route__departure_port__name__icontains=origin.strip(),
                route__destination_port__name__icontains=destination.strip()
            )
        except ValueError:
            messages.error(request, "Invalid route format. Use 'origin-to-destination' (e.g., nadi-to-suva).")

    if travel_date:
        try:
            travel_date_obj = timezone.datetime.strptime(travel_date, '%Y-%m-%d')
            travel_date_start = timezone.make_aware(travel_date_obj)
            travel_date_end = travel_date_start + timezone.timedelta(days=1)
            schedules = schedules.filter(
                departure_time__range=(travel_date_start, travel_date_end)
            )
        except ValueError:
            messages.error(request, "Invalid date format. Please use YYYY-MM-DD.")

    # Get all routes for datalist
    routes = Route.objects.all()

    # Get the next departure for initial display
    next_departure = schedules.first()
    next_departure_info = None
    if next_departure:
        next_departure_info = {
            'time': next_departure.departure_time.strftime('%a, %b %d, %H:%M'),
            'route': f"{next_departure.route.departure_port} to {next_departure.route.destination_port}",
            'schedule_id': next_departure.id
        }

    # Fetch initial weather data for routes in schedules
    weather_data = []
    # Get unique route_ids from schedules
    schedule_route_ids = schedules.values_list('route_id', flat=True).distinct()
    # Subquery to get the latest updated_at for each route_id
    latest_conditions_subquery = WeatherCondition.objects.filter(
        route_id=OuterRef('route_id'),
        expires_at__gt=timezone.now()
    ).values('route_id').annotate(
        latest_updated=Max('updated_at')
    ).values('latest_updated')

    # Main query to get the latest WeatherCondition for scheduled routes
    latest_conditions = WeatherCondition.objects.filter(
        route_id__in=schedule_route_ids,
        expires_at__gt=timezone.now(),
        updated_at__in=Subquery(latest_conditions_subquery)
    )

    latest_per_route = {wc.route_id: wc for wc in latest_conditions}

    for schedule in schedules:
        wc = latest_per_route.get(schedule.route_id)
        if wc:
            weather_data.append({
                'route_id': schedule.route_id,
                'port': wc.port.name,
                'condition': wc.condition,
                'temperature': float(wc.temperature) if wc.temperature is not None else None,
                'wind_speed': float(wc.wind_speed) if wc.wind_speed is not None else None,
                'precipitation_probability': float(wc.precipitation_probability) if wc.precipitation_probability is not None else None,
                'expires_at': wc.expires_at.isoformat(),
                'updated_at': wc.updated_at.isoformat(),
                'is_expired': wc.is_expired(),
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

    return render(request, 'home.html', {
        'schedules': schedules,
        'routes': routes,
        'form_data': {'route': route_input, 'date': travel_date},
        'weather_data': weather_data,
        'next_departure': next_departure_info
    })


@login_required_allow_anonymous
def booking_history(request):
    logger.debug(
        f"Fetching booking history for user={request.user if request.user.is_authenticated else 'Guest'}, session_guest_email={request.session.get('guest_email')}")
    logger.debug(f"Messages: {list(messages.get_messages(request))}")

    if request.user.is_authenticated:
        bookings = Booking.objects.filter(user=request.user).select_related('schedule__ferry',
                                                                            'schedule__route').order_by('-booking_date')
    else:
        guest_email = request.session.get('guest_email')
        bookings = Booking.objects.filter(guest_email=guest_email).select_related('schedule__ferry',
                                                                                  'schedule__route').order_by(
            '-booking_date') if guest_email else []

    for booking in bookings:
        booking.update_status_if_expired()

    return render(request, 'bookings/history.html', {
        'bookings': bookings,
        'cutoff_time': timezone.now() + timezone.timedelta(hours=6)
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


def get_pricing(request):
    try:
        schedule_id = request.GET.get('schedule_id')
        if not schedule_id:
            logger.error("Missing schedule_id in get_pricing")
            return JsonResponse({'error': 'Schedule ID is required.'}, status=400)

        adults = request.GET.get('adults', '0')
        children = request.GET.get('children', '0')
        infants = request.GET.get('infants', '0')
        add_cargo = request.GET.get('add_cargo') == 'true'
        cargo_type = request.GET.get('cargo_type', '')
        weight_kg = request.GET.get('weight_kg', '0')
        is_emergency = request.GET.get('is_emergency') == 'true'

        try:
            adults = int(adults)
            children = int(children)
            infants = int(infants)
            weight_kg = float(weight_kg) if weight_kg else 0.0
        except ValueError:
            logger.error(
                f"Invalid numeric inputs: adults={adults}, children={children}, infants={infants}, weight_kg={weight_kg}")
            return JsonResponse({'error': 'Passenger counts and weight must be valid numbers.'}, status=400)

        if adults < 0 or children < 0 or infants < 0 or weight_kg < 0:
            logger.error(
                f"Negative values detected: adults={adults}, children={children}, infants={infants}, weight_kg={weight_kg}")
            return JsonResponse({'error': 'Passenger counts and weight cannot be negative.'}, status=400)

        if add_cargo and not cargo_type:
            logger.error("Missing cargo_type when add_cargo is true")
            return JsonResponse({'error': 'Cargo type is required when adding cargo.'}, status=400)

        schedule = get_object_or_404(Schedule, id=schedule_id)
        total_price = calculate_total_price(
            adults, children, infants, schedule,
            add_cargo, cargo_type, weight_kg, is_emergency
        )

        return JsonResponse({
            'total_price': str(total_price),
            'breakdown': {
                'adults': str(calculate_passenger_price(adults, 0, 0, schedule)),
                'children': str(calculate_passenger_price(0, children, 0, schedule)),
                'infants': str(calculate_passenger_price(0, 0, infants, schedule)),
                'cargo': str(
                    calculate_cargo_price(Decimal(weight_kg), cargo_type) if add_cargo and cargo_type else Decimal(
                        '0.00')),
                'emergency_surcharge': str(Decimal('50.00') if is_emergency else Decimal('0.00'))
            }
        })
    except Schedule.DoesNotExist:
        logger.error(f"Schedule not found: schedule_id={schedule_id}")
        return JsonResponse({'error': 'Invalid schedule ID.'}, status=400)
    except Exception as e:
        logger.error(f"Pricing error: {str(e)}")
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


@csrf_exempt
def validate_step(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'errors': ['Invalid request method'], 'step': 1})

    step = request.POST.get('step')
    errors = []

    if step == '1':
        schedule_id = request.POST.get('schedule_id', '').strip()
        is_authenticated = request.POST.get('user_authenticated') == 'true'
        guest_email = request.POST.get('guest_email', '').strip()

        if not schedule_id or not Schedule.objects.filter(id=schedule_id).exists():
            errors.append('Please select a valid ferry trip.')
        if not is_authenticated and not guest_email:
            errors.append('Guest email is required.')

    elif step == '2':
        adults = int(request.POST.get('adults', 0))
        children = int(request.POST.get('children', 0))
        infants = int(request.POST.get('infants', 0))

        if adults + children + infants == 0:
            errors.append('At least one passenger is required.')
        if infants > 0 and adults == 0:
            errors.append('Infants cannot be booked without an adult.')

        for type in ['adult', 'child', 'infant']:
            count = adults if type == 'adult' else children if type == 'child' else infants
            for i in range(count):
                first_name = request.POST.get(f'passenger_{type}_{i}_first_name', '').strip()
                last_name = request.POST.get(f'passenger_{type}_{i}_last_name', '').strip()
                age = request.POST.get(f'passenger_{type}_{i}_age', '')

                if not first_name:
                    errors.append(f'{type.capitalize()} {i + 1}: First name is required.')
                if not last_name:
                    errors.append(f'{type.capitalize()} {i + 1}: Last name is required.')
                try:
                    age = int(age)
                    if type == 'infant' and not (0 <= age <= 1):
                        errors.append(f'Infant {i + 1}: Age must be 0-1.')
                    elif type == 'child' and not (2 <= age <= 11):
                        errors.append(f'Child {i + 1}: Age must be 2-11.')
                    elif type == 'adult' and age < 12:
                        errors.append(f'Adult {i + 1}: Age must be 12 or older.')
                except ValueError:
                    errors.append(f'{type.capitalize()} {i + 1}: Invalid age.')

        has_minors = children > 0 or infants > 0
        has_parent = any(
            request.POST.get(f'passenger_adult_{i}_is_parent') == 'on'
            for i in range(adults)
        )
        responsibility_declaration = 'responsibility_declaration' in request.FILES
        if has_minors and adults > 0 and not has_parent and not responsibility_declaration:
            errors.append('Responsibility declaration is required if no adult is a parent.')

    elif step == '3':
        is_unaccompanied_minor = request.POST.get('is_unaccompanied_minor') == 'on'
        has_minors = int(request.POST.get('children', 0)) > 0 or int(request.POST.get('infants', 0)) > 0
        if is_unaccompanied_minor and has_minors:
            if not request.POST.get('guardian_contact', '').strip():
                errors.append('Guardian contact is required for unaccompanied minors.')
            if 'consent_form' not in request.FILES:
                errors.append('Consent form is required for unaccompanied minors.')
        if request.POST.get('add_cargo_checkbox') == 'on':
            if not request.POST.get('cargo_type', '').strip():
                errors.append('Cargo type is required.')
            try:
                weight = float(request.POST.get('weight_kg', 0))
                if weight <= 0:
                    errors.append('Cargo weight must be a positive number.')
            except ValueError:
                errors.append('Cargo weight must be a positive number.')

    elif step == '4':
        if request.POST.get('privacy_consent') != 'on':
            errors.append('You must agree to the privacy policy.')

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
        file_validator(file)
        if file.size > 5 * 1024 * 1024:
            logger.error(f'File too large: {file.size} bytes')
            return JsonResponse({'error': 'File size must be less than 5MB.'}, status=400)
        return JsonResponse({'success': True})
    except ValidationError as e:
        logger.error(f'Invalid file: {str(e)}')
        return JsonResponse({'error': f'File must be a PDF, JPG, JPEG, or PNG.'}, status=400)



@login_required_allow_anonymous
def book_ticket(request):
    available_schedules = Schedule.objects.filter(
        status='scheduled', departure_time__gt=timezone.now()
    ).select_related('ferry', 'route')

    if request.method == 'POST':
        logger.debug(f'POST data: {request.POST}')
        logger.debug(f'FILES data: {request.FILES}')
        try:
            adults = int(request.POST.get('adults', '0'))
            children = int(request.POST.get('children', '0'))
            infants = int(request.POST.get('infants', '0'))
        except ValueError:
            logger.error('Invalid passenger count input')
            return JsonResponse({
                'error': 'Passenger counts must be valid numbers.',
                'step': 2
            }, status=400)

        if adults < 0 or children < 0 or infants < 0:
            logger.error('Negative passenger counts')
            return JsonResponse({
                'error': 'Passenger counts cannot be negative.',
                'step': 2
            }, status=400)

        if infants > 0 and adults == 0:
            logger.error('Infants cannot be booked without an adult')
            return JsonResponse({
                'error': 'Infants cannot be booked without an adult.',
                'step': 2
            }, status=400)

        schedule_id = request.POST.get('schedule_id')
        guest_email = request.POST.get('guest_email')
        is_unaccompanied_minor = bool(request.POST.get('is_unaccompanied_minor'))
        guardian_contact = request.POST.get('guardian_contact')
        consent_form = request.FILES.get('consent_form')
        is_group_booking = bool(request.POST.get('is_group_booking'))
        add_cargo = bool(request.POST.get('add_cargo_checkbox'))
        cargo_type = request.POST.get('cargo_type')
        weight_kg = request.POST.get('weight_kg')
        dimensions_cm = request.POST.get('dimensions_cm')
        is_emergency = bool(request.POST.get('is_emergency'))
        privacy_consent = bool(request.POST.get('privacy_consent'))
        responsibility_declaration = request.FILES.get('responsibility_declaration')

        file_validator = FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])
        if consent_form:
            try:
                file_validator(consent_form)
            except Exception as e:
                logger.error(f'Invalid consent form file: {str(e)}')
                return JsonResponse({
                    'error': 'Consent form must be a PDF, JPG, JPEG, or PNG file.',
                    'step': 3
                }, status=400)
        if responsibility_declaration:
            try:
                file_validator(responsibility_declaration)
            except Exception as e:
                logger.error(f'Invalid responsibility declaration file: {str(e)}')
                return JsonResponse({
                    'error': 'Responsibility declaration must be a PDF, JPG, JPEG, or PNG file.',
                    'step': 2
                }, status=400)

        form_data = {
            'schedule_id': schedule_id,
            'adults': adults,
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

        passenger_types = [('adult', adults), ('child', children), ('infant', infants)]
        for p_type, count in passenger_types:
            for i in range(count):
                form_data[f'passenger_{p_type}_{i}_first_name'] = request.POST.get(f'passenger_{p_type}_{i}_first_name', '')
                form_data[f'passenger_{p_type}_{i}_last_name'] = request.POST.get(f'passenger_{p_type}_{i}_last_name', '')
                form_data[f'passenger_{p_type}_{i}_age'] = request.POST.get(f'passenger_{p_type}_{i}_age', '')
                form_data[f'passenger_{p_type}_{i}_is_group_leader'] = request.POST.get(f'passenger_{p_type}_{i}_is_group_leader', '')
                form_data[f'passenger_{p_type}_{i}_is_parent'] = request.POST.get(f'passenger_{p_type}_{i}_is_parent', '')
                document = request.FILES.get(f'passenger_{p_type}_{i}_document')
                if document:
                    try:
                        file_validator(document)
                    except Exception as e:
                        logger.error(f'Invalid document for {p_type} {i + 1}: {str(e)}')
                        return JsonResponse({
                            'error': f'Document for {p_type.capitalize()} {i + 1} must be a PDF, JPG, JPEG, or PNG file.',
                            'step': 2
                        }, status=400)
                form_data[f'passenger_{p_type}_{i}_document'] = document

        has_parent = any(form_data.get(f'passenger_adult_{i}_is_parent') == 'on' for i in range(adults))

        if not schedule_id:
            logger.error('No schedule selected')
            return JsonResponse({
                'error': 'Please select a schedule.',
                'step': 1
            }, status=400)
        if not request.user.is_authenticated and not guest_email:
            logger.error('No guest email provided')
            return JsonResponse({
                'error': 'Guest email is required.',
                'step': 1
            }, status=400)

        total_passengers = adults + children + infants
        has_minors = children > 0 or infants > 0

        if total_passengers == 0:
            logger.error('No passengers selected')
            return JsonResponse({
                'error': 'At least one passenger is required.',
                'step': 2
            }, status=400)

        for p_type, count in passenger_types:
            for i in range(count):
                first_name = form_data[f'passenger_{p_type}_{i}_first_name']
                last_name = form_data[f'passenger_{p_type}_{i}_last_name']
                age = form_data[f'passenger_{p_type}_{i}_age']
                if not first_name.strip() or not last_name.strip():
                    logger.error(f'Missing name for {p_type} {i + 1}')
                    return JsonResponse({
                        'error': f'First and last name are required for {p_type.capitalize()} {i + 1}.',
                        'step': 2
                    }, status=400)
                if not age or not age.isdigit() or int(age) < (
                        0 if p_type == 'infant' else 2 if p_type == 'child' else 12) or int(age) > (
                        1 if p_type == 'infant' else 11 if p_type == 'child' else 150):
                    logger.error(f'Invalid age for {p_type} {i + 1}')
                    return JsonResponse({
                        'error': f'Age for {p_type.capitalize()} {i + 1} must be {"0-1" if p_type == "infant" else "2-11" if p_type == "child" else "12 or older"}.',
                        'step': 2
                    }, status=400)

        if children > 0 and adults == 0 and not responsibility_declaration:
            logger.error('Missing responsibility declaration for unaccompanied minors')
            return JsonResponse({
                'error': 'Responsibility declaration is required for unaccompanied minors.',
                'step': 2
            }, status=400)

        if has_minors and adults > 0 and not has_parent and not responsibility_declaration:
            logger.error('Missing responsibility declaration for non-parent adults with minors')
            return JsonResponse({
                'error': 'Responsibility declaration is required if no adult is a parent.',
                'step': 2
            }, status=400)

        if is_unaccompanied_minor and has_minors:
            if not guardian_contact:
                logger.error('Missing guardian contact for unaccompanied minor')
                return JsonResponse({
                    'error': 'Guardian contact is required for unaccompanied minors.',
                    'step': 3
                }, status=400)
            if not consent_form:
                logger.error('Missing consent form for unaccompanied minor')
                return JsonResponse({
                    'error': 'Consent form is required for unaccompanied minors.',
                    'step': 3
                }, status=400)

        if not privacy_consent:
            logger.error('Privacy consent not provided')
            return JsonResponse({
                'error': 'You must agree to the privacy policy.',
                'step': 4
            }, status=400)

        schedule = get_object_or_404(Schedule, id=schedule_id)

        if schedule.available_seats < total_passengers:
            logger.error('Not enough seats available')
            return JsonResponse({
                'error': 'Not enough seats available.',
                'step': 1
            }, status=400)

        total_price = calculate_total_price(
            adults, children, infants, schedule,
            add_cargo, cargo_type, float(weight_kg) if weight_kg else 0, is_emergency
        )

        booking_kwargs = {
            'user': request.user if request.user.is_authenticated else None,
            'schedule': schedule,
            'guest_email': guest_email if not request.user.is_authenticated else None,
            'passenger_adults': adults,
            'passenger_children': children,
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
        except TypeError as e:
            logger.error(f"Booking creation error: {str(e)}")
            return JsonResponse({
                'error': 'Failed to create booking due to invalid data.',
                'step': 4
            }, status=500)

        group_leader = None
        passengers = []
        for p_type, count in passenger_types:
            for i in range(count):
                first_name = form_data[f'passenger_{p_type}_{i}_first_name']
                last_name = form_data[f'passenger_{p_type}_{i}_last_name']
                age = form_data[f'passenger_{p_type}_{i}_age']
                is_group_leader_flag = form_data[f'passenger_{p_type}_{i}_is_group_leader'] == 'on'
                is_parent_flag = form_data[f'passenger_{p_type}_{i}_is_parent'] == 'on'
                document = form_data[f'passenger_{p_type}_{i}_document']
                verification_status = 'pending' if document else 'missing'
                passenger = Passenger.objects.create(
                    booking=booking,
                    first_name=first_name,
                    last_name=last_name,
                    age=age,
                    passenger_type=p_type,
                    document=document,
                    verification_status=verification_status,
                    is_group_leader=is_group_leader_flag,
                    is_parent=is_parent_flag
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

        if add_cargo and cargo_type and weight_kg:
            try:
                weight_kg = float(weight_kg)
                if weight_kg <= 0:
                    logger.error('Invalid cargo weight')
                    return JsonResponse({
                        'error': 'Cargo weight must be greater than zero.',
                        'step': 3
                    }, status=400)
                cargo = Cargo.objects.create(
                    booking=booking,
                    cargo_type=cargo_type,
                    weight_kg=Decimal(weight_kg),
                    dimensions_cm=dimensions_cm or '',
                    price=calculate_cargo_price(Decimal(weight_kg), cargo_type)
                )
                generate_cargo_qr(request, cargo)
            except ValueError:
                logger.error(f'Invalid cargo weight: {weight_kg}')
                return JsonResponse({
                    'error': 'Cargo weight must be a valid number.',
                    'step': 3
                }, status=400)

        if is_emergency:
            booking.notes = "Emergency booking: Verify child/infant documents on-site if missing."
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

        schedule.available_seats -= total_passengers
        schedule.save()

        if is_group_booking:
            logger.info(f"Group booking created: Booking #{booking.id}, Passengers: {total_passengers}")

        request.session['booking_id'] = booking.id
        if not request.user.is_authenticated and guest_email:
            request.session['guest_email'] = guest_email

        return JsonResponse({
            'success': True,
            'redirect_url': reverse('bookings:process_payment', args=[booking.id])
        })

    return render(request, 'bookings/book.html', {
        'schedules': available_schedules,
        'user': request.user,
        'form_data': {'step': 1, 'schedule_id': '', 'adults': 0, 'children': 0, 'infants': 0},
        'debug': True
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

    return render(request, 'bookings/ticket.html', {
        'booking': booking,
        'tickets': tickets,
        'cargo': cargo,
        'amount_to_charge': amount_to_charge,
        'price_adults': booking.passenger_adults * (booking.schedule.route.base_fare or Decimal('35.50')),
        'price_children': booking.passenger_children * (booking.schedule.route.base_fare or Decimal('35.50')) * Decimal(
            '0.5'),
        'price_infants': booking.passenger_infants * (booking.schedule.route.base_fare or Decimal('35.50')) * Decimal(
            '0.1'),
        'cargo_price': cargo.price if cargo else Decimal('0.00'),
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY
    })


@login_required_allow_anonymous
def process_payment(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    # Authorization checks
    if request.user.is_authenticated and booking.user != request.user:
        logger.error(f"Authorization failed: User {request.user} not authorized for booking {booking_id}")
        return HttpResponseForbidden("You are not authorized to process this payment.")
    if not request.user.is_authenticated and booking.guest_email != request.session.get('guest_email'):
        logger.error(
            f"Authorization failed: Guest email mismatch, booking.guest_email={booking.guest_email}, session.guest_email={request.session.get('guest_email')}")
        return HttpResponseForbidden("You are not authorized to process this payment.")

    # Check if booking is expired
    if booking.evaluated_status == 'cancelled':
        logger.error(f"Booking {booking_id} is cancelled or expired")
        messages.error(request, "This booking is no longer valid.")
        return redirect('bookings:booking_history')

    # Determine amount to charge
    price_difference = request.session.get('price_difference')
    amount_to_charge = Decimal(str(price_difference)) if price_difference and Decimal(
        str(price_difference)) > 0 else booking.total_price
    if amount_to_charge <= 0:
        logger.error(f"Invalid amount_to_charge for booking {booking_id}: {amount_to_charge}")
        return JsonResponse({'error': 'Payment amount must be greater than zero.'}, status=400)

    # Check if payment already completed
    if booking.payment_intent_id:
        try:
            payment_intent = stripe.PaymentIntent.retrieve(booking.payment_intent_id)
            if payment_intent.status == 'succeeded':
                booking.status = 'confirmed'
                booking.save()
                logger.info(f"Booking {booking_id} already paid, status updated to confirmed")
                return JsonResponse({'error': 'Payment already completed'}, status=400)
        except stripe.error.StripeError as e:
            logger.error(f"Error retrieving PaymentIntent {booking.payment_intent_id}: {str(e)}")

    if request.method == 'POST':
        try:
            amount_cents = int(amount_to_charge * 100)
            if amount_cents <= 0:
                logger.error(f"Invalid amount_cents for booking {booking_id}: {amount_cents}")
                return JsonResponse({'error': 'Payment amount must be positive.'}, status=400)

            success_url = request.build_absolute_uri('/bookings/success/?session_id={CHECKOUT_SESSION_ID}')
            logger.info(
                f"Creating Stripe session for booking {booking_id}, amount: {amount_to_charge} FJD, success_url={success_url}")

            # Check for existing session
            if booking.stripe_session_id:
                try:
                    session = stripe.checkout.Session.retrieve(booking.stripe_session_id)
                    if session.payment_status == 'paid':
                        logger.info(f"Existing session {session.id} already paid for booking {booking_id}")
                        return JsonResponse({'error': 'Payment already completed'}, status=400)
                    if session.status == 'open':
                        logger.info(f"Reusing existing session {session.id} for booking {booking_id}")
                        return JsonResponse({'sessionId': session.id})
                except stripe.error.InvalidRequestError:
                    logger.warning(f"Existing session {booking.stripe_session_id} invalid, creating new session")
                    booking.stripe_session_id = None
                    booking.save()

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
                cancel_url=request.build_absolute_uri('/bookings/cancel/'),
                metadata={'booking_id': str(booking_id)},
                customer_email=booking.guest_email or (booking.user.email if booking.user else None),
            )

            # Save session ID
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

            # Store in session
            request.session['booking_id'] = booking_id
            request.session['stripe_session_id'] = session.id
            request.session.pop('price_difference', None)

            logger.info(f"Stripe session created successfully for booking {booking_id}: session_id={session.id}")
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
        'price_adults': booking.passenger_adults * (booking.schedule.route.base_fare or Decimal('35.50')),
        'price_children': booking.passenger_children * (booking.schedule.route.base_fare or Decimal('35.50')) * Decimal(
            '0.5'),
        'price_infants': booking.passenger_infants * (booking.schedule.route.base_fare or Decimal('35.50')) * Decimal(
            '0.1'),
        'cargo_price': booking.cargo.price if hasattr(booking, 'cargo') else Decimal('0.00'),
        'stripe_publishable_key': settings.STRIPE_PUBLISHABLE_KEY
    })


@login_required_allow_anonymous
def payment_success(request):
    booking_id = request.session.get('booking_id')
    session_id = request.GET.get('session_id') or request.session.get('stripe_session_id')

    logger.debug(f"Payment success called: booking_id={booking_id}, session_id={session_id}")

    if not booking_id:
        logger.error("Missing booking_id in session")
        messages.error(request, "Payment status could not be verified. Please contact support.")
        return redirect('bookings:booking_history')

    booking = get_object_or_404(Booking, id=booking_id)

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

    # Use booking.stripe_session_id as fallback if session_id is invalid
    if not session_id or session_id == '{CHECKOUT_SESSION_ID}':
        logger.warning(
            f"Invalid or missing session_id, falling back to booking.stripe_session_id for booking {booking_id}")
        session_id = booking.stripe_session_id
        if not session_id:
            logger.error(f"No valid session_id found for booking {booking_id}")
            messages.error(request, "Invalid payment session. Please try again or contact support.")
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
            # Retrieve Stripe session
            session = stripe.checkout.Session.retrieve(session_id, expand=['payment_intent'])
            if not session.payment_intent:
                logger.error(f"No payment_intent found for session {session_id}, booking {booking_id}")
                messages.error(request, "Payment could not be verified. Please contact support.")
                return redirect('bookings:booking_history')

            payment_intent = session.payment_intent

            # Verify session matches booking
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

            if created:
                logger.info(f"Created new Payment object for booking {booking.id}: session_id={session.id}")
            else:
                logger.info(f"Found existing Payment object for booking {booking.id}: session_id={session.id}")

            payment.payment_intent_id = payment_intent.id
            payment.transaction_id = payment_intent.id
            payment.amount = Decimal(payment_intent.amount) / 100
            if payment_intent.status == 'succeeded':
                payment.payment_status = 'completed'
                booking.status = 'confirmed'
                booking.payment_intent_id = payment_intent.id
                booking.stripe_session_id = session.id
                booking.save()
                logger.info(f"Payment confirmed for booking {booking.id}: payment_intent_id={payment_intent.id}")
            else:
                logger.warning(f"Payment not completed for booking {booking.id}: status={payment_intent.status}")
                messages.error(request, f"Payment is not completed yet. Status: {payment_intent.status}")
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
                    first_name=f"{ptype.capitalize()}{i + 1}",
                    last_name="Passenger",
                    age=age,
                    passenger_type=ptype,
                    verification_status='pending' if ptype == 'adult' and (
                            booking.passenger_children > 0 or booking.passenger_infants > 0) else 'missing'
                )

        if total_existing > len(desired_passengers):
            to_remove = existing_passengers[len(desired_passengers):]
            for p in to_remove:
                Ticket.objects.filter(passenger=p).delete()
                p.delete()

        if booking.status == 'confirmed':
            for passenger in booking.passengers.all():
                ticket, created = Ticket.objects.get_or_create(
                    booking=booking,
                    passenger=passenger,
                    defaults={'ticket_status': 'active'}
                )
                if not created and ticket.ticket_status != 'active':
                    ticket.ticket_status = 'active'
                    ticket.save()
                    logger.info(f"Updated ticket {ticket.id} to active")
                if created or not ticket.qr_code:
                    qr_data = request.build_absolute_uri(reverse('bookings:view_ticket', args=[ticket.qr_token]))
                    qr = qrcode.make(qr_data)
                    buffer = BytesIO()
                    qr.save(buffer, format='PNG')
                    ticket.qr_code.save(f"ticket_{ticket.id}.png", ContentFile(buffer.getvalue()))
                    logger.info(f"Generated QR code for ticket {ticket.id}")

        # Send confirmation email
        email = booking.user.email if booking.user else booking.guest_email
        send_mail(
            'Booking Confirmation',
            f'Booking #{booking.id} confirmed. Thank you for your payment of {payment.amount} FJD.',
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=True
        )

        # Clear session data
        for key in ['booking_id', 'stripe_session_id', 'guest_email', 'price_difference']:
            request.session.pop(key, None)

        return render(request, 'bookings/success.html', {'message': 'Payment successful! Your booking is confirmed.'})

    except stripe.error.InvalidRequestError as e:
        logger.error(f"Stripe InvalidRequestError for session {session_id}, booking {booking_id}: {str(e)}")
        messages.error(request, "Invalid payment session. Please try again or contact support.")
        return redirect('bookings:booking_history')
    except stripe.error.StripeError as e:
        logger.error(f"Stripe error for session {session_id}, booking {booking_id}: {str(e)}")
        messages.error(request, "Error verifying payment with Stripe. Please contact support.")
        return redirect('bookings:booking_history')
    except Exception as e:
        logger.error(f"Unexpected error for session {session_id}, booking {booking_id}: {str(e)}")
        messages.error(request, "An unexpected error occurred while verifying payment. Please contact support.")
        return redirect('bookings:booking_history')


@login_required_allow_anonymous
def payment_cancel(request):
    booking_id = request.session.get('booking_id')
    if booking_id:
        booking = get_object_or_404(Booking, id=booking_id)
        if request.user.is_authenticated and booking.user != request.user:
            return HttpResponseForbidden("You are not authorized to cancel this booking.")
        if not request.user.is_authenticated and booking.guest_email != request.session.get('guest_email'):
            return HttpResponseForbidden("You are not authorized to cancel this booking.")
        if booking.status == 'pending':
            booking.status = 'cancelled'
            booking.schedule.available_seats += booking.number_of_passengers
            booking.schedule.save()
            booking.save()
            messages.success(request, f"Payment for Booking #{booking.id} was cancelled.")
        else:
            messages.info(request, f"Booking #{booking.id} cannot be cancelled as it is not pending.")
        request.session.pop('booking_id', None)
        request.session.pop('stripe_session_id', None)
        request.session.pop('guest_email', None)
        request.session.pop('price_difference', None)
    return render(request, 'bookings/cancel.html', {'message': 'Payment cancelled. Please try again.'})


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
        logger.info(
            f"Received webhook event: {event['type']}, event_id={event['id']}, booking_id={event['data']['object'].get('metadata', {}).get('booking_id')}")
    except ValueError:
        logger.error("Invalid webhook payload")
        return HttpResponse(status=400)
    except stripe.error.SignatureVerificationError:
        logger.error("Webhook signature verification failed. Check STRIPE_WEBHOOK_SECRET.")
        return HttpResponse(status=400)

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        booking_id = session['metadata'].get('booking_id')
        if not booking_id:
            logger.error(f"No booking_id in session metadata for session {session.id}")
            return HttpResponse(status=400)

        try:
            booking = Booking.objects.get(id=booking_id)
            payment = Payment.objects.get(session_id=session.id)
            if session.payment_status == 'paid':
                payment.payment_status = 'completed'
                payment.payment_intent_id = session.payment_intent
                payment.transaction_id = session.payment_intent
                payment.amount = Decimal(session.amount_total) / 100
                payment.save()
                booking.status = 'confirmed'
                booking.payment_intent_id = session.payment_intent
                booking.stripe_session_id = session.id
                booking.save()
                for passenger in booking.passengers.all():
                    ticket, created = Ticket.objects.get_or_create(
                        booking=booking,
                        passenger=passenger,
                        defaults={'ticket_status': 'active'}
                    )
                    if not created and ticket.ticket_status != 'active':
                        ticket.ticket_status = 'active'
                        ticket.save()
                        logger.info(f"Updated ticket {ticket.id} to active via webhook")
                    if created or not ticket.qr_code:
                        qr_data = request.build_absolute_uri(reverse('bookings:view_ticket', args=[ticket.qr_token]))
                        qr = qrcode.make(qr_data)
                        buffer = BytesIO()
                        qr.save(buffer, format='PNG')
                        ticket.qr_code.save(f"ticket_{ticket.id}.png", ContentFile(buffer.getvalue()))
                        logger.info(f"Generated QR code for ticket {ticket.id}")
                logger.info(f"Booking {booking.id} confirmed via checkout.session.completed webhook")
                email = session.get('customer_details', {}).get('email') or (
                    booking.user.email if booking.user else booking.guest_email)
                send_mail(
                    'Booking Confirmation',
                    f'Booking #{booking.id} confirmed. Thank you for your payment of {payment.amount} FJD.',
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=True
                )
        except Booking.DoesNotExist:
            logger.error(f"Booking {booking_id} not found for session {session.id}")
            return HttpResponse(status=404)
        except Payment.DoesNotExist:
            logger.error(f"Payment not found for session {session.id}, booking_id={booking_id}")
            return HttpResponse(status=404)

    elif event['type'] == 'payment_intent.succeeded':
        payment_intent = event['data']['object']
        booking_id = payment_intent['metadata'].get('booking_id')
        if booking_id:
            try:
                booking = Booking.objects.get(id=booking_id)
                payment, created = Payment.objects.get_or_create(
                    booking=booking,
                    session_id=booking.stripe_session_id,
                    defaults={
                        'payment_method': 'stripe',
                        'amount': Decimal(payment_intent['amount']) / 100,
                        'transaction_id': payment_intent['id'],
                        'payment_intent_id': payment_intent['id'],
                        'payment_status': 'completed'
                    }
                )
                if not created:
                    payment.payment_status = 'completed'
                    payment.payment_intent_id = payment_intent['id']
                    payment.transaction_id = payment_intent['id']
                    payment.amount = Decimal(payment_intent['amount']) / 100
                    payment.save()
                booking.status = 'confirmed'
                booking.payment_intent_id = payment_intent['id']
                booking.save()
                for passenger in booking.passengers.all():
                    ticket, created = Ticket.objects.get_or_create(
                        booking=booking,
                        passenger=passenger,
                        defaults={'ticket_status': 'active'}
                    )
                    if not created and ticket.ticket_status != 'active':
                        ticket.ticket_status = 'active'
                        ticket.save()
                        logger.info(f"Updated ticket {ticket.id} to active via webhook")
                    if created or not ticket.qr_code:
                        qr_data = request.build_absolute_uri(reverse('bookings:view_ticket', args=[ticket.qr_token]))
                        qr = qrcode.make(qr_data)
                        buffer = BytesIO()
                        qr.save(buffer, format='PNG')
                        ticket.qr_code.save(f"ticket_{ticket.id}.png", ContentFile(buffer.getvalue()))
                        logger.info(f"Generated QR code for ticket {ticket.id}")
                logger.info(f"Booking {booking_id} confirmed via payment_intent.succeeded webhook")
                email = (booking.user.email if booking.user else booking.guest_email)
                send_mail(
                    'Booking Confirmation',
                    f'Booking #{booking.id} confirmed. Thank you for your payment of {payment.amount} FJD.',
                    settings.DEFAULT_FROM_EMAIL,
                    [email],
                    fail_silently=True
                )
            except Booking.DoesNotExist:
                logger.error(f"Booking {booking_id} not found for payment_intent {payment_intent['id']}")
                return HttpResponse(status=404)
            except Payment.DoesNotExist:
                logger.error(f"Payment not found for booking {booking_id} with session_id {booking.stripe_session_id}")
                return HttpResponse(status=404)

    return HttpResponse(status=200)


@login_required
def modify_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    if booking.schedule.departure_time <= timezone.now() + timezone.timedelta(hours=6):
        messages.error(request, "Cannot modify bookings less than 6 hours before departure.")
        return redirect('bookings:booking_history')
    cargo_instance = Cargo.objects.filter(booking=booking).first()
    if request.method == 'POST':
        form = ModifyBookingForm(request.POST, instance=booking)
        cargo_form = CargoBookingForm(request.POST, instance=cargo_instance)
        if form.is_valid() and cargo_form.is_valid():
            old_total_price = booking.total_price
            old_total_passengers = booking.number_of_passengers
            new_adults = form.cleaned_data['passenger_adults']
            new_children = form.cleaned_data['passenger_children']
            new_infants = form.cleaned_data['passenger_infants']
            add_cargo = cargo_form.cleaned_data.get('cargo_type') and cargo_form.cleaned_data.get('weight_kg')
            new_total_price = calculate_total_price(
                new_adults, new_children, new_infants, booking.schedule,
                add_cargo, cargo_form.cleaned_data.get('cargo_type'), cargo_form.cleaned_data.get('weight_kg'),
                booking.is_emergency
            )
            price_difference = new_total_price - old_total_price
            booking.passenger_adults = new_adults
            booking.passenger_children = new_children
            booking.passenger_infants = new_infants
            booking.number_of_passengers = new_adults + new_children + new_infants
            booking.total_price = new_total_price
            booking.save()
            difference = booking.number_of_passengers - old_total_passengers
            if difference > 0 and booking.schedule.available_seats < difference:
                messages.error(request, "Not enough seats available for this modification.")
                return redirect('bookings:modify_booking', booking_id=booking.id)
            booking.schedule.available_seats -= difference
            booking.schedule.save()
            if cargo_form.has_changed():
                cargo = cargo_form.save(commit=False)
                cargo.booking = booking
                if cargo.weight_kg is None:
                    cargo.weight_kg = 0
                if cargo.dimensions_cm is None:
                    cargo.dimensions_cm = ''
                if not cargo.cargo_type:
                    cargo.cargo_type = 'parcel'
                cargo.price = calculate_cargo_price(cargo.weight_kg, cargo.cargo_type)
                cargo.save()
                generate_cargo_qr(request, cargo)
            else:
                if cargo_instance:
                    cargo_instance.delete()
            if price_difference > 0:
                messages.info(request, f"Please complete the additional payment of {price_difference} FJD.")
                request.session['price_difference'] = float(price_difference)
                request.session['booking_id'] = booking.id
                return redirect('bookings:process_payment', booking_id=booking.id)
            messages.success(request, f"Booking #{booking.id} updated successfully.")
            return redirect('bookings:booking_history')
    else:
        form = ModifyBookingForm(instance=booking)
        cargo_form = CargoBookingForm(instance=cargo_instance)
    return render(request, 'bookings/modify_booking.html', {
        'form': form,
        'cargo_form': cargo_form,
        'booking': booking
    })


@login_required
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    if booking.schedule.departure_time > timezone.now() + timezone.timedelta(hours=6):
        if booking.status != 'cancelled':
            booking.status = 'cancelled'
            Ticket.objects.filter(booking=booking).update(ticket_status='cancelled')
            booking.schedule.available_seats += booking.number_of_passengers
            booking.schedule.save()
            booking.save()
            messages.success(request, f"Booking #{booking.id} has been cancelled.")
        else:
            messages.info(request, f"Booking #{booking.id} was already cancelled.")
    else:
        messages.error(request, "Cannot cancel bookings less than 6 hours before departure.")
    return redirect('bookings:booking_history')
