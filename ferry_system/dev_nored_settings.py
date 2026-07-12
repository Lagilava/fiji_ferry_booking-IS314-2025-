"""Local dev settings for running the site when Redis isn't running.

Same real MySQL database, but cache and channel layer are swapped for
in-memory backends so pages render without a Redis server.

Usage:
    python manage.py runserver --settings=ferry_system.dev_nored_settings
"""
from .settings import *  # noqa: F401,F403

CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}
SESSION_ENGINE = "django.contrib.sessions.backends.db"
