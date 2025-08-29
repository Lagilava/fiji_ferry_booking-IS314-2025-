from django.db import models
from django.db.models import JSONField
from django.utils import timezone
from accounts.models import User
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
import uuid

from datetime import time

class Port(models.Model):
    name = models.CharField(max_length=100, unique=True)
    lat = models.FloatField(
        validators=[MinValueValidator(-21.0), MaxValueValidator(-16.0)],
        help_text="Latitude of port (Fiji: -21 to -16)"
    )
    lng = models.FloatField(
        validators=[MinValueValidator(176.0), MaxValueValidator(181.0)],
        help_text="Longitude of port (Fiji: 176 to 181)"
    )
    operating_hours_start = models.TimeField(default=time(6, 0), help_text="Port opening time")
    operating_hours_end = models.TimeField(default=time(20, 0), help_text="Port closing time")
    berths = models.PositiveIntegerField(default=2, help_text="Number of simultaneous berths")
    tide_sensitive = models.BooleanField(default=False, help_text="Port has reef/tide constraints")
    night_ops_allowed = models.BooleanField(default=False, help_text="Allows night operations")

    def __str__(self):
        return self.name

class Ferry(models.Model):
    name = models.CharField(max_length=100)
    operator = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    home_port = models.ForeignKey('Port', on_delete=models.SET_NULL, null=True, blank=True, help_text="Ferry's home port")
    cruise_speed_knots = models.FloatField(default=25.0, help_text="Cruising speed in knots")
    turnaround_minutes = models.PositiveIntegerField(default=480, help_text="Turnaround time in minutes")
    max_daily_hours = models.FloatField(default=12.0, help_text="Max operating hours per day")
    overnight_allowed = models.BooleanField(default=False, help_text="Allows overnight trips")

    def __str__(self):
        return self.name

class Route(models.Model):
    departure_port = models.ForeignKey('Port', on_delete=models.CASCADE, related_name='departures')
    destination_port = models.ForeignKey('Port', on_delete=models.CASCADE, related_name='arrivals')
    distance_km = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    estimated_duration = models.DurationField(null=True)
    base_fare = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    service_tier = models.CharField(
        max_length=20,
        choices=[('major', 'Major'), ('regional', 'Regional'), ('remote', 'Remote')],
        default='regional',
        help_text="Route service tier for scheduling frequency"
    )
    min_weekly_services = models.PositiveIntegerField(default=7, help_text="Minimum weekly services")
    preferred_departure_windows = JSONField(
        default=list,
        help_text="Preferred departure time windows (e.g., ['06:00-08:00', '12:00-14:00'])"
    )
    safety_buffer_minutes = models.PositiveIntegerField(default=15, help_text="Safety buffer in minutes for ETA")
    waypoints = JSONField(default=list, help_text="Optional water waypoints for maritime route")

    def __str__(self):
        return f"{self.departure_port} to {self.destination_port}"

    @property
    def departure_lat(self):
        return self.departure_port.lat

    @property
    def departure_lng(self):
        return self.departure_port.lng

    @property
    def destination_lat(self):
        return self.destination_port.lat

    @property
    def destination_lng(self):
        return self.destination_port.lng

class WeatherCondition(models.Model):
    route = models.ForeignKey('Route', on_delete=models.CASCADE)
    port = models.ForeignKey('Port', on_delete=models.CASCADE)
    temperature = models.FloatField(null=True)
    wind_speed = models.FloatField(null=True)
    wave_height = models.FloatField(null=True)
    condition = models.CharField(max_length=100, null=True)
    precipitation_probability = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"Weather for {self.port.name} - {self.route}"

class Schedule(models.Model):
    ferry = models.ForeignKey('Ferry', on_delete=models.CASCADE)
    route = models.ForeignKey('Route', on_delete=models.CASCADE, related_name='schedules')
    departure_time = models.DateTimeField()
    arrival_time = models.DateTimeField()
    available_seats = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=[('scheduled', 'Scheduled'), ('cancelled', 'Cancelled'), ('delayed', 'Delayed')],
        default='scheduled'
    )
    last_updated = models.DateTimeField(auto_now=True)
    operational_day = models.DateField(db_index=True, help_text="Date of operation")
    notes = models.TextField(blank=True, null=True, help_text="Additional notes")
    created_by_auto = models.BooleanField(default=False, help_text="Created by auto-scheduler")

    def __str__(self):
        return f"{self.ferry.name} - {self.route} at {self.departure_time}"

