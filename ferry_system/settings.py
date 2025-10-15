from pathlib import Path
from decouple import config
import os
from dotenv import load_dotenv
from celery.schedules import crontab

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Ensure logs directory exists
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

# Load environment variables
load_dotenv(os.path.join(BASE_DIR, '.env'))

# Security settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://localhost',
    'https://127.0.0.1',
]

# Base URL for success/cancel redirects
SITE_URL = config('SITE_URL', default='http://localhost:8000')

CELERY_BEAT_SCHEDULE = {
    'update-schedules-every-minute': {
        'task': 'bookings.tasks.update_schedules_status',
        'schedule': crontab(minute='*/5'),
    },
}

# Application definition
INSTALLED_APPS = [
    'channels',  # Required for WebSocket support
    'daphne',    # ASGI server for WebSocket
    'accounts.apps.AccountsConfig',
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'bookings.apps.BookingsConfig',
    'django_celery_beat',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'bookings.middleware.ScheduleUpdateMiddleware',
]

ROOT_URLCONF = 'ferry_system.urls'
ASGI_APPLICATION = 'ferry_system.asgi.application'
WSGI_APPLICATION = 'ferry_system.wsgi.application'

# Use Daphne as ASGI application for WebSocket support
# This replaces the default ASGI application
DEFAULT_ASGI_APPLICATION = ASGI_APPLICATION

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.media',
                'django.template.context_processors.i18n',
            ],
        },
    },
]

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME', default='fiji_ferry_db'),
        'USER': config('DB_USER', default='root'),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='3306'),
        'OPTIONS': {
            'sql_mode': 'traditional',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        'CONN_MAX_AGE': 600 if not DEBUG else 0,
        'POOL': {
            'MAX_OVERFLOW': 10,
            'POOL_SIZE': 5,
        } if not DEBUG else None,
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Pacific/Fiji'
USE_I18N = True
USE_TZ = True

# Static and media files
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage' if not DEBUG else 'django.contrib.staticfiles.storage.StaticFilesStorage'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
DEFAULT_FILE_STORAGE = 'django.core.files.storage.FileSystemStorage'

# Authentication
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'
AUTH_USER_MODEL = 'accounts.User'
AUTHENTICATION_BACKENDS = [
    'accounts.backends.EmailBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Email configuration
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL = config('EMAIL_HOST_USER', default='admin@fijiferry.com')
ADMIN_EMAIL = config('ADMIN_EMAIL', default='admin@fijiferry.com')

# Channel Layers Configuration
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [config("REDIS_WS_URL", default="redis://127.0.0.1:6379/0")],
            "symmetric_encryption_keys": [SECRET_KEY],
            "capacity": 1000,
            "expiry": 20,
            "channel_capacity": {
                "admin_dashboard": 1000,
                "jazzmin_admin": 500,
                "http.response": 1000,
                "booking_updates": 200,
                "weather_alerts": 100,
            },
        },
    },
}


# Redis Cache Configuration
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": config('REDIS_CACHE_URL', default='redis://127.0.0.1:6379/1'),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SOCKET_CONNECT_TIMEOUT": 5,
            "SOCKET_TIMEOUT": 5,
            "PARSER_CLASS": "redis.connection.HiredisParser",
            "SERIALIZER_CLASS": "django_redis.serializers.json.JSONSerializer",
            "CONNECTION_POOL_KWARGS": {
                "max_connections": 20,
            },
        },
        "KEY_PREFIX": "ferry",
        "TIMEOUT": config('CACHE_TIMEOUT', default=300, cast=int),
    }
}

# Celery Configuration
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 25 * 60
CELERY_WORKER_PREFETCH_MULTIPLIER = 1  # For real-time tasks

# Admin Enhancements Configuration - ENHANCED
ADMIN_ENHANCEMENTS_ENABLED = config('ADMIN_ENHANCEMENTS_ENABLED', default=True, cast=bool)
ADMIN_BACKGROUND_TASKS = config('ADMIN_BACKGROUND_TASKS', default=not DEBUG, cast=bool)
ADMIN_WEBSOCKET_ENABLED = config('ADMIN_WEBSOCKET_ENABLED', default=True, cast=bool)
ADMIN_WEBSOCKET_PING_INTERVAL = config('ADMIN_WS_PING_INTERVAL', default=30, cast=int)
ADMIN_WEBSOCKET_TIMEOUT = config('ADMIN_WS_TIMEOUT', default=20, cast=int)

