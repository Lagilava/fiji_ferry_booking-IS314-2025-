from django.db import models
from django.utils import timezone
from accounts.models import User
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
import uuid


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

    def __str__(self):
        return self.name


class Ferry(models.Model):
    name = models.CharField(max_length=100)
    operator = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField()
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Route(models.Model):
    departure_port = models.ForeignKey(Port, on_delete=models.CASCADE, related_name='departures')
    destination_port = models.ForeignKey(Port, on_delete=models.CASCADE, related_name='arrivals')
    distance_km = models.DecimalField(max_digits=10, decimal_places=2, null=True)
    estimated_duration = models.DurationField(null=True)
    base_fare = models.DecimalField(max_digits=10, decimal_places=2, null=True)

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
    route = models.ForeignKey(Route, on_delete=models.CASCADE)
    port = models.ForeignKey(Port, on_delete=models.CASCADE)
    temperature = models.FloatField(null=True)
    wind_speed = models.FloatField(null=True)
    wave_height = models.FloatField(null=True)
    condition = models.CharField(max_length=100, null=True)
    precipitation_probability = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    def is_expired(self):
        return timezone.now() > self.expires_at


class Schedule(models.Model):
    ferry = models.ForeignKey(Ferry, on_delete=models.CASCADE)
    route = models.ForeignKey(Route, on_delete=models.CASCADE)
    departure_time = models.DateTimeField()
    arrival_time = models.DateTimeField()
    available_seats = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=[
        ('scheduled', 'Scheduled'),
        ('cancelled', 'Cancelled'),
        ('delayed', 'Delayed')
    ], default='scheduled')
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.ferry.name} - {self.route} at {self.departure_time}"


class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    guest_email = models.EmailField(null=True, blank=True)
    schedule = models.ForeignKey(Schedule, on_delete=models.CASCADE)
    booking_date = models.DateTimeField(auto_now_add=True)
    number_of_passengers = models.PositiveIntegerField()
    passenger_adults = models.PositiveIntegerField()
    passenger_children = models.PositiveIntegerField(default=0)
    passenger_infants = models.PositiveIntegerField(default=0)
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_session_id = models.CharField(max_length=100, unique=True, null=True, blank=True, help_text="Stripe Checkout Session ID")
    status = models.CharField(max_length=20, choices=[
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('pending', 'Pending'),
        ('emergency', 'Emergency')
    ], default='pending')
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
    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE, related_name='verifications')
    document = models.FileField(
        upload_to='verifications/%Y/%m/%d/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])],
        null=True,
        blank=True
    )
    verification_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('verified', 'Verified'),
            ('rejected', 'Rejected')
        ],
        default='pending'
    )
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Verification for {self.passenger}"


class Payment(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='payments')
    payment_method = models.CharField(max_length=20, choices=[
        ('stripe', 'Stripe'),
        ('paypal', 'PayPal'),
        ('local', 'Local')
    ])
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    session_id = models.CharField(max_length=100, unique=True, null=True, blank=True, help_text="Stripe Checkout Session ID")
    payment_intent_id = models.CharField(max_length=255, null=True, blank=True, help_text="Stripe PaymentIntent ID")
    payment_status = models.CharField(max_length=20, choices=[
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('pending', 'Pending')
    ], default='pending')
    payment_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payment {self.transaction_id or 'N/A'} for Booking {self.booking.id}"


class Ticket(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='tickets')
    passenger = models.ForeignKey(Passenger, on_delete=models.CASCADE)
    qr_code = models.ImageField(upload_to='qr_codes/', blank=True, null=True)
    ticket_status = models.CharField(max_length=20, choices=[
        ('active', 'Active'),
        ('used', 'Used'),
        ('cancelled', 'Cancelled')
    ], default='active')
    issued_at = models.DateTimeField(auto_now_add=True)
    qr_token = models.CharField(max_length=255, unique=True, editable=False, blank=True)

    def save(self, *args, **kwargs):
        if not self.qr_token:
            self.qr_token = uuid.uuid4().hex
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Ticket for {self.passenger} (Booking {self.booking.id})"

