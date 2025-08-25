from django import forms
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View

from bookings.models import Schedule, Booking
from .models import User


# -----------------------------
#  Registration
# -----------------------------
class CustomUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': ' '}),
            'email': forms.EmailInput(attrs={'placeholder': ' '}),
            'password1': forms.PasswordInput(attrs={'placeholder': ' '}),
            'password2': forms.PasswordInput(attrs={'placeholder': ' '}),
        }

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

            # ✅ Authenticate after creating user
            authenticated_user = authenticate(request, username=user.email, password=raw_password)

            if authenticated_user:
                login(request, authenticated_user)
                messages.success(request, 'Registration successful! You are now logged in.')
                next_url = request.GET.get('next') or request.POST.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect(self.success_url)

        messages.error(request, 'Registration failed. Please correct the errors below.')
        return render(request, self.template_name, {'form': form})


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

        # ✅ Single call, backend handles both username/email
        user = authenticate(request, username=identifier, password=password)

        if user is not None:
            login(request, user)
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
    return render(request, 'home.html', {'schedules': schedules})


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