ADMIN_ENHANCEMENTS = {
    'ENABLED': ADMIN_ENHANCEMENTS_ENABLED,
    'WEBSOCKET_GROUP': 'admin_dashboard',
    'JAZZMIN_GROUP': 'jazzmin_admin',
    'CACHE_TIMEOUT': 300,
    'ALERT_THRESHOLD': {
        'LOW_SEATS': config('ALERT_LOW_SEATS', default=5, cast=int),
        'HIGH_WIND': config('ALERT_HIGH_WIND', default=25, cast=float),
        'HIGH_PRECIP': config('ALERT_HIGH_PRECIP', default=70, cast=float),
    },
    'WEBSOCKET': {
        'ENABLED': ADMIN_WEBSOCKET_ENABLED,
        'PING_INTERVAL': ADMIN_WEBSOCKET_PING_INTERVAL,
        'TIMEOUT': ADMIN_WEBSOCKET_TIMEOUT,
        'RECONNECT_DELAY': 2000,
        'MAX_RETRIES': 5,
    }
}

# HTTPS configuration
SECURE_SSL_REDIRECT = False if DEBUG else True
SESSION_COOKIE_SECURE = False if DEBUG else True
CSRF_COOKIE_SECURE = False if DEBUG else True
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = False if DEBUG else True
SECURE_HSTS_PRELOAD = False

# Security Headers - ENHANCED
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'SAMEORIGIN'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'

# CORS configuration - ENHANCED FOR WEBSOCKETS
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://localhost',
    'https://127.0.0.1',
    'https://dq2rwn-ip-45-117-242-240.tunnelmole.net',
    'https://jlcnng-ip-45-117-242-240.tunnelmole.net',
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOWED_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
    'x-websocket-version',
]

# Session Configuration - ENHANCED
SESSION_ENGINE = 'django.contrib.sessions.backends.db'
SESSION_COOKIE_AGE = 1209600  # 2 weeks
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_SAMESITE = 'Lax' if DEBUG else 'Strict'
SESSION_COOKIE_HTTPONLY = True

# File Upload Settings
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5MB
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000

# Cache Timeouts - ENHANCED
CACHE_MIDDLEWARE_SECONDS = 300
CACHE_TIMEOUT_ANALYTICS = config('CACHE_ANALYTICS', default=300, cast=int)
CACHE_TIMEOUT_WEATHER = config('CACHE_WEATHER', default=1800, cast=int)
CACHE_TIMEOUT_WEBSOCKET = config('CACHE_WS', default=60, cast=int)

