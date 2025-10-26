# bookings/views_helpers.py
import hmac, hashlib, random, string, datetime
from django.conf import settings
from django.utils import timezone

def _otp_store_key(email: str) -> str:
    # binds OTP state to session by a keyed hash of the email (no PII as key)
    secret = getattr(settings, "SECRET_KEY", "fiji-ferry-secret")
    return "otp:" + hmac.new(secret.encode(), email.lower().encode(), hashlib.sha256).hexdigest()

def generate_otp_code() -> str:
    return "".join(random.choices(string.digits, k=6))

def otp_is_valid(session, email: str) -> bool:
    key = _otp_store_key(email)
    data = session.get(key)
    return bool(data and data.get("verified") is True)

def require_guest_otp(view_func):
    """Guests must have a verified OTP for the email they're using."""
    from functools import wraps
    from django.http import JsonResponse

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)

        email = (request.POST.get("guest_email") or request.POST.get("email") or "").strip().lower()
        if not email:
            return JsonResponse({"success": False, "errors":[{"field":"guest_email","message":"Guest email required"}]}, status=400)

        if not otp_is_valid(request.session, email):
            return JsonResponse({"success": False, "errors":[{"field":"guest_email","message":"Please verify your email before continuing."}]}, status=403)

        return view_func(request, *args, **kwargs)
    return _wrapped
