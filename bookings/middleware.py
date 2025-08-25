from django.utils import timezone
from .models import Schedule

class ScheduleUpdateMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        now = timezone.now()
        Schedule.objects.filter(
            status='scheduled',
            departure_time__lt=now
        ).update(status='departed')
        return self.get_response(request)