# Logging Configuration - ENHANCED FOR WEBSOCKETS
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module}:{funcName} {process:d} {thread:d} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
        'websocket': {
            'format': '[WS] {asctime} {levelname} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose' if DEBUG else 'simple',
            'level': 'DEBUG' if DEBUG else 'INFO',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(BASE_DIR / 'logs' / 'ferry_system.log'),
            'maxBytes': 1024*1024*5,  # 5MB
            'backupCount': 5,
            'formatter': 'verbose',
            'level': 'INFO',
        },
        'websocket_file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': str(BASE_DIR / 'logs' / 'websocket.log'),
            'maxBytes': 1024*1024*5,  # 5MB
            'backupCount': 3,
            'formatter': 'websocket',
            'level': 'INFO',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'bookings': {
            'handlers': ['console', 'file'] if not DEBUG else ['console'],
            'level': 'DEBUG' if DEBUG else 'INFO',
            'propagate': True,
        },
        'bookings.admin': {
            'handlers': ['console', 'file'] if not DEBUG else ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'bookings.consumers': {
            'handlers': ['console', 'websocket_file', 'file'] if not DEBUG else ['console', 'websocket_file'],
            'level': 'INFO',
            'propagate': False,
        },
        'channels': {
            'handlers': ['console', 'websocket_file'],
            'level': 'INFO',
            'propagate': True,
        },
        'channels.layers': {
            'handlers': ['console', 'websocket_file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'django.channels': {
            'handlers': ['console'],
            'level': 'WARNING',
            'propagate': True,
        },
        'django.security.DisallowedHost': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'daphne': {
            'handlers': ['console', 'websocket_file'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

APPEND_SLASH = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# =========================
# Jazzmin Admin Settings
# =========================
JAZZMIN_SETTINGS = {
    # Branding and Header
    "site_title": "Fiji Ferry Control Hub",  # Modernized title
    "site_header": "Ferry Control",  # Concise for header
    "site_brand": "Fiji Ferry",  # Consistent branding
    "welcome_sign": "Welcome to Fiji Ferry Control Hub",
    "copyright": "Fiji Ferry © 2025",
    "site_logo": "apple-touch-icon.png",  # Replace with your logo in static/images/
    "site_logo_classes": "img-circle img-thumbnail",  # Subtle border effect
    "site_icon": "apple-touch-icon.png",  # Replace with your favicon

    # Search Configuration (Disabled)
    "search_model": None,  # Disable global search bar

    # User Avatar
    "user_avatar": None,

    # Top Menu Links
    "topmenu_links": [
        {
            "name": "Dashboard",
            "url": "/admin/",
            "icon": "fas fa-anchor",
            "class": "btn btn-primary-custom topmenu-item",
            "permissions": ["auth.view_user"],
        },
        {
            "name": "Bookings",
            "url": "/admin/bookings/booking/",
            "icon": "fas fa-ticket-alt",
            "class": "btn btn-secondary-custom topmenu-item",
            "permissions": ["bookings.view_booking"],
        },
        {
            "name": "Schedules",
            "url": "/admin/bookings/schedule/",
            "icon": "fas fa-calendar-alt",
            "class": "btn btn-info-custom topmenu-item",
            "permissions": ["bookings.view_schedule"],
        },
        {
            "name": "Maintenance",
            "url": "/admin/bookings/maintenancelog/",
            "icon": "fas fa-tools",
            "class": "btn btn-success-custom topmenu-item",
            "permissions": ["bookings.view_maintenancelog"],
        },
        # Add real-time dashboard link
        {
            "name": "Real-time",
            "url": "/admin/realtime-data/",
            "icon": "fas fa-chart-line",
            "class": "btn btn-warning topmenu-item",
            "permissions": ["auth.view_user"],
            "new_window": False,
        },
    ],

    # Sidebar Configuration
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": [],

    # Model Icons
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.User": "fas fa-user",
        "accounts.User": "fas fa-user-tie",
        "bookings.Port": "fas fa-anchor",
        "bookings.Cargo": "fas fa-box",
        "bookings.Ferry": "fas fa-ship",
        "bookings.Route": "fas fa-route",
        "bookings.WeatherCondition": "fas fa-cloud-sun",
        "bookings.Schedule": "fas fa-calendar-alt",
        "bookings.Booking": "fas fa-ticket-alt",
        "bookings.Passenger": "fas fa-user-friends",
        "bookings.Vehicle": "fas fa-car",
        "bookings.AddOn": "fas fa-plus-circle",
        "bookings.Payment": "fas fa-credit-card",
        "bookings.Ticket": "fas fa-qrcode",
        "bookings.MaintenanceLog": "fas fa-tools",
        "bookings.ServicePattern": "fas fa-clock",
    },

    # Additional Settings
    "related_modal_active": True,
    "custom_css": "css/admin_custom.css",  # Points to updated CSS
    "custom_js": "js/admin_custom.js",  # Points to provided admin_custom.js
    "show_ui_builder": False,
    "changeform_format": "horizontal_tabs",
    "changeform_format_overrides": {
        "auth.user": "collapsible",
        "auth.group": "vertical_tabs",
    },
}

# =========================
# Jazzmin UI Tweaks
# =========================
JAZZMIN_UI_TWEAKS = {
    # Typography - Matches Inter font from CSS
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": False,
    "brand_small_text": False,

    # Color scheme - Uses CSS custom properties
    "brand_colour": False,  # Let CSS handle primary colors
    "accent": "accent-primary",
    "navbar": "navbar-dark",
    "no_navbar_border": False,
    "navbar_fixed": True,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": True,
    "sidebar": "sidebar-dark-primary",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,

    # Theme integration with CSS dark mode
    "theme": "default",

    # Button styling - Matches custom CSS classes
    "button_classes": {
        "primary": "btn btn-primary-custom",
        "secondary": "btn btn-secondary-custom",
        "info": "btn btn-info-custom",
        "warning": "btn btn-warning",
        "danger": "btn btn-danger",
        "success": "btn btn-success-custom"
    },

    # Form and list customization
    "actions_sticky_top": True,
    "related_modal_active": True,

    # Search and filters
    "show_search_buttons": False,
    "changeform_search": False,
    "changelist_search": True,

    # Responsive settings
    "responsive_page_breaks": True,
    "topmenu_show_above_mobile": True,
    "show_above_mobile": True,
}

# Stripe configuration
STRIPE_PUBLIC_KEY = config('STRIPE_PUBLIC_KEY', default='')
STRIPE_SECRET_KEY = config('STRIPE_SECRET_KEY', default='')
STRIPE_PUBLISHABLE_KEY = config('STRIPE_PUBLISHABLE_KEY', default='')
STRIPE_WEBHOOK_SECRET = config('STRIPE_WEBHOOK_SECRET', default='')

# Weather API Keys
WEATHER_API_KEY = config('WEATHER_API_KEY', default='083b420b5fbc4b248a810906252508')
OPENWEATHERMAP_API_KEY = config('OPENWEATHERMAP_API_KEY', default='2ed7bcece5c9d7a7498be98276d933a9')

# WebSocket specific environment variables
WS_REDIS_HOST = config('WS_REDIS_HOST', default='localhost')
WS_REDIS_PORT = config('WS_REDIS_PORT', default=6379, cast=int)
WS_REDIS_DB = config('WS_REDIS_DB', default=0, cast=int)