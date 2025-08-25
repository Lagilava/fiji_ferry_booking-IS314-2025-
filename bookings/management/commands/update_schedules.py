from django.core.management.base import BaseCommand
from django.utils import timezone
from schedules.models import Schedule


class Command(BaseCommand):
    help = 'Updates schedules that have departed.'

    def handle(self, *args, **kwargs):
        now = timezone.now()
        updated_count = Schedule.objects.filter(
            status='scheduled',
            departure_time__lt=now
        ).update(status='departed')

        self.stdout.write(
            self.style.SUCCESS(f'{updated_count} schedules updated successfully.')
        )
