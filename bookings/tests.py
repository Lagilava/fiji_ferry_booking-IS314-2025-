"""Test suite for the booking service layer, DB invariants, and authorization.

Fully offline: the only external dependency (Stripe) is mocked, and email is
mocked. Run with:  python manage.py test bookings
"""
import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.db import transaction, DatabaseError
from django.test import TestCase, Client
from django.utils import timezone

from accounts.models import User
from bookings import services
from bookings.services import InvalidTransition, BookingStatus
from bookings.models import (
    Port, Ferry, Route, Schedule, Booking, Passenger, Payment, Ticket,
)


def client(**extra):
    """A test client that passes ALLOWED_HOSTS (which excludes 'testserver')."""
    return Client(HTTP_HOST="localhost", **extra)


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


def make_user(email, staff=False):
    u = User.objects.create_user(email=email, username=email.split('@')[0], password="pw12345!")
    if staff:
        u.is_staff = True
        u.save()
    return u


# --------------------------------------------------------------------------- #
# Service layer
# --------------------------------------------------------------------------- #
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
        self.assertEqual(sch.available_seats, 3)
        services.release_seats(sch.pk, 7)
        sch.refresh_from_db()
        self.assertEqual(sch.available_seats, 10)

    def test_reserve_rejects_oversell(self):
        sch = make_schedule(seats=2)
        with transaction.atomic():
            self.assertFalse(services.reserve_seats(sch.pk, 3))
        sch.refresh_from_db()
        self.assertEqual(sch.available_seats, 2)

    def test_db_constraint_blocks_negative_seats(self):
        sch = make_schedule(seats=1)
        with self.assertRaises(DatabaseError):
            with transaction.atomic():
                Schedule.objects.filter(pk=sch.pk).update(available_seats=-1)


class ConfirmPaymentTests(TestCase):
    def test_confirm_is_idempotent(self):
        sch = make_schedule(seats=10)
        b = make_booking(sch, guest_email="g@x.com", status='pending')
        for _ in range(3):
            services.confirm_paid_booking(
                b.id, session_id="cs_test_1",
                payment_intent_id="pi_1", amount=Decimal("100.00"),
            )
        b.refresh_from_db()
        self.assertEqual(b.status, 'confirmed')
        self.assertEqual(b.payments.filter(payment_status='completed').count(), 1)


class CancelServiceTests(TestCase):
    def test_cancel_releases_seats_and_is_idempotent(self):
        sch = make_schedule(seats=10)
        with transaction.atomic():
            services.reserve_seats(sch.pk, 2)
        b = make_booking(sch, guest_email="g@x.com", status='pending')
        _b, changed1 = services.cancel_booking(b.id, do_refund=True)
        _b, changed2 = services.cancel_booking(b.id, do_refund=True)
        sch.refresh_from_db()
        self.assertTrue(changed1)
        self.assertFalse(changed2)
        self.assertEqual(sch.available_seats, 10)
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


class PricingTests(TestCase):
    def test_passenger_and_total_pricing(self):
        from bookings import pricing
        sch = make_schedule()
        self.assertEqual(pricing.calculate_passenger_price(2, 1, 1, sch), Decimal("130.000"))
        total = pricing.calculate_total_price(
            2, 0, 0, sch, add_cargo=False, cargo_type=None, weight_kg=0, addons=[]
        )
        self.assertEqual(total, Decimal("100.00"))

    def test_addon_and_cargo_pricing(self):
        from bookings import pricing
        self.assertEqual(pricing.calculate_addon_price('cabin', 2), Decimal("100.00"))
        self.assertEqual(pricing.calculate_cargo_price(10, 'Heavy Cargo'), Decimal("100.00"))
        with self.assertRaises(ValueError):
            pricing.calculate_addon_price('not_a_thing', 1)


# --------------------------------------------------------------------------- #
# Authorization (SEC-1)
# --------------------------------------------------------------------------- #
class BookingPdfAuthorizationTests(TestCase):
    def setUp(self):
        self.sch = make_schedule()
        self.owner = make_user("owner@x.com")
        self.other = make_user("other@x.com")
        self.staff = make_user("staff@x.com", staff=True)
        self.user_booking = make_booking(self.sch, user=self.owner, status='confirmed')
        self.guest_booking = make_booking(self.sch, guest_email="guest@x.com", status='confirmed')

    def _pdf(self, c, booking):
        return c.get(f"/bookings/booking/{booking.id}/pdf/")

    def test_anonymous_denied(self):
        self.assertEqual(self._pdf(client(), self.user_booking).status_code, 403)

    def test_anonymous_denied_guest_booking_without_session(self):
        self.assertEqual(self._pdf(client(), self.guest_booking).status_code, 403)

    def test_owner_allowed(self):
        c = client(); c.force_login(self.owner)
        self.assertEqual(self._pdf(c, self.user_booking).status_code, 200)

    def test_other_user_denied(self):
        c = client(); c.force_login(self.other)
        self.assertEqual(self._pdf(c, self.user_booking).status_code, 403)

    def test_staff_allowed(self):
        c = client(); c.force_login(self.staff)
        self.assertEqual(self._pdf(c, self.user_booking).status_code, 200)

    def test_guest_with_matching_session_allowed(self):
        c = client()
        s = c.session
        s['guest_email'] = "guest@x.com"
        s.save()
        self.assertEqual(self._pdf(c, self.guest_booking).status_code, 200)


