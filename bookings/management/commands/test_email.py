"""Diagnose live email/SMTP configuration.

Run in the Render Shell (or locally) to see exactly why mail does or doesn't
send — prints the resolved settings and the full error if the send fails:

    python manage.py test_email
    python manage.py test_email --to someone@example.com
"""
import traceback

from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Send a test email and report the resolved email configuration / errors."

    def add_arguments(self, parser):
        parser.add_argument('--to', default=None, help='Recipient (defaults to ADMIN_EMAIL).')

    def handle(self, *args, **options):
        to = options['to'] or getattr(settings, 'ADMIN_EMAIL', '') or getattr(settings, 'EMAIL_HOST_USER', '')
        self.stdout.write(self.style.MIGRATE_HEADING("Email configuration"))
        self.stdout.write(f"  EMAIL_BACKEND      = {settings.EMAIL_BACKEND}")
        self.stdout.write(f"  EMAIL_HOST         = {getattr(settings, 'EMAIL_HOST', '')}")
        self.stdout.write(f"  EMAIL_PORT         = {getattr(settings, 'EMAIL_PORT', '')}")
        self.stdout.write(f"  EMAIL_USE_TLS      = {getattr(settings, 'EMAIL_USE_TLS', '')}")
        self.stdout.write(f"  EMAIL_USE_SSL      = {getattr(settings, 'EMAIL_USE_SSL', False)}")
        self.stdout.write(f"  EMAIL_HOST_USER    = {getattr(settings, 'EMAIL_HOST_USER', '')}")
        self.stdout.write(f"  password set       = {bool(getattr(settings, 'EMAIL_HOST_PASSWORD', ''))}")
        self.stdout.write(f"  EMAIL_TIMEOUT      = {getattr(settings, 'EMAIL_TIMEOUT', None)}")
        self.stdout.write(f"  DEFAULT_FROM_EMAIL = {getattr(settings, 'DEFAULT_FROM_EMAIL', '')}")
        self.stdout.write(f"  -> sending test to : {to}\n")

        if not to:
            self.stdout.write(self.style.ERROR("No recipient. Pass --to or set ADMIN_EMAIL."))
            return

        try:
            n = send_mail(
                "Fiji Ferry — email diagnostic",
                "If you received this, outbound email works from this environment.",
                getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                [to],
                fail_silently=False,
            )
            self.stdout.write(self.style.SUCCESS(f"OK — send_mail returned {n}. Check the inbox (and spam)."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"FAILED: {type(e).__name__}: {e}\n"))
            self.stdout.write(traceback.format_exc())
            self.stdout.write(self.style.WARNING(
                "\nCommon causes:\n"
                "  - Connection timeout  -> the host blocks/throttles outbound SMTP (port 587).\n"
                "  - 535 BadCredentials  -> wrong Gmail App Password (must be 16 chars, no spaces).\n"
                "  - Name or service not known -> EMAIL_HOST wrong.\n"
                "If SMTP is blocked here, switch to an HTTP email API (SendGrid/Resend/Mailgun)."
            ))
