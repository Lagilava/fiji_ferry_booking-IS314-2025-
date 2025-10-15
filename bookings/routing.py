# bookings/routing.py - ENHANCED WITH CHANGELIST SUPPORT
from django.urls import re_path
from .consumers import AdminDashboardConsumer, AdminChangeListConsumer  # Added ChangeListConsumer

websocket_urlpatterns = [
    # Main admin dashboard WebSocket (single endpoint) - UNCHANGED
    re_path(r'ws/admin/dashboard/$', AdminDashboardConsumer.as_asgi()),

    # Model-specific endpoints (optional) - UNCHANGED
    re_path(r'ws/admin/tickets/$', AdminDashboardConsumer.as_asgi()),
    re_path(r'ws/admin/bookings/$', AdminDashboardConsumer.as_asgi()),
    re_path(r'ws/admin/schedules/$', AdminDashboardConsumer.as_asgi()),

    # NEW: Admin ChangeList WebSocket endpoints
    # Generic endpoint that accepts app_label and model as query params or path
    re_path(r'ws/admin/changelist/(?P<app_label>\w+)/(?P<model>\w+)/$', AdminChangeListConsumer.as_asgi()),

    # Fallback generic changelist endpoint (uses query params)
    re_path(r'ws/admin/changelist/$', AdminChangeListConsumer.as_asgi()),

    # Legacy compatibility (optional) - UNCHANGED
    re_path(r'ws/admin/legacy-dashboard/$', AdminDashboardConsumer.as_asgi()),
]


def get_websocket_urlpatterns():
    """Return WebSocket URL patterns for inclusion in main routing."""
    return websocket_urlpatterns