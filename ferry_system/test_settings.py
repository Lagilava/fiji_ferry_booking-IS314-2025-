"""Settings for running the test suite locally.

The app's MySQL user (`ferry_app`) doesn't have CREATE DATABASE rights, so
Django can't build its throwaway test database against MySQL. Tests don't
need MySQL — swap in an in-memory SQLite database instead.

Usage:
    python manage.py test --settings=ferry_system.test_settings
"""
from .settings import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# No Redis on the test machine: middleware and views hit the cache on every
# request, so give them a local in-memory cache…
CACHES = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
}
SESSION_ENGINE = "django.contrib.sessions.backends.db"

# …and Schedule/booking saves broadcast live updates over Channels, so use
# the in-memory channel layer too.
CHANNEL_LAYERS = {
    "default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}
}

# Keep tests hermetic: no real emails, no upstream weather calls needed.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # speed
