from django.db import models
from django.db.models import JSONField
from django.utils import timezone
from accounts.models import User
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
import uuid
from datetime import time, date
from django.db import transaction


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

    class Meta:
        indexes = [models.Index(fields=['name'])]

    def __str__(self):
        return self.name


class Ferry(models.Model):
    name = models.CharField(max_length=100, unique=True)
    operator = models.CharField(max_length=100, blank=True)
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    home_port = models.ForeignKey(
        'Port', on_delete=models.SET_NULL, null=True, blank=True, help_text="Ferry's home port"
    )
    cruise_speed_knots = models.FloatField(
        default=25.0, validators=[MinValueValidator(0.0)], help_text="Cruising speed in knots"
    )
    turnaround_minutes = models.PositiveIntegerField(
        default=480, help_text="Turnaround time in minutes"
    )
    max_daily_hours = models.FloatField(
        default=12.0, validators=[MinValueValidator(0.0)], help_text="Max operating hours per day"
    )
    overnight_allowed = models.BooleanField(default=False, help_text="Allows overnight trips")

    class Meta:
        indexes = [models.Index(fields=['name', 'is_active'])]

    def __str__(self):
        return self.name


class Route(models.Model):
    departure_port = models.ForeignKey(
        'Port', on_delete=models.CASCADE, related_name='departures'
    )
    destination_port = models.ForeignKey(
        'Port', on_delete=models.CASCADE, related_name='arrivals'
    )
    distance_km = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    estimated_duration = models.DurationField(default='00:00:00')
    base_fare = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    service_tier = models.CharField(
        max_length=20,
        choices=[('major', 'Major'), ('regional', 'Regional'), ('remote', 'Remote')],
        default='regional',
        help_text="Route service tier for scheduling frequency"
    )
    min_weekly_services = models.PositiveIntegerField(
        default=7, help_text="Minimum weekly services"
    )
    preferred_departure_windows = JSONField(
        default=list, help_text="Preferred departure time windows (e.g., ['06:00-08:00', '12:00-14:00'])"
    )
    safety_buffer_minutes = models.PositiveIntegerField(
        default=15, help_text="Safety buffer in minutes for ETA"
    )
    waypoints = JSONField(
        default=list, help_text="Optional water waypoints for maritime route"
    )

    class Meta:
        unique_together = ['departure_port', 'destination_port']
        indexes = [models.Index(fields=['departure_port', 'destination_port'])]

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
    port = models.ForeignKey('Port', on_delete=models.CASCADE, related_name='weather_conditions')
    route = models.ForeignKey('Route', on_delete=models.CASCADE, related_name='weather_conditions')
    temperature = models.FloatField(null=True, blank=True)
    wind_speed = models.FloatField(null=True, blank=True)
    wave_height = models.FloatField(null=True, blank=True)
    condition = models.CharField(max_length=100, null=True, blank=True)
    precipitation_probability = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=['route', 'port', 'expires_at'])]

    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        return f"Weather for {self.port.name} - {self.route}"


class Schedule(models.Model):
    ferry = models.ForeignKey('Ferry', on_delete=models.CASCADE)
    route = models.ForeignKey('Route', on_delete=models.CASCADE, related_name='schedules')
    departure_time = models.DateTimeField()
    arrival_time = models.DateTimeField()
    estimated_duration = models.CharField(
        max_length=50, blank=True, help_text="Estimated travel duration (e.g., '12 hours')"
    )
    available_seats = models.PositiveIntegerField(validators=[MinValueValidator(0)])
    status = models.CharField(
        max_length=20,
        choices=[('scheduled', 'Scheduled'), ('cancelled', 'Cancelled'), ('delayed', 'Delayed')],
        default='scheduled'
    )
    last_updated = models.DateTimeField(auto_now=True)
    operational_day = models.DateField(db_index=True, help_text="Date of operation")
    notes = models.TextField(blank=True, null=True, help_text="Additional notes")
    created_by_auto = models.BooleanField(default=False, help_text="Created by auto-scheduler")

    class Meta:
        indexes = [
            models.Index(fields=['departure_time', 'status']),
            models.Index(fields=['operational_day'])
        ]

    def __str__(self):
        return f"{self.ferry.name} - {self.route} at {self.departure_time}"


