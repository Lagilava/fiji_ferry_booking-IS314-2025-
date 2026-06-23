"""Test suite for the booking service layer, DB invariants, and authorization.

Run with:  python manage.py test bookings
"""
import datetime
from decimal import Decimal

from django.db import transaction, DatabaseError
from django.test import TestCase, Client
from django.utils import timezone

from accounts.models import User
from bookings import services
from bookings.services import InvalidTransition, BookingStatus
from bookings.models import Port, Ferry, Route, Schedule, Booking


def make_schedule(seats=10, departs_in_hours=48):
    p1 = Port.objects.create(name=f"Origin{Port.objects.count()}", lat=-18.0, lng=178.0)
    p2 = Port.objects.create(name=f"Dest{Port.objects.count()}", lat=-17.5, lng=178.5)
    ferry = Ferry.objects.create(name=f"Ferry{Ferry.objects.count()}", capacity=200)
    route = Route.objects.create(
        departure_port=p1, destination_port=p2,
        distance_km=Decimal("50"), base_fare=Decimal("50.00"),
        estimated_duration=datetime.timedelta(hours=2),
    )
    now = timezone.now()
    return Schedule.objects.create(
        ferry=ferry, route=route,
        departure_time=now + datetime.timedelta(hours=departs_in_hours),
        arrival_time=now + datetime.timedelta(hours=departs_in_hours + 2),
        available_seats=seats, status='scheduled',
        operational_day=(now + datetime.timedelta(hours=departs_in_hours)).date(),
    )


def make_booking(schedule, *, user=None, guest_email=None, adults=2, status='pending',
                 payment_intent_id=None):
    return Booking.objects.create(
        user=user, guest_email=guest_email, schedule=schedule,
        passenger_adults=adults, passenger_children=0, passenger_infants=0,
        total_price=Decimal("100.00"), status=status, payment_intent_id=payment_intent_id,
    )


class StateMachineTests(TestCase):
    def test_legal_transitions(self):
        sch = make_schedule()
        b = make_booking(sch, guest_email="g@x.com", status='pending')
        services.transition_booking(b, BookingStatus.CONFIRMED)
        self.assertEqual(Booking.objects.get(pk=b.pk).status, 'confirmed')
        services.transition_booking(b, BookingStatus.CANCELLED)
        self.assertEqual(Booking.objects.get(pk=b.pk).status, 'cancelled')

    def test_illegal_transition_raises(self):
        sch = make_schedule()
        b = make_booking(sch, guest_email="g@x.com", status='cancelled')
        with self.assertRaises(InvalidTransition):
            services.transition_booking(b, BookingStatus.CONFIRMED, save=False)


class SeatInventoryTests(TestCase):
    def test_reserve_and_release_are_atomic(self):
        sch = make_schedule(seats=10)
        with transaction.atomic():
            self.assertTrue(services.reserve_seats(sch.pk, 3))
        with transaction.atomic():
            self.assertTrue(services.reserve_seats(sch.pk, 4))
        sch.refresh_from_db()
        self.assertEqual(sch.available_seats, 3)  # 10 - 3 - 4, no lost update
        services.release_seats(sch.pk, 7)
        sch.refresh_from_db()
        self.assertEqual(sch.available_seats, 10)

    def test_reserve_rejects_oversell(self):
        sch = make_schedule(seats=2)
        with transaction.atomic():
            self.assertFalse(services.reserve_seats(sch.pk, 3))
        sch.refresh_from_db()
        self.assertEqual(sch.available_seats, 2)  # unchanged

    def test_db_constraint_blocks_negative_seats(self):
        # The DB must refuse negative inventory: PositiveIntegerField is UNSIGNED
        # (DataError) and the CHECK constraint is a second backstop (IntegrityError);
        # both are DatabaseError subclasses.
        sch = make_schedule(seats=1)
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Schedule.objects.filter(pk=sch.pk).update(available_seats=-1)


class ConfirmPaymentTests(TestCase):
    def test_confirm_is_idempotent(self):
        sch = make_schedule(seats=10)
        b = make_booking(sch, guest_email="g@x.com", status='pending')
        for _ in range(3):  # simulate webhook re-delivery
            services.confirm_paid_booking(
                b.id, session_id="cs_test_1",
                payment_intent_id="pi_1", amount=Decimal("100.00"),
            )
        b.refresh_from_db()
        self.assertEqual(b.status, 'confirmed')
        self.assertEqual(b.payments.filter(payment_status='completed').count(), 1)


class CancelTests(TestCase):
    def test_cancel_releases_seats_and_is_idempotent(self):
        sch = make_schedule(seats=10)
        with transaction.atomic():
            services.reserve_seats(sch.pk, 2)
        b = make_booking(sch, guest_email="g@x.com", status='pending')  # no payment_intent -> no Stripe

        _b, changed1 = services.cancel_booking(b.id, do_refund=True)
        _b, changed2 = services.cancel_booking(b.id, do_refund=True)

        sch.refresh_from_db()
        self.assertTrue(changed1)
        self.assertFalse(changed2)                 # idempotent no-op
        self.assertEqual(sch.available_seats, 10)  # seats restored exactly once
        self.assertEqual(Booking.objects.get(pk=b.id).status, 'cancelled')

    def test_expire_pending_releases_seats(self):
        sch = make_schedule(seats=10)
        with transaction.atomic():
            services.reserve_seats(sch.pk, 2)
        b = make_booking(sch, guest_email="g@x.com", status='pending')
        self.assertTrue(services.expire_pending_booking(b.id))
        sch.refresh_from_db()
        self.assertEqual(sch.available_seats, 10)
        self.assertEqual(Booking.objects.get(pk=b.id).status, 'cancelled')


class BookingPdfAuthorizationTests(TestCase):
    """SEC-1: object-level authorization on the ticket PDF."""

    def setUp(self):
        self.sch = make_schedule()
        self.owner = User.objects.create_user(email="owner@x.com", username="owner", password="pw12345!")
        self.other = User.objects.create_user(email="other@x.com", username="other", password="pw12345!")
        self.staff = User.objects.create_user(email="staff@x.com", username="staff", password="pw12345!")
        self.staff.is_staff = True
        self.staff.save()
        self.user_booking = make_booking(self.sch, user=self.owner, status='confirmed')
        self.guest_booking = make_booking(self.sch, guest_email="guest@x.com", status='confirmed')

    def _pdf(self, client, booking):
        return client.get(f"/bookings/booking/{booking.id}/pdf/", HTTP_HOST="localhost")

    def test_anonymous_denied(self):
        self.assertEqual(self._pdf(Client(), self.user_booking).status_code, 403)

    def test_anonymous_denied_guest_booking_without_session(self):
        self.assertEqual(self._pdf(Client(), self.guest_booking).status_code, 403)

    def test_owner_allowed(self):
        c = Client(); c.force_login(self.owner)
        self.assertEqual(self._pdf(c, self.user_booking).status_code, 200)

    def test_other_user_denied(self):
        c = Client(); c.force_login(self.other)
        self.assertEqual(self._pdf(c, self.user_booking).status_code, 403)

    def test_staff_allowed(self):
        c = Client(); c.force_login(self.staff)
        self.assertEqual(self._pdf(c, self.user_booking).status_code, 200)

    def test_guest_with_matching_session_allowed(self):
        c = Client()
        s = c.session
        s['guest_email'] = "guest@x.com"
        s.save()
        self.assertEqual(self._pdf(c, self.guest_booking).status_code, 200)
