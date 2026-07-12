from functools import wraps
from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse


def login_required_allow_anonymous(view_func):
    """Allow authenticated users, or guests who verified an email this session.

    Everyone else goes to the guest lookup page with ``?next=`` pointing back
    here. A stale-session visitor following a ticket link from an old email
    often has no account at all, so the login page would be a dead end for
    them; lookup verifies the booking email by OTP and links on to sign-in.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated and not request.session.get('guest_email'):
            messages.info(request, "Please confirm your email to view this page.")
            target = reverse('bookings:guest_lookup')
            return redirect(f"{target}?{urlencode({'next': request.get_full_path()})}")
        return view_func(request, *args, **kwargs)
    return wrapper
