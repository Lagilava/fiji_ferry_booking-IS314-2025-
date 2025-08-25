import uuid
from django.core.management.base import BaseCommand
from bookings.models import Ticket

class Command(BaseCommand):
    help = "Generate unique qr_token for tickets with empty qr_token."

    def handle(self, *args, **options):
        tickets = Ticket.objects.filter(qr_token__isnull=True)
        count = tickets.count()
        self.stdout.write(f"Found {count} tickets without qr_token.")

        for ticket in tickets:
            ticket.qr_token = uuid.uuid4().hex
            ticket.save()
            self.stdout.write(f"Generated qr_token for Ticket ID {ticket.id}")

        self.stdout.write("Finished generating qr_tokens.")