# --------------------------------------------------------------------------- #
# Public pages + APIs
# --------------------------------------------------------------------------- #
class PublicPageTests(TestCase):
    def setUp(self):
        self.sch = make_schedule(seats=10, departs_in_hours=72)

    def test_homepage_renders(self):
        r = client().get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "schedule-card")

    def test_homepage_route_text_filter_with_to_in_port_name(self):
        o = self.sch.route.departure_port.name
        d = self.sch.route.destination_port.name
        r = client().get("/", {"route": f"{o} to {d}"})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "Invalid route format")

    def test_privacy_and_terms(self):
        self.assertEqual(client().get("/bookings/privacy_policy/").status_code, 200)
        self.assertEqual(client().get("/bookings/terms_of_service/").status_code, 200)


class ApiTests(TestCase):
    def setUp(self):
        self.sch = make_schedule(seats=10, departs_in_hours=72)
        self.route = self.sch.route

    def test_routes_api(self):
        r = client().get("/bookings/api/routes/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("routes", r.json())

    def test_availability_api_valid(self):
        # availability groups by departure_time date (connection tz); assert the
        # month returns the sailing rather than a specific tz-boundary date.
        d = self.sch.departure_time
        r = client().get("/bookings/api/availability/",
                         {"route_id": self.route.id, "year": d.year, "month": d.month})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["available_dates"]), 1)

    def test_availability_api_bad_input_no_500(self):
        r = client().get("/bookings/api/availability/",
                         {"route_id": self.route.id, "year": "abc", "month": "x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["available_dates"], [])

    def test_api_bookings_by_date(self):
        r = client().get("/bookings/api/bookings/", {"date": str(self.sch.operational_day)})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total"], 1)

    def test_pricing_api(self):
        c = client(); c.force_login(make_user("p@x.com", staff=True))
        r = c.post("/bookings/api/pricing/",
                   {"schedule_id": self.sch.id, "adults": 2, "children": 1, "infants": 0})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["total_price"], "125.000")


# --------------------------------------------------------------------------- #
# Checkout flow (Stripe mocked)
# --------------------------------------------------------------------------- #
class CheckoutFlowTests(TestCase):
    def setUp(self):
        self.sch = make_schedule(seats=5, departs_in_hours=72)
        self.user = make_user("buyer@x.com", staff=True)  # staff bypasses guest OTP gate

    def _payload(self, **over):
        p = {"schedule_id": self.sch.id, "adults": 2, "children": 0, "infants": 0,
             "adult_first_name_0": "A", "adult_last_name_0": "B", "adult_age_0": 30,
             "adult_first_name_1": "C", "adult_last_name_1": "D", "adult_age_1": 28}
        p.update(over)
        return p

    @mock.patch("bookings.views.stripe")
    def test_checkout_creates_booking_and_reserves_seats(self, mstripe):
        mstripe.checkout.Session.create.return_value = SimpleNamespace(id="cs_test_123")
        c = client(); c.force_login(self.user)
        r = c.post("/bookings/api/create_checkout_session/", self._payload())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sessionId"], "cs_test_123")
        self.sch.refresh_from_db()
        self.assertEqual(self.sch.available_seats, 3)
        self.assertEqual(Booking.objects.filter(status="pending").count(), 1)
        self.assertEqual(Passenger.objects.count(), 2)

    @mock.patch("bookings.views.stripe")
    def test_checkout_overbooking_rejected(self, mstripe):
        mstripe.checkout.Session.create.return_value = SimpleNamespace(id="cs_x")
        c = client(); c.force_login(self.user)
        r = c.post("/bookings/api/create_checkout_session/",
                   self._payload(adults=6, adult_first_name_2="E", adult_last_name_2="F"))
        self.assertEqual(r.status_code, 400)
        self.sch.refresh_from_db()
        self.assertEqual(self.sch.available_seats, 5)
        self.assertEqual(Booking.objects.count(), 0)

    @mock.patch("bookings.views.stripe")
    def test_checkout_idempotency_dedupes(self, mstripe):
        mstripe.checkout.Session.create.return_value = SimpleNamespace(id="cs_dedupe")
        c = client(); c.force_login(self.user)
        payload = self._payload(idempotency_key="tok-123")
        r1 = c.post("/bookings/api/create_checkout_session/", payload)
        r2 = c.post("/bookings/api/create_checkout_session/", dict(payload))
        self.assertEqual(r1.json()["sessionId"], r2.json()["sessionId"])
        self.sch.refresh_from_db()
        self.assertEqual(self.sch.available_seats, 3)
        self.assertEqual(Booking.objects.count(), 1)


# --------------------------------------------------------------------------- #
# Webhook (Stripe mocked)
# --------------------------------------------------------------------------- #
class WebhookTests(TestCase):
    def setUp(self):
        self.sch = make_schedule(seats=10, departs_in_hours=72)
        self.booking = make_booking(self.sch, guest_email="g@x.com", status="pending")
        Passenger.objects.create(booking=self.booking, first_name="A", last_name="B",
                                 passenger_type="adult")

    def _event(self, sid, pi):
        return {"type": "checkout.session.completed",
                "data": {"object": {"id": sid, "payment_intent": pi, "amount_total": 10000,
                                    "metadata": {"booking_id": str(self.booking.id)}}}}

    @mock.patch("bookings.views.stripe")
    def test_webhook_confirms_and_generates_tickets(self, mstripe):
        mstripe.Webhook.construct_event.return_value = self._event("cs_w", "pi_w")
        r = client().post("/bookings/api/stripe_webhook/", data="{}",
                          content_type="application/json", HTTP_STRIPE_SIGNATURE="t")
        self.assertEqual(r.status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "confirmed")
        self.assertEqual(Ticket.objects.filter(booking=self.booking).count(), 1)

    @mock.patch("bookings.views.stripe")
    def test_webhook_idempotent(self, mstripe):
        mstripe.Webhook.construct_event.return_value = self._event("cs_w2", "pi_w2")
        for _ in range(3):
            client().post("/bookings/api/stripe_webhook/", data="{}",
                          content_type="application/json", HTTP_STRIPE_SIGNATURE="t")
        self.assertEqual(self.booking.payments.filter(payment_status="completed").count(), 1)


# --------------------------------------------------------------------------- #
# Cancel view (Stripe mocked)
# --------------------------------------------------------------------------- #
class CancelViewTests(TestCase):
    def setUp(self):
        self.sch = make_schedule(seats=10, departs_in_hours=72)
        self.owner = make_user("owner2@x.com")
        self.booking = make_booking(self.sch, user=self.owner, status="confirmed",
                                    payment_intent_id="pi_cancel")
        with transaction.atomic():
            services.reserve_seats(self.sch.pk, 2)

    @mock.patch("bookings.services.stripe")
    def test_cancel_view_refunds_and_restores_seats(self, mstripe):
        mstripe.Refund.create.return_value = SimpleNamespace(id="re_1")
        c = client(); c.force_login(self.owner)
        r = c.post(f"/bookings/cancel_booking/{self.booking.id}/")
        self.assertEqual(r.status_code, 302)
        self.booking.refresh_from_db()
        self.sch.refresh_from_db()
        self.assertEqual(self.booking.status, "cancelled")
        self.assertEqual(self.sch.available_seats, 10)
        mstripe.Refund.create.assert_called_once()

    def test_cancel_other_users_booking_denied(self):
        c = client(); c.force_login(make_user("intruder@x.com"))
        r = c.post(f"/bookings/cancel_booking/{self.booking.id}/")
        self.assertEqual(r.status_code, 302)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "confirmed")


