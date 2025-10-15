"""
ASGI config for ferry_system project.
"""

import os
import logging
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from django.conf import settings
import bookings.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ferry_system.settings')

logger = logging.getLogger(__name__)

# Initialize Django ASGI app
django_asgi_app = get_asgi_application()

# Combine all websocket routes directly
websocket_app = AuthMiddlewareStack(
    URLRouter(
        bookings.routing.websocket_urlpatterns  # ✅ include directly (no extra 'path' wrapping)
    )
)

# Apply production security if DEBUG=False
if not settings.DEBUG:
    application = ProtocolTypeRouter({
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(websocket_app),
    })
else:
    # Development mode (no origin restrictions)
    application = ProtocolTypeRouter({
        "http": django_asgi_app,
        "websocket": websocket_app,
    })


# Optional Logging Middleware (for dev debugging)
class ASGILoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        logger.debug(f"ASGI Scope: type={scope['type']}, path={scope.get('path', 'N/A')}")
        return await self.app(scope, receive, send)


if settings.DEBUG:
    application = ASGILoggingMiddleware(application)

__all__ = ["application"]
