# Backfill vehicle/cargo capacity on existing schedules from their ferry.
from django.db import migrations


def backfill(apps, schema_editor):
    Schedule = apps.get_model('bookings', 'Schedule')
    # Only seed rows still at the field defaults (0), so re-running is safe and
    # we never clobber capacity that has already been consumed by bookings.
    for sched in Schedule.objects.select_related('ferry').filter(
        available_vehicle_slots=0, available_cargo_kg=0
    ):
        if sched.ferry_id:
            sched.available_vehicle_slots = sched.ferry.vehicle_capacity
            sched.available_cargo_kg = sched.ferry.max_cargo_kg
            sched.save(update_fields=['available_vehicle_slots', 'available_cargo_kg'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('bookings', '0008_ferry_max_cargo_kg_ferry_vehicle_capacity_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
