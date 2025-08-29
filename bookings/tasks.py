from celery import shared_task
from django.utils import timezone
from .models import Schedule

@shared_task
def update_schedules_status():
    now = timezone.now()
    return Schedule.objects.filter(
        status='scheduled',
        departure_time__lt=now
    ).update(status='departed')