class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    guest_email = models.EmailField(null=True, blank=True)
    schedule = models.ForeignKey('Schedule', on_delete=models.CASCADE)
    booking_date = models.DateTimeField(auto_now_add=True)
    number_of_passengers = models.PositiveIntegerField()
    passenger_adults = models.PositiveIntegerField()
    passenger_children = models.PositiveIntegerField(default=0)
    passenger_infants = models.PositiveIntegerField(default=0)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_session_id = models.CharField(max_length=100, unique=True, null=True, blank=True, help_text="Stripe Checkout Session ID")
    status = models.CharField(
        max_length=20,
        choices=[('confirmed', 'Confirmed'), ('cancelled', 'Cancelled'), ('pending', 'Pending'), ('emergency', 'Emergency')],
        default='pending'
    )
    is_group_booking = models.BooleanField(default=False)
    group_leader = models.ForeignKey('Passenger', on_delete=models.SET_NULL, null=True, blank=True, related_name='led_bookings')
    is_unaccompanied_minor = models.BooleanField(default=False)
    guardian_contact = models.CharField(max_length=100, blank=True)
    consent_form = models.FileField(
        upload_to='consent_forms/%Y/%m/%d/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])],
        blank=True,
        null=True
    )
    responsibility_declaration = models.FileField(
        upload_to='responsibility_declarations/%Y/%m/%d/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])],
        blank=True,
        null=True,
        help_text="Upload a responsibility declaration for non-parent adults traveling with minors."
    )
    is_emergency = models.BooleanField(default=False)

    def __str__(self):
        return f"Booking {self.id} by {self.user.email if self.user else self.guest_email or 'Guest'}"

    @property
    def evaluated_status(self):
        if self.status not in ['cancelled', 'emergency'] and self.schedule.departure_time < timezone.now():
            return 'cancelled'
        return self.status

    def update_status_if_expired(self):
        if self.status not in ['cancelled', 'emergency'] and self.schedule.departure_time < timezone.now():
            self.status = 'cancelled'
            self.save()

class Cargo(models.Model):
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE)
    cargo_type = models.CharField(max_length=100)
    weight_kg = models.DecimalField(max_digits=10, decimal_places=2)
    dimensions_cm = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    qr_code = models.ImageField(upload_to='cargo_qrcodes/', blank=True, null=True)

    def __str__(self):
        return f"{self.cargo_type} ({self.weight_kg}kg)"

class Passenger(models.Model):
    PASSENGER_TYPE_CHOICES = [
        ('adult', 'Adult'),
        ('child', 'Child'),
        ('infant', 'Infant'),
    ]
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('missing', 'Missing'),
        ('temporary', 'Temporary')
    ]

    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='passengers')
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    age = models.PositiveIntegerField()
    passenger_type = models.CharField(max_length=20, choices=PASSENGER_TYPE_CHOICES)
    document = models.FileField(
        upload_to='passenger_documents/%Y/%m/%d/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])],
        null=True,
        blank=True,
        help_text="Upload a birth certificate or scanned ID (PDF, JPG, or PNG)."
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='missing'
    )
    linked_adult = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='dependents')
    is_group_leader = models.BooleanField(default=False)
    is_parent_guardian = models.BooleanField(default=False, help_text="Indicates if the passenger is a parent or guardian of a minor.")

    class Meta:
        verbose_name = "Passenger"
        verbose_name_plural = "Passengers"

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.passenger_type})"

    def is_verified(self):
        return self.verification_status in ['verified', 'temporary']

    def has_document(self):
        return bool(self.document)

class DocumentVerification(models.Model):
    passenger = models.ForeignKey('Passenger', on_delete=models.CASCADE, related_name='verifications')
    document = models.FileField(
        upload_to='verifications/%Y/%m/%d/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])],
        null=True,
        blank=True
    )
    verification_status = models.CharField(
        max_length=20,
        choices=[('pending', 'Pending'), ('verified', 'Verified'), ('rejected', 'Rejected')],
        default='pending'
    )
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Verification for {self.passenger}"

class Payment(models.Model):
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='payments')
    payment_method = models.CharField(
        max_length=20,
        choices=[('stripe', 'Stripe'), ('paypal', 'PayPal'), ('local', 'Local')]
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    session_id = models.CharField(max_length=100, unique=True, null=True, blank=True, help_text="Stripe Checkout Session ID")
    payment_intent_id = models.CharField(max_length=255, null=True, blank=True, help_text="Stripe PaymentIntent ID")
    payment_status = models.CharField(
        max_length=20,
        choices=[('completed', 'Completed'), ('failed', 'Failed'), ('pending', 'Pending')],
        default='pending'
    )
    payment_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment {self.transaction_id or 'N/A'} for Booking {self.booking.id}"

class Ticket(models.Model):
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='tickets')
    passenger = models.ForeignKey('Passenger', on_delete=models.CASCADE)
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, null=True)
    ticket_status = models.CharField(
        max_length=20,
        choices=[('active', 'Active'), ('used', 'Used'), ('cancelled', 'Cancelled')],
        default='active'
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    qr_token = models.CharField(max_length=255, unique=True, editable=False, blank=True)

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Ticket for {self.passenger} (Booking {self.booking.id})"

class MaintenanceLog(models.Model):
    ferry = models.ForeignKey('Ferry', on_delete=models.CASCADE, related_name='maintenance_logs')
    maintenance_date = models.DateField()
    notes = models.TextField(blank=True)
    completed_at = models.DateTimeField(auto_now_add=True)
    maintenance_interval_days = models.PositiveIntegerField(default=14, help_text="Custom maintenance interval in days")

    def __str__(self):
        return f"Maintenance for {self.ferry.name} on {self.maintenance_date}"

class ServicePattern(models.Model):
    route = models.ForeignKey('Route', on_delete=models.CASCADE)
    weekday = models.PositiveIntegerField(
        choices=[
            (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), (3, 'Thursday'),
            (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday')
        ],
        help_text="Day of the week"
    )
    window = models.CharField(max_length=20, help_text="Time window (e.g., '06:00-08:00')")
    target_departures = models.PositiveIntegerField(default=1, help_text="Target number of departures")

    def __str__(self):
        return f"{self.route} - {self.get_weekday_display()} - {self.window}"