"""Tests for the deterministic slot-filling dialog engine (chatbot_engine)."""
import datetime

from django.test import TestCase
from django.utils import timezone

from bookings import chatbot, chatbot_engine
from bookings.models import Ferry, Port, Route, Schedule, WaitlistEntry


def _mkport(name, lat=-17.8, lng=177.4):
    return Port.objects.create(name=name, lat=lat, lng=lng)


class ExtractorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.nadi = _mkport("Nadi")
        cls.suva = _mkport("Suva", lat=-18.1, lng=178.4)
        cls.savusavu = _mkport("Savusavu", lat=-16.8, lng=179.3)

    def test_route_a_to_b(self):
        origin, dest = chatbot_engine.extract_route("book nadi to suva")
        self.assertEqual(origin["name"], "Nadi")
        self.assertEqual(dest["name"], "Suva")

    def test_route_prepositions(self):
        origin, dest = chatbot_engine.extract_route("i want to go to savusavu from suva")
        self.assertEqual(origin["name"], "Suva")
        self.assertEqual(dest["name"], "Savusavu")

    def test_lone_port_is_destination(self):
        origin, dest = chatbot_engine.extract_route("how do i get to savusavu")
        self.assertIsNone(origin)
        self.assertEqual(dest["name"], "Savusavu")

    def test_date_tomorrow(self):
        today = timezone.localdate()
        self.assertEqual(chatbot_engine.extract_date("leaving tomorrow", today),
                         today + datetime.timedelta(days=1))

    def test_date_weekday(self):
        today = datetime.date(2026, 7, 11)  # a Saturday
        d = chatbot_engine.extract_date("on friday", today)
        self.assertEqual(d, datetime.date(2026, 7, 17))

    def test_date_explicit(self):
        self.assertEqual(chatbot_engine.extract_date("on 14 july 2026"),
                         datetime.date(2026, 7, 14))
        self.assertEqual(chatbot_engine.extract_date("2026-08-02"),
                         datetime.date(2026, 8, 2))

    def test_party_mixed(self):
        p = chatbot_engine.extract_party("2 adults and 1 child and a baby")
        self.assertEqual(p, {"adults": 2, "children": 1, "infants": 1})

    def test_party_generic(self):
        self.assertEqual(chatbot_engine.extract_party("3 people")["adults"], 3)
        self.assertEqual(chatbot_engine.extract_party("family of four")["adults"], 4)
        self.assertEqual(chatbot_engine.extract_party("just me")["adults"], 1)

    def test_party_children_alone_get_adult(self):
        p = chatbot_engine.extract_party("2 kids")
        self.assertEqual(p["adults"], 1)
        self.assertEqual(p["children"], 2)

    def test_party_bare_number_only_when_asked(self):
        self.assertIsNone(chatbot_engine.extract_party("3"))
        self.assertEqual(chatbot_engine.extract_party("3", allow_bare_number=True)["adults"], 3)


class DialogTests(TestCase):
    """Drive full conversations through chatbot.answer()."""

    @classmethod
    def setUpTestData(cls):
        cls.nadi = _mkport("Nadi")
        cls.suva = _mkport("Suva", lat=-18.1, lng=178.4)
        cls.savusavu = _mkport("Savusavu", lat=-16.8, lng=179.3)
        cls.ferry = Ferry.objects.create(name="Test Ferry", capacity=100)
        cls.route = Route.objects.create(
            departure_port=cls.nadi, destination_port=cls.suva, base_fare=50)
        cls.dep = timezone.now() + datetime.timedelta(days=2)
        cls.schedule = Schedule.objects.create(
            ferry=cls.ferry, route=cls.route,
            departure_time=cls.dep,
            arrival_time=cls.dep + datetime.timedelta(hours=4),
            available_seats=40,
            operational_day=cls.dep.date(),
        )

    def _talk(self, messages):
        """Send messages in sequence, threading the context like the view does."""
        ctx, out = {}, None
        for msg in messages:
            out = chatbot.answer(msg, context=ctx)
            ctx = out["context"]
        return out

    def test_one_shot_plan(self):
        # The engine filters by *local* calendar day (as a customer would say
        # it), so ask for the sailing's local date, not its UTC date.
        date_str = timezone.localtime(self.dep).strftime("%Y-%m-%d")
        out = self._talk([f"book 2 adults and 1 child nadi to suva on {date_str}"])
        self.assertEqual(out["intent"], "engine_plan_trip")
        self.assertIn("Nadi", out["reply"])
        self.assertIn("Suva", out["reply"])
        self.assertIn("2 adults, 1 child", out["reply"])
        # fare: 2*50 + 0.5*50 = 125
        self.assertIn("FJ$125.00", out["reply"])
        self.assertIn(f"schedule_id={self.schedule.id}", out["reply"])
        self.assertIn("passengers=3", out["reply"])

    def test_multi_turn_slot_filling(self):
        out = self._talk(["i want to book a ferry to suva", "2 adults"])
        self.assertEqual(out["intent"], "engine_plan_trip")
        self.assertIn("Book this sailing", out["reply"])
        self.assertIn("FJ$100.00", out["reply"])

    def test_asks_for_party(self):
        out = self._talk(["book nadi to suva"])
        self.assertIn("How many", out["reply"])
        self.assertIn("2 adults", out["suggestions"])

    def test_wrong_date_offers_alternatives(self):
        far = (self.dep + datetime.timedelta(days=30)).strftime("%Y-%m-%d")
        out = self._talk([f"book nadi to suva on {far}", "just me"])
        self.assertIn("No sailings", out["reply"])
        self.assertIn("next departures are", out["reply"])
        out2_ctx = out["context"]
        out2 = chatbot.answer("book the first one", context=out2_ctx)
        self.assertIn(f"schedule_id={self.schedule.id}", out2["reply"])

    def test_unknown_route(self):
        out = self._talk(["book savusavu to nadi for 2 people"])
        self.assertIn("don't currently sail", out["reply"])

    def test_sold_out_offers_waitlist_and_joins(self):
        self.schedule.available_seats = 1
        self.schedule.save(update_fields=["available_seats"])
        out = self._talk(["book 2 adults nadi to suva"])
        self.assertIn("fully booked", out["reply"])
        self.assertIn("Join the waitlist", out["suggestions"])
        # guest: asked for email, then joins
        ctx = out["context"]
        out2 = chatbot.answer("join the waitlist", context=ctx)
        self.assertIn("email", out2["reply"].lower())
        out3 = chatbot.answer("guest@example.com", context=out2["context"])
        self.assertIn("You're on the waitlist", out3["reply"])
        entry = WaitlistEntry.objects.get(schedule=self.schedule)
        self.assertEqual(entry.email, "guest@example.com")
        self.assertEqual(entry.seats_requested, 2)

    def test_reset_clears_task(self):
        out = self._talk(["book a ferry to suva", "never mind"])
        self.assertEqual(out["intent"], "engine_reset")
        self.assertNotIn("engine", out["context"])

    def test_static_intents_untouched(self):
        # No entities → the engine stays out of the way.
        out = self._talk(["how do i book a ticket?"])
        self.assertEqual(out["intent"], "booking_how_to")
        out = self._talk(["how do i cancel or get a refund?"])
        self.assertEqual(out["intent"], "cancel_refund")

    def test_subject_change_mid_task_falls_through(self):
        out = self._talk(["book a ferry to suva", "what documents do i need?"])
        self.assertEqual(out["intent"], "documents")
