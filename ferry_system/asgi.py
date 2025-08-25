import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.http import AsgiHandler
import bookings.routing

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ferry_system.settings')
application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': URLRouter(bookings.routing.websocket_urlpatterns)
})