from pathlib import Path
from decouple import config
import os
from dotenv import load_dotenv
from celery.schedules import crontab

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

# Load environment variables
load_dotenv(os.path.join(BASE_DIR, '.env'))

# Security settings
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-me-in-production')  # Update in .env for production
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']  # Restrict to specific domains in production
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'https://localhost',
    'https://127.0.0.1',
]  # Restrict to specific origins in production

# Base URL for success/cancel redirects
SITE_URL = config('SITE_URL', default='http://localhost:8000')

CELERY_BEAT_SCHEDULE = {
    'update-schedules-every-minute': {
        'task': 'bookings.tasks.update_schedules_status',
        'schedule': crontab(minute='*/5'),  # Adjusted to every 5 minutes to reduce load
    },
}

# Application definition
INSTALLED_APPS = [
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
WSGI_APPLICATION = 'ferry_system.wsgi.application'

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
            ],
        },
    },
]

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': config('DB_NAME', default='fiji_ferry_db'),
        'USER': config('DB_USER', default='root'),  # Update in .env for production
        'PASSWORD': config('DB_PASSWORD', default=''),  # Update in .env for production
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='3306'),
        'OPTIONS': {'sql_mode': 'traditional'},
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
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.ManifestStaticFilesStorage'
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
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')  # Update in .env
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')  # Update in .env
DEFAULT_FROM_EMAIL = config('EMAIL_HOST_USER', default='admin@fijiferry.com')
ADMIN_EMAIL = config('ADMIN_EMAIL', default='admin@fijiferry.com')

# HTTPS configuration
SECURE_SSL_REDIRECT = False if DEBUG else True
SESSION_COOKIE_SECURE = False if DEBUG else True
CSRF_COOKIE_SECURE = False if DEBUG else True
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = False if DEBUG else True
SECURE_HSTS_PRELOAD = False  # Only enable if submitted to HSTS preload list

# Stripe configuration
STRIPE_PUBLIC_KEY = config('STRIPE_PUBLIC_KEY', default='')
STRIPE_SECRET_KEY = config('STRIPE_SECRET_KEY', default='')
STRIPE_PUBLISHABLE_KEY = config('STRIPE_PUBLISHABLE_KEY', default='')
STRIPE_WEBHOOK_SECRET = config('STRIPE_WEBHOOK_SECRET', default='')
WEATHER_API_KEY = '083b420b5fbc4b248a810906252508'
OPENWEATHERMAP_API_KEY = '2ed7bcece5c9d7a7498be98276d933a9'

# CORS configuration
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'https://dq2rwn-ip-45-117-242-240.tunnelmole.net',
    'https://jlcnng-ip-45-117-242-240.tunnelmole.net',
]

# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {'bookings': {'level': 'INFO', 'handlers': ['console']}},
}

APPEND_SLASH = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
DATA_UPLOAD_MAX_NUMBER_FIELDS = 2000

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'

# =========================
# Jazzmin Admin Settings
# =========================
JAZZMIN_SETTINGS = {
    "site_title": "Fiji Ferry Control Hub",  # Modernized title
    "site_header": "Ferry Control",  # Concise for header
    "site_brand": "Fiji Ferry",  # Consistent branding
    "welcome_sign": "Welcome to Fiji Ferry Control Hub",
    "copyright": "Fiji Ferry © 2025",
    "search_model": "auth.User",
    "site_logo": "apple-touch-icon.png",  # Replace with your logo in static/images/
    "site_logo_classes": "img-circle img-thumbnail",  # Subtle border effect
    "site_icon": "apple-touch-icon.png",  # Replace with your favicon
    "user_avatar": None,
    "topmenu_links": [
        {
            "name": "Control Hub",
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
    ],
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": [],
    "order_with_respect_to": ["auth", "accounts", "bookings"],
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.User": "fas fa-user",
        "accounts.User": "fas fa-user-tie",
        "bookings.Port": "fas fa-anchor",
        "bookings.Cargo": "fas fa-box",
        "bookings.Ferry": "fas fa-ship",
        "bookings.Route": "fas fa-route",
        "bookings.WeatherCondition": "fas fa-cloud",
        "bookings.Schedule": "fas fa-calendar-alt",
        "bookings.Booking": "fas fa-ticket-alt",
        "bookings.Passenger": "fas fa-user-friends",
        "bookings.Vehicle": "fas fa-car",
        "bookings.AddOn": "fas fa-plus-circle",
        "bookings.Payment": "fas fa-credit-card",
        "bookings.Ticket": "fas fa-ticket",
        "bookings.MaintenanceLog": "fas fa-tools",
        "bookings.ServicePattern": "fas fa-clock",
    },
    "related_modal_active": True,
    "custom_css": "css/admin_custom.css",  # Points to updated CSS
    "custom_js": "js/admin_custom.js",
    "show_ui_builder": True,  # Enable for live tweaking
}