from django import forms
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login, update_session_auth_hash, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import PasswordResetView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.conf import settings

from bookings.models import Schedule, Booking
from .models import User
from .forms import ProfileUpdateForm, PasswordChangeForm


# -----------------------------
#  Registration
# -----------------------------
class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'password1', 'password2']
        widgets = {
            'first_name': forms.TextInput(attrs={'placeholder': ' '}),
            'last_name': forms.TextInput(attrs={'placeholder': ' '}),
            'username': forms.TextInput(attrs={'placeholder': ' '}),
            'email': forms.EmailInput(attrs={'placeholder': ' '}),
            'password1': forms.PasswordInput(attrs={'placeholder': ' '}),
            'password2': forms.PasswordInput(attrs={'placeholder': ' '}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # First/last name are optional on the model; encourage them at signup.
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True


class RegisterView(View):
    template_name = 'accounts/register.html'
    success_url = reverse_lazy('home')

    def get(self, request):
        form = CustomUserCreationForm()
        return render(request, self.template_name, {'form': form})

    def post(self, request):
        form = CustomUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            raw_password = form.cleaned_data.get('password1')

            # Send a welcome / account-confirmation email (best-effort).
            try:
                from bookings.notifications import send_welcome_email
                send_welcome_email(user)
            except Exception:
                pass

            # ✅ Robust auto-login after creating the user
            # First try the safest route: log in directly with a known backend.
            # (Django allows this right after signup.)
            try:
                backend_to_use = (
                    settings.AUTHENTICATION_BACKENDS[0]
                    if getattr(settings, 'AUTHENTICATION_BACKENDS', None)
                    else 'django.contrib.auth.backends.ModelBackend'
                )
                auth_login(request, user, backend=backend_to_use)
            except Exception:
                # Fallback: authenticate using the model's USERNAME_FIELD
                # so this works regardless of whether it's 'email' or 'username'.
                U = get_user_model()
                username_field = U.USERNAME_FIELD
                auth_kwargs = {username_field: getattr(user, username_field), 'password': raw_password}
                authenticated_user = authenticate(request, **auth_kwargs)
                if not authenticated_user:
                    messages.error(request, 'Registration succeeded but auto-login failed. Please log in.')
                    return redirect('accounts:login')
                auth_login(request, authenticated_user)

            messages.success(request, 'Registration successful! You are now logged in.')
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect(self.success_url)

        messages.error(request, 'Registration failed. Please correct the errors below.')
        return render(request, self.template_name, {'form': form})


# -----------------------------
#  Password reset (notifies admin that a client asked for help)
# -----------------------------
class NotifyingPasswordResetView(PasswordResetView):
    """Standard reset flow, plus an admin heads-up when a client requests one."""

    def form_valid(self, form):
        response = super().form_valid(form)  # sends the reset email to the user
        try:
            from bookings.notifications import send_admin_alert
            email = form.cleaned_data.get('email', '')
            U = get_user_model()
            exists = U.objects.filter(email__iexact=email).exists()
            send_admin_alert(
                "Password reset requested",
                f"A password reset was requested for: {email}\n"
                f"(matching account exists: {'yes' if exists else 'no'})\n\n"
                f"The reset link was emailed to the user automatically. No action needed "
                f"unless they contact you for help.",
                throttle_key=f"admin_alert:pwreset:{email.lower()}",
                throttle_seconds=600,
            )
        except Exception:
            pass
        return response


# -----------------------------
#  Login
# -----------------------------
class LoginView(View):
    template_name = 'accounts/login.html'
    success_url = reverse_lazy('home')

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        identifier = request.POST.get('identifier')
        password = request.POST.get('password')

        # ✅ Try authenticating in a way that works whether the user enters email or username,
        # and regardless of what USERNAME_FIELD is.
        user = authenticate(request, username=identifier, password=password)  # works for most backends

        if user is None:
            U = get_user_model()
            username_field = U.USERNAME_FIELD
            # Try again passing the model's username field explicitly (e.g., email)
            try:
                user = authenticate(request, **{username_field: identifier, 'password': password})
            except TypeError:
                # Some backends only accept 'username' kwarg; nothing more to do here.
                pass

        if user is not None:
            auth_login(request, user)
            messages.success(request, "Login successful! Welcome back 🌴")
            next_url = request.GET.get('next') or request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect(self.success_url)
        else:
            messages.error(request, "Invalid username/email or password.")
            return render(request, self.template_name)


# Homepage View
def homepage(request):
    now = timezone.now()
    schedules = Schedule.objects.filter(departure_time__gte=now).order_by('departure_time')
    # Note: your template expects 'bookings' — keeping that key to avoid breaking the page.
    return render(request, 'home.html', {'bookings': schedules})


# Booking History View
@login_required
def booking_history(request):
    bookings = Booking.objects.filter(user=request.user).order_by('-created_at')

    # Expire any bookings with pending payment past expiry
    for booking in bookings.filter(status='pending'):
        booking.expire_payment()

    cutoff_time = timezone.now() + timezone.timedelta(hours=1)  # Example cutoff time, adjust as needed

    return render(request, 'bookings/history.html', {
        'bookings': bookings,
        'cutoff_time': cutoff_time,
    })


# Booking Detail and Ticket View
@login_required
def booking_detail(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)

    # Expire payment if expired
    if booking.status == 'pending':
        booking.expire_payment()

    passengers = booking.passengers.all()

    return render(request, 'bookings/ticket.html', {
        'booking': booking,
        'passengers': passengers
    })


# View to re-attempt payment for pending bookings
@login_required
def pay_pending_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user, status='pending')

    if not booking.payment_is_valid():
        messages.error(request, 'Payment window expired. Please make a new booking.')
        return redirect('bookings:booking_history')

    # Redirect or display payment page / start Stripe session etc.
    # Customize this part based on your payment integration
    # Example:
    # return redirect('payments:start_checkout', booking_id=booking.id)

    return render(request, 'bookings/payment_retry.html', {'booking': booking})


# Cancel booking
@login_required
def cancel_booking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id, user=request.user)
    if booking.status != 'cancelled':
        booking.status = 'cancelled'
        booking.save()
        messages.success(request, f'Booking #{booking.id} has been cancelled.')
    return redirect('bookings:booking_history')


@login_required
def profile_settings(request):
    profile_form = ProfileUpdateForm(instance=request.user)
    password_form = PasswordChangeForm(user=request.user)
    active_tab = 'profile'

    if request.method == 'POST':
        form_type = request.POST.get('form_type')

        if form_type == 'profile':
            active_tab = 'profile'
            profile_form = ProfileUpdateForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, 'Profile updated successfully.')
                return redirect('accounts:profile')
            else:
                messages.error(request, 'Please correct the errors below.')

        elif form_type == 'password':
            active_tab = 'security'
            password_form = PasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, 'Password changed successfully.')
                return redirect('accounts:profile')
            else:
                messages.error(request, 'Please correct the errors below.')

    recent_bookings = (
        Booking.objects.filter(user=request.user)
        .select_related('schedule__route', 'schedule__ferry')
        .order_by('-booking_date')[:5]
    )
    total_bookings = Booking.objects.filter(user=request.user).count()
    confirmed_bookings = Booking.objects.filter(user=request.user, status='confirmed').count()

    return render(request, 'accounts/profile.html', {
        'profile_form': profile_form,
        'password_form': password_form,
        'active_tab': active_tab,
        'recent_bookings': recent_bookings,
        'total_bookings': total_bookings,
        'confirmed_bookings': confirmed_bookings,
    })
