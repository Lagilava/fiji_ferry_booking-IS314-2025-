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

        # Visibility into the active email transport (shows in the free Logs tab).
        # Lets us confirm whether Brevo (HTTP) or SMTP is in effect without a shell.
        try:
            logger.info(
                "EMAIL CONFIG -> backend=%s | BREVO_API_KEY=%s | from=%s",
                settings.EMAIL_BACKEND,
                "set" if getattr(settings, "BREVO_API_KEY", "") else "NOT set",
                getattr(settings, "DEFAULT_FROM_EMAIL", ""),
            )
        except Exception:
            pass

        # Server status monitor: a daemon thread bound to the server lifecycle.
        # It self-guards so it only starts for real server processes (runserver /
        # daphne / asgi) and never for migrate/test/shell/etc.
        try:
            from .monitor import start_monitor
            start_monitor()
        except Exception as e:
            logger.warning(f"Server monitor failed to start: {e}")

        # Offline automation agent: periodic non-destructive self-tests, also
        # bound to the server lifecycle (daemon thread, dies with the server).
        try:
            from .automation import start_automation
            start_automation()
        except Exception as e:
            logger.warning(f"Automation agent failed to start: {e}")

        # Cybersecurity agent: periodic read-only security-posture audit
        # (Django deploy checks, settings hardening, cookie/HSTS, account &
        # repo hygiene). Same lifecycle contract as the other two daemons.
        try:
            from .security import start_security
            start_security()
        except Exception as e:
            logger.warning(f"Cybersecurity agent failed to start: {e}")

        # Ensure the booking system is "ready when the server is up": active
        # ferries, routes, and a rolling window of upcoming schedules. Runs in a
        # short-delayed daemon thread (server processes only) so it stays off the
        # app-initialization/DB path and is fully idempotent.
        try:
            from .seed import start_autoseed
            start_autoseed()
        except Exception as e:
            logger.warning(f"Auto-seed failed to start: {e}")

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