# --------------------------------------------------------------------------- #
# OTP (email mocked) + upload validation
# --------------------------------------------------------------------------- #
class OtpTests(TestCase):
    @mock.patch("bookings.views.EmailMultiAlternatives")
    def test_send_otp_rate_limited(self, mmail):
        from django.core.cache import cache
        cache.clear()
        c = client()
        codes = [c.post("/bookings/api/send_otp/", {"email": "rl@x.com"}).status_code
                 for _ in range(5)]
        self.assertIn(429, codes)

    @mock.patch("bookings.views.EmailMultiAlternatives")
    def test_send_otp_graceful_on_smtp_error(self, mmail):
        from django.core.cache import cache
        cache.clear()
        mmail.return_value.send.side_effect = Exception("smtp down")
        r = client().post("/bookings/api/send_otp/", {"email": "err@x.com"})
        self.assertEqual(r.status_code, 502)
        self.assertFalse(r.json()["success"])


class FileValidationTests(TestCase):
    def test_rejects_spoofed_extension(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from bookings.views import _validate_id_document
        bad = SimpleUploadedFile("evil.jpg", b"<html>nope</html>", content_type="image/jpeg")
        with self.assertRaises(Exception):
            _validate_id_document(bad)

    def test_accepts_real_png(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from bookings.views import _validate_id_document
        png = SimpleUploadedFile("ok.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
                                 content_type="image/png")
        _validate_id_document(png)
