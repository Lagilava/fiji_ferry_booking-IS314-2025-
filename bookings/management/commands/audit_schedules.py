"""Audit (and optionally fix) legacy schedule conflicts.

Surfaces the same operational risks as the Operations dashboard — ferry
turnaround overlaps and maintenance conflicts — for sailings created before the
prevention gate existed. By default it only reports (dry run). With ``--fix`` it
cancels conflicting sailings **that have no active (pending/confirmed) bookings**;
sailings that carry bookings are always left for a human and listed for manual
review.

Usage:
    python manage.py audit_schedules            # report only
    python manage.py audit_schedules --fix      # cancel safe (booking-free) conflicts
"""
from django.core.management.base import BaseCommand
from django.db.models import Q

from bookings import scheduling
from bookings.models import Booking, Schedule


def _has_active_bookings(schedule):
    return Booking.objects.filter(
        schedule=schedule, status__in=("pending", "confirmed")
    ).exists()


class Command(BaseCommand):
    help = "Audit and optionally fix legacy ferry overlap / maintenance schedule conflicts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix", action="store_true",
            help="Cancel conflicting sailings that have no active bookings.",
        )

    def handle(self, *args, **options):
        fix = options["fix"]
        overlaps = scheduling.upcoming_overlap_conflicts()
        maintenance = scheduling.upcoming_maintenance_conflicts()

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nSchedule audit — {len(overlaps)} overlap, {len(maintenance)} maintenance conflict(s)"
        ))

        # The later sailing in each overlap pair is the one to resolve.
        to_resolve = {c["schedule"].pk: c["schedule"] for c in overlaps}
        for s in maintenance:
            to_resolve[s.pk] = s

        cancelled = 0
        skipped_booked = 0
        for sched in to_resolve.values():
            tag = f"#{sched.pk} {sched.ferry.name} — {sched.route} @ {sched.departure_time:%Y-%m-%d %H:%M}"
            if _has_active_bookings(sched):
                skipped_booked += 1
                self.stdout.write(self.style.WARNING(f"  KEEP (has bookings): {tag}"))
                continue
            if fix:
                sched.status = "cancelled"
                sched.save(update_fields=["status", "last_updated"])
                cancelled += 1
                self.stdout.write(self.style.SUCCESS(f"  CANCELLED: {tag}"))
            else:
                self.stdout.write(f"  would cancel: {tag}")

        self.stdout.write("")
        if fix:
            self.stdout.write(self.style.SUCCESS(
                f"Done: cancelled {cancelled} conflict(s); {skipped_booked} kept (have bookings)."
            ))
        else:
            self.stdout.write(self.style.NOTICE(
                f"Dry run: {len(to_resolve) - skipped_booked} would be cancelled, "
                f"{skipped_booked} kept (have bookings). Re-run with --fix to apply."
            ))
