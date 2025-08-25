from functools import wraps
from django.http import HttpResponseForbidden

def login_required_allow_anonymous(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated and not request.session.get('guest_email'):
            return HttpResponseForbidden("Authentication required.")
        return view_func(request, *args, **kwargs)
    return wrapper