class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    guest_email = models.EmailField(null=True, blank=True)
    schedule = models.ForeignKey('Schedule', on_delete=models.CASCADE)
    booking_date = models.DateTimeField(auto_now_add=True)
    passenger_adults = models.PositiveIntegerField(validators=[MinValueValidator(0)])
    passenger_children = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    passenger_infants = models.PositiveIntegerField(default=0, validators=[MinValueValidator(0)])
    total_price = models.DecimalField(max_digits=10, decimal_places=2)
    payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_session_id = models.CharField(
        max_length=100, unique=True, null=True, blank=True, help_text="Stripe Checkout Session ID"
    )
    status = models.CharField(
        max_length=20,
        choices=[('confirmed', 'Confirmed'), ('cancelled', 'Cancelled'), ('pending', 'Pending')],
        default='pending'
    )
    is_unaccompanied_minor = models.BooleanField(
        default=False, help_text="Booking includes unaccompanied minors"
    )
    is_group_booking = models.BooleanField(default=False, help_text="Booking is for a group")
    is_emergency = models.BooleanField(default=False, help_text="Booking is for emergency travel")
    group_leader = models.ForeignKey(
        'Passenger',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='led_bookings',
        help_text="Designated group leader"
    )

    class Meta:
        indexes = [
            models.Index(fields=['user', 'booking_date']),
            models.Index(fields=['guest_email', 'booking_date']),
            models.Index(fields=['status'])
        ]

    def __str__(self):
        return f"Booking {self.id} by {self.user.email if self.user else self.guest_email or 'Guest'}"

    def clean(self):
        """Validate booking constraints."""
        total_passengers = self.passenger_adults + self.passenger_children + self.passenger_infants
        if total_passengers == 0:
            raise ValidationError("At least one passenger is required.")
        if (
            self.passenger_children + self.passenger_infants > 0
            and self.passenger_adults == 0
            and not self.is_unaccompanied_minor
        ):
            raise ValidationError(
                "Children or infants require at least one accompanying adult unless marked as unaccompanied minor."
            )
        if self.is_group_booking and not self.group_leader:
            raise ValidationError("Group bookings must have a designated group leader.")
        if self.group_leader and (
            not self.passengers.filter(id=self.group_leader.id, passenger_type='adult').exists()
        ):
            raise ValidationError("Group leader must be an adult passenger in this booking.")

    def reserve_seats(self):
        """Atomically reserve seats for the booking."""
        total_passengers = self.passenger_adults + self.passenger_children + self.passenger_infants
        with transaction.atomic():
            schedule = Schedule.objects.select_for_update().get(id=self.schedule.id)
            if schedule.available_seats < total_passengers:
                raise ValidationError(
                    f"Not enough seats available ({schedule.available_seats} remaining)."
                )
            schedule.available_seats -= total_passengers
            schedule.save()
            self.save()

    def update_status_if_expired(self):
        """Update booking status to cancelled if schedule has departed."""
        if self.status != 'cancelled' and self.schedule.departure_time < timezone.now():
            self.status = 'cancelled'
            self.save()

    @property
    def evaluated_status(self):
        """Return evaluated status based on schedule departure time."""
        if self.status != 'cancelled' and self.schedule.departure_time < timezone.now():
            return 'cancelled'
        return self.status


class Passenger(models.Model):
    PASSENGER_TYPE_CHOICES = [
        ('adult', 'Adult'),
        ('child', 'Child'),
        ('infant', 'Infant'),
    ]
    VERIFICATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ]

    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='passengers')
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    age = models.PositiveIntegerField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True, help_text="Required for infants")
    passenger_type = models.CharField(max_length=20, choices=PASSENGER_TYPE_CHOICES)
    document = models.FileField(
        upload_to='passenger_documents/%Y/%m/%d/',
        validators=[FileExtensionValidator(allowed_extensions=['pdf', 'jpg', 'jpeg', 'png'])],
        null=True,
        blank=True,
        help_text="Required for adults and children; not applicable for infants."
    )
    linked_adult = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='dependents',
        help_text="Adult responsible for child/infant, if applicable"
    )
    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='pending',
        help_text="Status of document verification"
    )
    is_group_leader = models.BooleanField(default=False, help_text="Is this passenger the group leader?")

    class Meta:
        verbose_name = "Passenger"
        verbose_name_plural = "Passengers"
        indexes = [models.Index(fields=['booking', 'passenger_type'])]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.passenger_type})"

    def clean(self):
        """Validate passenger data based on type."""
        if self.passenger_type == 'infant' and not self.date_of_birth:
            raise ValidationError("Date of birth is required for infants.")
        if self.passenger_type == 'adult' and (not self.age or self.age < 18):
            raise ValidationError("Adults must be 18 or older.")
        if self.passenger_type == 'child' and (not self.age or self.age < 2 or self.age >= 18):
            raise ValidationError("Children must be between 2 and 17 years old.")
        if self.passenger_type == 'infant' and self.date_of_birth:
            today = date.today()
            age_days = (today - self.date_of_birth).days
            if age_days > 730:
                raise ValidationError("Infants must be under 2 years old.")
        if self.linked_adult and self.linked_adult.passenger_type != 'adult':
            raise ValidationError("Linked adult must be an adult passenger.")
        if self.is_group_leader and self.passenger_type != 'adult':
            raise ValidationError("Group leader must be an adult.")
        if self.passenger_type in ['adult', 'child'] and not self.document:
            raise ValidationError("Document is required for adults and children.")
        if self.passenger_type == 'infant' and self.document:
            raise ValidationError("Documents are not allowed for infants.")


