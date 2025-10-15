# bookings/apps.py
from django.apps import AppConfig
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class BookingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'bookings'

    def ready(self):
        """Initialize admin enhancements when app is ready - FIXED."""
        from django.conf import settings

        # Only initialize if explicitly enabled
        if getattr(settings, 'ADMIN_ENHANCEMENTS_ENABLED', False):
            try:
                # Import here to avoid circular imports
                from .admin import start_admin_background_tasks, clear_analytics_cache

                # Start background tasks only if enabled and not in test mode
                if (getattr(settings, 'ADMIN_BACKGROUND_TASKS', False) and
                        not hasattr(settings, 'TESTING') and
                        not settings.DEBUG):
                    start_admin_background_tasks()
                    logger.info("Admin background tasks started")
                else:
                    logger.info("Admin background tasks skipped (DEBUG/TEST mode)")

                # Test cache clearing
                clear_analytics_cache()
                logger.info("Bookings app ready - Admin enhancements initialized")

            except ImportError as e:
                logger.warning(f"Admin enhancements import failed: {e}")
            except Exception as e:
                logger.error(f"Failed to initialize admin enhancements: {e}")
        else:
            logger.info("Admin enhancements disabled in settings")