class Vehicle(models.Model):
    VEHICLE_TYPE_CHOICES = [
        ('car', 'Car'),
        ('motorcycle', 'Motorcycle'),
        ('bicycle', 'Bicycle'),
    ]

    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='vehicles')
    vehicle_type = models.CharField(max_length=20, choices=VEHICLE_TYPE_CHOICES)
    dimensions = models.CharField(max_length=50, help_text="Vehicle dimensions in cm (e.g., 480x180x150)")
    license_plate = models.CharField(max_length=20, blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        indexes = [models.Index(fields=['booking'])]

    def __str__(self):
        return f"{self.vehicle_type} ({self.license_plate or 'N/A'})"


class Cargo(models.Model):
    CARGO_TYPE_CHOICES = [
        ('general', 'General'),
        ('hazardous', 'Hazardous'),
        ('perishable', 'Perishable'),
        ('vehicle', 'Vehicle'),
    ]

    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='cargo')
    cargo_type = models.CharField(max_length=100, choices=CARGO_TYPE_CHOICES, help_text="Type of cargo")
    weight_kg = models.DecimalField(
        max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)]
    )
    dimensions_cm = models.CharField(max_length=100, blank=True, null=True, help_text="e.g., 400x180x150")
    license_plate = models.CharField(
        max_length=20, blank=True, null=True, help_text="Optional license plate for vehicles"
    )
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        indexes = [models.Index(fields=['booking'])]

    def __str__(self):
        return f"{self.cargo_type} ({self.weight_kg}kg)"


class AddOn(models.Model):
    ADD_ON_TYPE_CHOICES = [
        ('premium_seating', 'Premium Seating'),
        ('priority_boarding', 'Priority Boarding'),
        ('cabin', 'Cabin'),
        ('meal_breakfast', 'Meal - Breakfast'),
        ('meal_lunch', 'Meal - Lunch'),
        ('meal_dinner', 'Meal - Dinner'),
        ('meal_snack', 'Meal - Snack'),
    ]

    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='add_ons')
    add_on_type = models.CharField(max_length=50, choices=ADD_ON_TYPE_CHOICES)
    description = models.TextField(blank=True, help_text="Description of the add-on")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    price = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True, help_text="Is this add-on currently available?")

    class Meta:
        indexes = [models.Index(fields=['booking', 'add_on_type'])]

    def __str__(self):
        return f"{self.get_add_on_type_display()} (x{self.quantity}) for Booking {self.booking.id}"


class Payment(models.Model):
    booking = models.ForeignKey('Booking', on_delete=models.CASCADE, related_name='payments')
    payment_method = models.CharField(
        max_length=20, choices=[('stripe', 'Stripe'), ('paypal', 'PayPal'), ('local', 'Local')]
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    transaction_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    session_id = models.CharField(
        max_length=100, unique=True, null=True, blank=True, help_text="Stripe Checkout Session ID"
    )
    payment_intent_id = models.CharField(
        max_length=255, null=True, blank=True, help_text="Stripe PaymentIntent ID"
    )
    payment_status = models.CharField(
        max_length=20,
        choices=[('completed', 'Completed'), ('failed', 'Failed'), ('pending', 'Pending'), ('refunded', 'Refunded')],
        default='pending'
    )
    payment_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['booking', 'payment_status'])]

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

    class Meta:
        indexes = [models.Index(fields=['booking', 'qr_token'])]

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
    completed_at = models.DateTimeField(null=True, blank=True, help_text="Set when maintenance is completed")
    maintenance_interval_days = models.PositiveIntegerField(
        default=14, help_text="Custom maintenance interval in days"
    )

    class Meta:
        indexes = [models.Index(fields=['ferry', 'maintenance_date'])]

    def __str__(self):
        return f"Maintenance for {self.ferry.name} on {self.maintenance_date}"


class ServicePattern(models.Model):
    route = models.ForeignKey('Route', on_delete=models.CASCADE)
    weekday = models.PositiveIntegerField(
        choices=[
            (1, 'Sunday'),
            (2, 'Monday'),
            (3, 'Tuesday'),
            (4, 'Wednesday'),
            (5, 'Thursday'),
            (6, 'Friday'),
            (7, 'Saturday'),
        ],
        help_text="Day of the week (aligned with ExtractWeekDay)"
    )
    window = models.CharField(max_length=20, help_text="Time window (e.g., '06:00-08:00')")
    target_departures = models.PositiveIntegerField(
        default=1, help_text="Target number of departures"
    )

    class Meta:
        indexes = [models.Index(fields=['route', 'weekday'])]

    def __str__(self):
        return f"{self.route} - {self.get_weekday_display()} - {self.window}"