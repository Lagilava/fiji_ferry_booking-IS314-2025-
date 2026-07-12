"""Rule-based help assistant for the public booking site.

A self-contained, offline, zero-cost FAQ/intent engine — no LLM, no API key,
no network. It maps a visitor's free-text question to the most relevant intent
using weighted keyword matching (with light synonym + typo tolerance), and
returns a helpful answer plus a few quick-reply suggestions.

Beyond static answers, several intents are *live*: they query the database to
answer with the real routes, the next sailings, current fares, and — for a
signed-in user — their own upcoming trip. Every live handler is defensive and
returns ``None`` on any error/empty data, falling back to the static answer, so
the bot still works in the offline/demo mode the rest of the project targets.

Add an intent by appending to ``INTENTS``; give it a ``handler`` to make it live.
"""
import difflib
import re

from django.db.models import Q
from django.utils.html import escape

# Quick-reply chips shown when the conversation opens or when we can't match.
DEFAULT_SUGGESTIONS = [
    "How do I book a ticket?",
    "Show me the next departures",
    "How do I change my booking?",
    "What documents do I need?",
    "How do I cancel or get a refund?",
]

GREETING_REPLY = (
    "Hi! 👋 I'm the Fiji Ferry assistant. I can help you book tickets, check "
    "fares and live departures, manage a booking, and find your way around the "
    "site. What would you like to do?"
)

FALLBACK_REPLY = (
    "Sorry, I didn't quite catch that. I can help with booking a ticket, "
    "fares, payments, cancellations, luggage &amp; vehicles, live departures, "
    "routes and your account. Try one of the suggestions below, or rephrase "
    "your question. For anything else, contact our team at "
    "<a href=\"mailto:info@fijiferrybooking.com\">info@fijiferrybooking.com</a> "
    "or +679 738 8496."
)

# Synonyms folded into the message before matching, so casual phrasing still hits
# the right intent ("ride"/"trip" → "ferry", "kid" → "child", etc.).
SYNONYMS = {
    "boat": "ferry", "ride": "ferry", "sailing": "ferry", "crossing": "ferry",
    "kids": "child", "kid": "child", "toddler": "child", "baby": "infant",
    "auto": "car", "automobile": "car", "motorcycle": "motorbike",
    "timetable": "schedule", "timings": "schedule", "times": "schedule",
    "tix": "ticket", "reservation": "booking", "buy": "book",
    "cancelling": "cancel", "canceling": "cancel", "cancelled": "cancel",
    "amend": "modify", "amending": "modify", "amendment": "modify",
    "alter": "modify", "update": "modify", "modifying": "modify",
    "ute": "car", "van": "car", "vehicle": "car",
    "passport": "document", "id": "document", "identification": "document",
    "birthdate": "dob", "birthday": "dob",
    "wheelchair": "accessibility", "disabled": "accessibility",
    "storm": "weather", "cyclone": "weather", "rain": "weather",
    "otp": "code", "pin": "code",
}

# NOTE: "fee"/"cost"/"charge" are deliberately NOT folded into "fare" — the
# change fee and the ticket fare are different things, and collapsing them made
# "what is the change fee?" answer with the fare table.


# --------------------------------------------------------------------------- #
# Safety: the assistant is public and unauthenticated. It must never describe
# internals, and must never be talked into acting as a general-purpose bot.
# --------------------------------------------------------------------------- #
_PROBE_PATTERNS = [
    # Internals. Note "password" alone is NOT here — "I forgot my password" is a
    # perfectly ordinary question that the `account` intent should answer.
    r"\b(admin|superuser|staff)\s*(panel|page|login|url|dashboard|account|password)",
    r"\b(database|sql|orm|schema|migration)\b",
    r"\b(source code|codebase|repo|repository|github|settings\.py|views\.py|\.env)\b",
    r"\b(api[_ ]?key|secret[_ ]?key|access[_ ]?token|credential)s?\b",
    r"\b(stripe|webhook)\s*(key|secret|endpoint)",
    r"\b(sql injection|xss|csrf|exploit|vulnerab|bypass|penetration test)",
    # Prompt-injection style redirection.
    r"\b(ignore|disregard|forget)\s+(all\s+)?(your\s+|the\s+)?(previous\s+)?(instruction|rule|prompt)",
    r"\byou are now\b|\bpretend to be\b|\bsystem prompt\b",
    # Other people's data. Scoped tightly so "make another booking" is fine.
    r"\b(someone|somebody|anyone)\s*(else)?('s)?\s+(booking|ticket|account|email|detail)",
    r"\b(another|other)\s+(person|customer|passenger|user)('s)?\s+(booking|ticket|account)",
    r"\b(all|every|list\s+the)\s+(bookings|customers|users|passengers|emails)\b",
    r"\bshow me\s+(the\s+)?(all\s+)?(users|customers|bookings|passengers)\b",
]

_PROBE_RE = re.compile("|".join(_PROBE_PATTERNS), re.IGNORECASE)

SAFETY_REPLY = (
    "I can only help with travel questions — booking, fares, schedules, "
    "luggage, and managing your own bookings. I can't share anything about how "
    "the system is built, or look up anyone else's booking. If you need account "
    "help, our team can verify your identity: "
    "<a href=\"mailto:info@fijiferrybooking.com\">info@fijiferrybooking.com</a> "
    "or +679 738 8496."
)


def is_unsafe(raw_text):
    """True when the message probes internals or asks for someone else's data.

    Checked against the *raw* text (before synonym folding), so obfuscation via
    the normalizer can't slip past it.
    """
    return bool(_PROBE_RE.search(raw_text or ""))


def _policy():
    """Live policy numbers, so the bot can never quote a stale fee or window."""
    try:
        from .modification import MODIFICATION_FEE, MODIFY_CUTOFF_HOURS
        return {"fee": f"{MODIFICATION_FEE:.2f}", "modify_hours": MODIFY_CUTOFF_HOURS}
    except Exception:
        return {"fee": "15.00", "modify_hours": 24}


# --------------------------------------------------------------------------- #
# Live-data handlers (defensive: any failure → None → static fallback)
# --------------------------------------------------------------------------- #
def _fmt_dt(dt):
    from django.utils import timezone
    try:
        return timezone.localtime(dt).strftime("%a %d %b, %H:%M")
    except Exception:
        return dt.strftime("%a %d %b, %H:%M")


# --------------------------------------------------------------------------- #
# Entity extraction — recognise port / place names the visitor mentions, so we
# can answer route-specific questions with live data ("fare to Yasawa", "next
# ferry from Denarau"). Defensive: returns [] on any DB issue.
# --------------------------------------------------------------------------- #
def _all_ports():
    from .models import Port
    return list(Port.objects.values("id", "name"))


def extract_ports(text):
    """Return [{id, name}] for ports whose name (or a significant word of it)
    appears in the visitor's text. Matches on whole name or a >=4-char token."""
    found, seen = [], set()
    try:
        for p in _all_ports():
            name = (p["name"] or "").lower()
            if not name:
                continue
            hit = name in text
            if not hit:
                for word in re.split(r"[^a-z0-9]+", name):
                    if len(word) >= 4 and re.search(r"\b" + re.escape(word) + r"\b", text):
                        hit = True
                        break
            if hit and p["id"] not in seen:
                seen.add(p["id"])
                found.append(p)
    except Exception:
        return []
    return found


def _routes_touching(port_ids):
    from .models import Route
    return (
        Route.objects.filter(
            Q(departure_port_id__in=port_ids) | Q(destination_port_id__in=port_ids)
        )
        .select_related("departure_port", "destination_port")
        .order_by("base_fare")[:6]
    )


def live_routes(ctx):
    try:
        from .models import Route
        routes = list(
            Route.objects.select_related("departure_port", "destination_port")
            .order_by("departure_port__name")[:8]
        )
        if not routes:
            return None
        items = []
        for r in routes:
            fare = getattr(r, "base_fare", None)
            fare_txt = f" — from FJ${fare:.0f}" if fare is not None else ""
            items.append(
                f"• {escape(r.departure_port.name)} → "
                f"{escape(r.destination_port.name)}{fare_txt}"
            )
        return (
            "Here are some of our routes (adult base fare):<br>"
            + "<br>".join(items)
            + "<br><br>See them all with photos on the "
            "<a href=\"/bookings/destinations/\">Destinations</a> page, then "
            "tap a route to <a href=\"/bookings/book/\">book</a>."
        )
    except Exception:
        return None


def live_departures(ctx):
    """Next scheduled sailings, optionally filtered to a place the visitor named."""
    try:
        from django.utils import timezone
        from .models import Schedule
        now = timezone.now()
        ports = ctx.get("ports") or []
        qs = (
            Schedule.objects.select_related(
                "ferry", "route__departure_port", "route__destination_port"
            )
            .filter(status="scheduled", departure_time__gte=now)
        )
        place = None
        if ports:
            pid = [p["id"] for p in ports]
            qs = qs.filter(
                Q(route__departure_port_id__in=pid) | Q(route__destination_port_id__in=pid)
            )
            place = escape(ports[0]["name"])

        sched = list(qs.order_by("departure_time")[:5])
        if not sched:
            if place:
                return {"reply": (
                    f"I don't see any upcoming scheduled sailings for "
                    f"<strong>{place}</strong> right now. Check the full "
                    "<a href=\"/bookings/departures/\">Live Departures</a> board, "
                    "as schedules update through the day.")}
            return None

        items = []
        for s in sched:
            seats = s.available_seats
            seat_txt = (f"{seats} seat{'s' if seats != 1 else ''} left"
                        if seats and seats > 0 else "fully booked")
            items.append(
                f"• <strong>{_fmt_dt(s.departure_time)}</strong> — "
                f"{escape(s.route.departure_port.name)} → "
                f"{escape(s.route.destination_port.name)} "
                f"({escape(s.ferry.name)}, {seat_txt})"
            )
        heading = (f"Next sailings via <strong>{place}</strong>:" if place
                   else "Next sailings:")
        return (
            heading + "<br>" + "<br>".join(items)
            + "<br><br>Full live board on the "
            "<a href=\"/bookings/departures/\">Live Departures</a> page."
        )
    except Exception:
        return None


def _fare_rules_tail():
    return (
        "<br><br>Children travel at <strong>50%</strong> and infants at "
        "<strong>10%</strong> of the adult fare; vehicles, cargo and add-ons are "
        "priced on top. The exact total is always shown on the "
        "<a href=\"/bookings/book/\">booking page</a> before you pay."
    )


def live_pricing(ctx):
    """Live per-route base fares. If the visitor named a place, give the fares
    for routes touching it; otherwise list the cheapest routes and offer to
    look up a specific one (a follow-up question)."""
    try:
        from .models import Route
        ports = ctx.get("ports") or []
        if ports:
            routes = list(_routes_touching([p["id"] for p in ports]))
            if routes:
                items = [
                    f"• {escape(r.departure_port.name)} → "
                    f"{escape(r.destination_port.name)}: FJ${r.base_fare:.2f}"
                    for r in routes if r.base_fare is not None
                ]
                place = escape(ports[0]["name"])
                return {"reply": (
                    f"Adult base fares for routes via <strong>{place}</strong>:<br>"
                    + "<br>".join(items) + _fare_rules_tail())}

        routes = list(
            Route.objects.select_related("departure_port", "destination_port")
            .exclude(base_fare__isnull=True)
            .order_by("base_fare")[:5]
        )
        if not routes:
            return None
        items = [
            f"• {escape(r.departure_port.name)} → "
            f"{escape(r.destination_port.name)}: FJ${r.base_fare:.2f}"
            for r in routes
        ]
        # No specific route named → answer generally and ASK a follow-up,
        # remembering that we're waiting for a destination.
        return {
            "reply": ("Fares are per the route's adult base fare. Some current "
                      "base fares:<br>" + "<br>".join(items) + _fare_rules_tail()
                      + "<br><br>Want the fare for a particular route? Just tell me "
                      "the destination (e.g. <em>Yasawa</em>)."),
            "pending": {"slot": "route", "intent": "pricing"},
        }
    except Exception:
        return None


def live_my_bookings(ctx):
    """Personalized: a signed-in user's next confirmed trip (and pending ones)."""
    user = ctx.get("user")
    if not user or not getattr(user, "is_authenticated", False):
        return (
            "<a href=\"/accounts/login/\">Log in</a> and I can show your upcoming "
            "trips here. Once signed in, all your tickets live under "
            "<a href=\"/bookings/history/\">My Bookings</a>."
        )
    try:
        from django.utils import timezone
        from .models import Booking
        now = timezone.now()
        upcoming = list(
            Booking.objects.filter(
                user=user, status="confirmed", schedule__departure_time__gte=now
            ).select_related(
                "schedule__route__departure_port", "schedule__route__destination_port",
                "schedule__ferry",
            ).order_by("schedule__departure_time")[:3]
        )
        if upcoming:
            items = []
            for b in upcoming:
                s = b.schedule
                items.append(
                    f"• <strong>{_fmt_dt(s.departure_time)}</strong> — "
                    f"{escape(s.route.departure_port.name)} → "
                    f"{escape(s.route.destination_port.name)} "
                    f"(booking #{b.id})"
                )
            return (
                f"Your next trip{'s' if len(upcoming) > 1 else ''}:<br>"
                + "<br>".join(items)
                + "<br><br>Open <a href=\"/bookings/history/\">My Bookings</a> to "
                "view tickets, modify or cancel."
            )
        pending = Booking.objects.filter(user=user, status="pending").count()
        if pending:
            return (
                f"You have {pending} booking{'s' if pending != 1 else ''} still "
                "awaiting payment. Finish checkout from "
                "<a href=\"/bookings/history/\">My Bookings</a> to confirm your seat."
            )
        return (
            "You don't have any upcoming trips yet. Ready for an island run? "
            "<a href=\"/bookings/book/\">Book a ticket</a> — it takes about a minute."
        )
    except Exception:
        return None


# Each intent: keywords (weighted by specificity), an answer, follow-up chips,
# and optionally a `handler` that returns a live reply (or None to fall back).
def live_modify_policy(ctx):
    """Explain the modification rules using the live constants from modification.py."""
    p = _policy()
    return (
        "Open <a href=\"/bookings/history/\">My Bookings</a> → select the booking → "
        "<em>Modify</em>. You can <strong>add or remove passengers</strong> there.<br><br>"
        f"• Changes close <strong>{p['modify_hours']} hours</strong> before departure.<br>"
        f"• A flat <strong>FJ${p['fee']}</strong> change fee applies whenever the "
        "passenger list changes, on top of the fare difference.<br>"
        "• Each <strong>added adult or child</strong> needs a full name, age and a "
        "photo ID document; <strong>infants</strong> need a date of birth.<br>"
        "• Children and infants must be linked to an adult on the booking.<br>"
        "• Removing passengers refunds the fare drop (the fee still applies).<br><br>"
        "The exact amount is shown before you confirm, and new e-tickets are issued "
        "automatically."
    )


def live_modify_fee(ctx):
    p = _policy()
    return (
        f"Changing the passenger list costs a flat <strong>FJ${p['fee']}</strong> "
        "change fee, plus the difference in fare.<br><br>"
        "• <strong>Adding</strong> someone: you pay the fee + their fare.<br>"
        "• <strong>Removing</strong> someone: you pay the fee, and their fare is "
        "refunded to your original payment method — so you may end up net refunded.<br><br>"
        f"Changes must be made at least <strong>{p['modify_hours']} hours</strong> before "
        "departure. You'll see the exact figure on the "
        "<a href=\"/bookings/history/\">Modify</a> screen before confirming anything."
    )


def live_cancel_policy(ctx):
    return (
        "Open <a href=\"/bookings/history/\">My Bookings</a>, select the booking and "
        "choose <em>Cancel</em>.<br><br>"
        "• Cancellations close <strong>6 hours</strong> before departure.<br>"
        "• Your refund returns to the original payment method.<br>"
        "• Your seats are released straight away for other travellers.<br><br>"
        "Only want to change who's travelling? That's a "
        "<em>modification</em> rather than a cancellation — cheaper, and allowed up "
        f"to {_policy()['modify_hours']} hours before departure."
    )


INTENTS = [
    {
        "name": "my_bookings",
        "keywords": ["my booking", "my bookings", "my trip", "my trips", "my next trip",
                     "upcoming trip", "my reservation", "booking status", "my ticket status",
                     "next trip", "my sailing"],
        "handler": live_my_bookings,
        "answer": (
            "Your tickets and trips live under "
            "<a href=\"/bookings/history/\">My Bookings</a> when you're signed in."
        ),
        "suggestions": ["Show me the next departures", "How do I cancel or get a refund?"],
    },
    {
        "name": "booking_how_to",
        "keywords": ["how do i book", "how to book", "make a booking", "book a ticket",
                     "book ticket", "booking", "book"],
        "answer": (
            "Booking a ticket takes about a minute:<br>"
            "1. Go to <a href=\"/bookings/book/\">Book Now</a>.<br>"
            "2. Choose your route, travel date and departure time.<br>"
            "3. Add passengers (adults, children, infants) and any vehicles, "
            "cargo or add-ons.<br>"
            "4. Review the price, then pay to confirm. Your e-ticket with a QR "
            "code is issued instantly and appears under <em>My Bookings</em>."
        ),
        "suggestions": ["What payment methods can I use?", "What routes do you have?",
                        "Can I bring a vehicle?"],
    },
    {
        "name": "pricing",
        "keywords": ["how much", "price", "pricing", "fare", "fares", "cheap",
                     "expensive", "rate", "how much is"],
        "handler": live_pricing,
        "answer": (
            "Fares are based on the route's base fare per adult:<br>"
            "• <strong>Adults</strong>: full fare<br>"
            "• <strong>Children</strong>: 50% of the adult fare<br>"
            "• <strong>Infants</strong>: 10% of the adult fare<br>"
            "Vehicles, cargo and add-ons are priced on top. The exact total is "
            "always shown on the <a href=\"/bookings/book/\">booking page</a> "
            "before you pay — no hidden fees."
        ),
        "suggestions": ["What routes do you have?", "Can I bring a vehicle?",
                        "What payment methods can I use?"],
    },
    {
        "name": "payment",
        "keywords": ["payment method", "how do i pay", "pay", "payment", "card",
                     "visa", "mastercard", "mpaisa", "m-paisa", "mycash", "anz",
                     "bsp", "mobile money", "checkout"],
        "answer": (
            "You can pay by credit/debit <strong>card</strong>, or with a local "
            "provider: <strong>ANZ</strong>, <strong>BSP</strong>, "
            "<strong>M-PAiSA</strong> or <strong>MyCash</strong>. Pick your "
            "method at checkout. Payment is processed securely and your booking "
            "is confirmed the moment it succeeds. If a payment fails, the seats "
            "stay held briefly so you can try again."
        ),
        "suggestions": ["How do I cancel or get a refund?", "How do I book a ticket?"],
    },
    {
        "name": "cancel_refund",
        "keywords": ["cancel", "cancellation", "refund", "money back", "change my mind"],
        "handler": live_cancel_policy,
        "answer": (
            "To cancel: open <a href=\"/bookings/history/\">My Bookings</a>, "
            "select the booking, and choose <em>Cancel</em>. Cancellations close "
            "<strong>6 hours</strong> before departure — after that, please "
            "contact our team. Refunds go back to your original payment method, "
            "and your seats are released automatically."
        ),
        "suggestions": ["How do I change my booking?", "What is the change fee?"],
    },
    {
        "name": "modify",
        # Phrases score higher than bare words, so "add another passenger to my
        # booking" must out-score the `my_bookings` intent's "my booking".
        "keywords": ["modify", "change my booking", "edit booking",
                     "add a passenger", "add passenger", "add another passenger",
                     "another passenger", "extra passenger", "add someone",
                     "remove a passenger", "remove passenger", "remove someone",
                     "passenger to my booking", "more people", "fewer people",
                     "join the trip", "coming too", "dropped out", "pulled out",
                     "no longer coming", "cant come", "one less", "one more person"],
        "handler": live_modify_policy,
        "answer": (
            "Open <a href=\"/bookings/history/\">My Bookings</a> → select the "
            "booking → <em>Modify</em> to add or remove passengers."
        ),
        "suggestions": ["What is the change fee?", "What documents do I need?",
                        "How do I cancel or get a refund?"],
    },
    {
        "name": "modify_fee",
        "keywords": ["change fee", "modification fee", "admin fee", "amendment fee",
                     "surcharge", "cost to change", "charge to change", "fee to modify",
                     "how much to change", "how much to add a passenger"],
        "handler": live_modify_fee,
        "answer": (
            "Changing the passenger list costs a flat change fee, plus (or minus) "
            "the difference in fare. Reducing passengers still pays the fee, and "
            "the fare drop is refunded to your original payment method."
        ),
        "suggestions": ["How do I change my booking?", "How much do tickets cost?"],
    },
    {
        "name": "modify_deadline",
        "keywords": ["deadline to change", "too late to change", "when can i change",
                     "last minute change", "cutoff", "cut off"],
        "handler": live_modify_policy,
        "answer": (
            "Changes close 24 hours before departure, and cancellations 6 hours "
            "before. Inside those windows the booking is locked so the manifest "
            "and document checks can be finalised — contact our team if you're stuck."
        ),
        "suggestions": ["How do I change my booking?", "How do I cancel or get a refund?"],
    },
    {
        "name": "documents",
        "keywords": ["document", "documents", "what id", "photo id", "upload",
                     "file type", "pdf", "jpg", "png", "file size", "proof of age"],
        "answer": (
            "Every <strong>adult</strong> and <strong>child</strong> needs a photo "
            "ID document uploaded with the booking — a <strong>PDF, JPG or PNG</strong>, "
            "up to <strong>2.5&nbsp;MB</strong>. Adults also need an age, children an "
            "age between 2 and 17. <strong>Infants</strong> (under 2) need a date of "
            "birth instead of a document. The same rules apply when you add a "
            "passenger to an existing booking. Documents are checked by staff before "
            "boarding."
        ),
        "suggestions": ["How do I change my booking?", "Do children need a ticket?"],
    },
    {
        "name": "guest_lookup",
        # "code" alone is too generic — it stole "scan the code at the gate" from
        # ticket_checkin. Likewise a bare "email" belongs to `contact`.
        "keywords": ["find my booking", "lost my ticket", "lost booking",
                     "booked as a guest", "guest booking", "cant find my ticket",
                     "didnt get my ticket", "no account booking", "verification code",
                     "verify my email", "confirmation email", "never got",
                     "didnt receive", "did not receive", "resend"],
        "answer": (
            "If you booked as a guest, use "
            "<a href=\"/bookings/find-booking/\">Find My Booking</a>. Enter the email "
            "you booked with and we'll send a <strong>6-digit code</strong>; entering "
            "it opens your bookings and tickets. The code proves the email is yours — "
            "we never show a booking to anyone who hasn't verified that address. "
            "Codes expire after a few minutes; just request a new one."
        ),
        "suggestions": ["Where are my tickets?", "Create an account"],
    },
    {
        "name": "accessibility",
        "keywords": ["accessibility", "wheelchair", "mobility", "assistance",
                     "special needs", "elderly", "pregnant"],
        "answer": (
            "We want everyone aboard comfortably. Please tell us before you travel "
            "so we can arrange boarding assistance and suitable seating — "
            "<a href=\"mailto:info@fijiferrybooking.com\">info@fijiferrybooking.com</a> "
            "or +679 738 8496. Let staff at the terminal know when you arrive and "
            "they'll help you board first."
        ),
        "suggestions": ["Contact support", "How do I book a ticket?"],
    },
    {
        "name": "pets",
        "keywords": ["pet", "pets", "dog", "cat", "animal", "livestock"],
        "answer": (
            "Pets and livestock aren't part of the standard passenger booking. "
            "Livestock can be carried as <strong>cargo</strong> (it has its own "
            "handling rate), and assistance animals are always welcome. Please "
            "contact our team before travelling so we can arrange it safely: "
            "<a href=\"mailto:info@fijiferrybooking.com\">info@fijiferrybooking.com</a>."
        ),
        "suggestions": ["Can I bring a vehicle?", "Contact support"],
    },
    {
        "name": "arrival_time",
        "keywords": ["how early", "arrive before", "check in time", "how long before",
                     "boarding time", "gate close"],
        "answer": (
            "Please arrive at the terminal <strong>45 minutes</strong> before "
            "departure (an hour if you're bringing a vehicle or cargo, which need "
            "loading time). Have your QR e-ticket and each passenger's ID ready for "
            "the gate. Boarding usually closes 15 minutes before departure."
        ),
        "suggestions": ["Where are my tickets?", "Can I bring a vehicle?"],
    },
    {
        "name": "delays",
        "keywords": ["delay", "delayed", "late", "cancelled sailing", "rough sea",
                     "weather hold", "on time"],
        "answer": (
            "Sailings can be delayed or held when the weather turns — safety comes "
            "first. The <a href=\"/bookings/departures/\">Live Departures</a> board "
            "shows each sailing's current status, and we email you if your sailing "
            "changes. If a sailing is cancelled by us, you're refunded in full or "
            "moved to the next available one."
        ),
        "suggestions": ["What's the weather like?", "Show me the next departures"],
    },
    {
        "name": "privacy_data",
        "keywords": ["privacy", "data", "gdpr", "personal information",
                     "delete my data", "how do you use my"],
        "answer": (
            "We collect only what a sailing needs: your contact details, passenger "
            "names/ages and ID documents for the manifest and boarding checks. "
            "Payments are handled by our payment provider — we never store your card "
            "number. Read the full <a href=\"/privacy_policy/\">Privacy Policy</a> "
            "and <a href=\"/terms_of_service/\">Terms of Service</a>."
        ),
        "suggestions": ["Contact support", "What documents do I need?"],
    },
    {
        "name": "vehicle_cargo",
        "keywords": ["vehicle", "car", "truck", "motorbike", "bike", "cargo",
                     "freight", "luggage", "baggage", "bag", "suitcase"],
        "answer": (
            "Yes — you can add <strong>vehicles</strong> (car, truck, motorbike) "
            "and <strong>cargo</strong> during booking, in the add-ons step. "
            "You'll enter the vehicle type or cargo weight and the fee is added "
            "to your total automatically. Standard personal luggage is included; "
            "extra baggage can be added as an add-on."
        ),
        "suggestions": ["How much do tickets cost?", "How do I book a ticket?"],
    },
    {
        "name": "children_infants",
        "keywords": ["child", "children", "infant", "minor", "unaccompanied minor"],
        "answer": (
            "Children travel at 50% of the adult fare and infants at 10%. Add "
            "them in the passenger step when booking. Note that unaccompanied "
            "minors may require guardian verification before boarding — staff "
            "will check documents at the gate."
        ),
        "suggestions": ["How much do tickets cost?", "How do I book a ticket?"],
    },
    {
        "name": "ticket_checkin",
        "keywords": ["where are my tickets", "e-ticket", "eticket", "ticket",
                     "qr code", "qr", "boarding", "check in", "check-in", "board",
                     "scan", "gate", "download my ticket", "print"],
        "answer": (
            "After payment your e-ticket with a <strong>QR code</strong> is "
            "available immediately under <a href=\"/bookings/history/\">My "
            "Bookings</a> — open the booking and tap <em>View Ticket</em> to show "
            "or download it (PDF). At the terminal, staff scan the QR code to "
            "check you in. No need to print, your phone is fine."
        ),
        "suggestions": ["Show me my bookings", "How do I cancel or get a refund?"],
    },
    {
        "name": "routes_destinations",
        "keywords": ["route", "routes", "destination", "destinations", "where can i go",
                     "islands", "yasawa", "nadi", "denarau", "port", "ports", "island hop"],
        "handler": live_routes,
        "answer": (
            "We sail between Fiji's mainland ports and the islands — including "
            "Nadi / Port Denarau out to the Yasawa Islands. Browse every route, "
            "with photos and times, on the "
            "<a href=\"/bookings/destinations/\">Destinations</a> page, or see "
            "what's leaving soon under <a href=\"/bookings/departures/\">Live "
            "Departures</a>."
        ),
        "suggestions": ["How do I book a ticket?", "Show me the next departures"],
    },
    {
        "name": "live_departures",
        "keywords": ["live departure", "departure", "departures", "schedule", "timetable",
                     "what time", "when does", "next ferry", "leaving", "next sailing"],
        "handler": live_departures,
        "answer": (
            "The <a href=\"/bookings/departures/\">Live Departures</a> page shows "
            "upcoming sailings with their status (scheduled, delayed or "
            "cancelled) and remaining seats, updated in real time. From there you "
            "can jump straight into booking a specific departure."
        ),
        "suggestions": ["What routes do you have?", "What's the weather like?"],
    },
    {
        "name": "weather",
        "keywords": ["weather", "rain", "storm", "wind", "sea condition", "rough",
                     "forecast", "cyclone"],
        "answer": (
            "Sailings can be affected by weather. Live conditions and a forecast "
            "for each port are shown on the route and departures pages. If a "
            "sailing is delayed or cancelled for safety, you'll be notified and "
            "offered a rebooking or refund."
        ),
        "suggestions": ["Show me the next departures", "How do I cancel or get a refund?"],
    },
    {
        "name": "account",
        "keywords": ["account", "register", "sign up", "signup", "log in", "login",
                     "sign in", "password", "reset password", "forgot password",
                     "profile", "create account"],
        "answer": (
            "Creating an account lets you manage bookings, store passenger "
            "details and see your history. <a href=\"/accounts/register/\">Sign "
            "up</a> or <a href=\"/accounts/login/\">log in</a> from the top menu. "
            "Forgot your password? Use the <em>reset password</em> link on the "
            "login page. You can also book as a guest without an account."
        ),
        "suggestions": ["How do I book a ticket?", "Where are my tickets?"],
    },
    {
        "name": "guest_booking",
        "keywords": ["guest", "without account", "without an account", "no account",
                     "do i need an account"],
        "answer": (
            "No account needed — you can book as a <strong>guest</strong> using "
            "just your email. Your e-ticket is emailed to you. Creating an "
            "account later lets you claim guest bookings and manage everything in "
            "one place."
        ),
        "suggestions": ["How do I book a ticket?", "Create an account"],
    },
    {
        "name": "contact",
        "keywords": ["contact", "support", "help desk", "phone", "email", "call",
                     "talk to", "human", "agent", "customer service"],
        "answer": (
            "Our team is here to help: ✉️ "
            "<a href=\"mailto:info@fijiferrybooking.com\">info@fijiferrybooking.com</a> "
            "📞 +679 738 8496. Hours: Mon–Fri 8AM–6PM, Sat–Sun 9AM–5PM. We're at "
            "Port Denarau Marina, Fiji."
        ),
        "suggestions": ["How do I book a ticket?", "How do I cancel or get a refund?"],
    },
    {
        "name": "thanks",
        "keywords": ["thank", "thanks", "cheers", "vinaka", "appreciate"],
        "answer": "You're welcome! 🌴 Safe travels — anything else I can help with?",
        "suggestions": DEFAULT_SUGGESTIONS,
    },
]

GREETING_KEYWORDS = ["hello", "hi", "hey", "bula", "good morning", "good afternoon",
                     "good evening", "yo", "greetings"]

# Vocabulary of single-word keywords, used for typo-tolerant matching.
_VOCAB = sorted({
    kw for intent in INTENTS for kw in intent["keywords"] if " " not in kw and len(kw) > 3
})

# Words that carry no intent signal. Dropped before scoring so "how do i cancel"
# and "cancel" land on the same intent with the same confidence.
_STOPWORDS = frozenset("""
a an the is are was were be been being do does did doing done have has had
i me my we our you your it its they them their this that these those to for
of in on at by with from about as if then than so and or but not no yes
can could will would shall should may might must please just get got need
want like use using there here what when where which who whom whose why how
""".split())

# Negation cues: "I do NOT want to cancel" should not fire the cancel intent
# as confidently as "cancel my booking".
_NEGATIONS = frozenset(["not", "dont", "don't", "doesnt", "doesn't", "never",
                        "without", "cannot", "cant", "can't", "avoid", "instead of"])


def _idf_table():
    """Inverse document frequency over intent keywords.

    Each intent is a "document" of terms. A term appearing in one intent
    (``mpaisa``) is far more diagnostic than one appearing in many (``booking``),
    and IDF captures exactly that — replacing the old flat +1-per-keyword count
    that let common words like "booking" dominate the match.
    """
    import math
    df = {}
    for intent in INTENTS:
        terms = set()
        for kw in intent["keywords"]:
            terms.update(kw.split())
        for t in terms:
            df[t] = df.get(t, 0) + 1
    n = len(INTENTS)
    return {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}


_IDF = _idf_table()
_DEFAULT_IDF = 1.0


def _correct(token):
    """Snap a close-but-unknown token to a known keyword (typo tolerance).

    Cutoff is 0.80, not 0.84: a single transposition in a short word ("cancle"
    → "cancel") scores 0.833, which the stricter threshold silently rejected.
    """
    if len(token) > 4 and token not in _VOCAB:
        match = difflib.get_close_matches(token, _VOCAB, n=1, cutoff=0.80)
        if match:
            return match[0]
    return token


def _normalize(text):
    """Lowercase, strip punctuation, fold synonyms, and correct typos."""
    text = (text or "").lower()
    text = re.sub(r"[^\w\s$-]", " ", text)
    return " ".join(_correct(SYNONYMS.get(t, t)) for t in text.split())


def _terms(text):
    """Content tokens plus adjacent bigrams, for phrase-aware scoring."""
    tokens = [t for t in text.split() if t]
    content = [t for t in tokens if t not in _STOPWORDS]
    bigrams = [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]
    return tokens, content, bigrams


def _negated(tokens, keyword):
    """True when a negation cue appears within 3 tokens before ``keyword``."""
    head = keyword.split()[0]
    for i, tok in enumerate(tokens):
        if tok == head:
            if any(t in _NEGATIONS for t in tokens[max(0, i - 3):i]):
                return True
    return False


def _score(text, keywords):
    """IDF-weighted match score for one intent, normalised to roughly [0, 1+].

    Exact multi-word phrases are the strongest evidence, so they keep a large
    bonus; single content words contribute their IDF. Dividing by the square
    root of the intent's own vocabulary size stops keyword-heavy intents from
    winning purely by having more ways to match.
    """
    import math

    tokens, content, bigrams = _terms(text)
    if not tokens:
        return 0.0

    seen = set(tokens) | set(bigrams)
    score = 0.0

    for kw in keywords:
        if " " in kw:
            if kw in text:  # exact phrase, in order
                if _negated(tokens, kw):
                    continue
                score += 3.0 + 1.5 * kw.count(" ")
            elif kw in seen:  # bigram hit
                score += 2.0
        else:
            if kw in seen and kw not in _STOPWORDS:
                if _negated(tokens, kw):
                    continue
                score += _IDF.get(kw, _DEFAULT_IDF)

    # Normalise by intent breadth so a 15-keyword intent isn't inherently favoured.
    breadth = math.sqrt(max(len(keywords), 1))
    return score / breadth * 2.0


# Intents whose answers depend on a place/route. A bare port name in a
# follow-up ("…Yasawa") is routed back to the most recent one of these.
_ROUTE_AWARE = {"pricing", "live_departures", "routes_destinations"}


def _intent_by_name(name):
    for intent in INTENTS:
        if intent["name"] == name:
            return intent
    return None


#: One canonical question per intent, used to offer "did you mean" chips.
_TOPIC_PROMPTS = {
    "booking_how_to": "How do I book a ticket?",
    "pricing": "How much do tickets cost?",
    "modify": "How do I change my booking?",
    "modify_fee": "What is the change fee?",
    "documents": "What documents do I need?",
    "cancel_refund": "How do I cancel or get a refund?",
    "guest_lookup": "I booked as a guest — where's my ticket?",
    "live_departures": "Show me the next departures",
    "routes_destinations": "What routes do you have?",
    "vehicle_cargo": "Can I bring a vehicle?",
    "weather": "What's the weather like?",
    "arrival_time": "How early should I arrive?",
    "payment": "What payment methods can I use?",
    "contact": "Contact support",
}


def _nearest_topics(text, limit=3):
    """Closest intents by token overlap with their keywords — for 'did you mean'."""
    words = set(text.split())
    if not words:
        return []
    scored = []
    for intent in INTENTS:
        prompt = _TOPIC_PROMPTS.get(intent["name"])
        if not prompt:
            continue
        kw_words = set()
        for kw in intent["keywords"]:
            kw_words.update(kw.split())
        overlap = len(words & kw_words)
        # Fuzzy: catch near-miss spellings the normalizer didn't snap.
        if not overlap:
            for w in words:
                if len(w) > 3 and difflib.get_close_matches(w, kw_words, n=1, cutoff=0.8):
                    overlap = 1
                    break
        if overlap:
            scored.append((overlap, prompt))
    scored.sort(key=lambda p: -p[0])
    return [p for _, p in scored[:limit]]


#: Below this the match is noise; above MARGIN the winner is unambiguous.
_MIN_CONFIDENCE = 0.55
#: If the runner-up is within this ratio of the winner, ask instead of guessing.
_AMBIGUITY_RATIO = 0.82


def _rank_intents(text):
    """All intents scored, best first."""
    ranked = [(intent, _score(text, intent["keywords"])) for intent in INTENTS]
    ranked.sort(key=lambda p: -p[1])
    return ranked


def _match_intent(text):
    """Best-scoring intent for the normalized text (or (None, 0))."""
    ranked = _rank_intents(text)
    if not ranked or ranked[0][1] < _MIN_CONFIDENCE:
        return None, 0
    return ranked[0]


def _ambiguous(ranked):
    """The runner-up is nearly as strong as the winner → clarify, don't guess."""
    if len(ranked) < 2:
        return None
    (top, s1), (second, s2) = ranked[0], ranked[1]
    if s1 >= _MIN_CONFIDENCE and s2 > 0 and (s2 / s1) >= _AMBIGUITY_RATIO:
        return top, second
    return None


def _run_intent(intent, ctx, is_authenticated):
    """Execute one intent → (reply, suggestions, pending).

    A handler may return a plain string, or a dict {reply, suggestions?,
    pending?}; static intents fall back to their 'answer'. `pending` lets a
    handler ask a follow-up question and remember which slot it is waiting on.
    """
    reply, pending = None, None
    suggestions = intent.get("suggestions", DEFAULT_SUGGESTIONS)
    handler = intent.get("handler")
    if handler is not None:
        try:
            out = handler(ctx)
        except Exception:
            out = None
        if isinstance(out, dict):
            reply = out.get("reply")
            pending = out.get("pending")
            suggestions = out.get("suggestions", suggestions)
        elif out:
            reply = out
    if reply is None:
        reply = intent["answer"]
    if intent["name"] in ("cancel_refund", "modify", "ticket_checkin") and not is_authenticated:
        reply += ("<br><br><em>Tip: <a href=\"/accounts/login/\">log in</a> to see "
                  "and manage your existing bookings.</em>")
    return reply, suggestions, pending


def answer(message, user=None, is_authenticated=False, context=None):
    """Return {reply, suggestions, intent, context} for a visitor message.

    `user` powers personalized answers ("my next trip"). `context` carries
    per-session conversation state — the last intent and any pending follow-up
    slot — and is echoed back (updated) so the caller can persist it in the
    session. Fully deterministic and offline.
    """
    if user is not None:
        is_authenticated = getattr(user, "is_authenticated", is_authenticated)
    context = dict(context or {})
    pending = context.get("pending")
    engine_state = context.get("engine") or {}

    def _out(reply, suggestions, intent_name, new_pending=None):
        new_ctx = {"last_intent": intent_name}
        if new_pending:
            new_ctx["pending"] = new_pending
        if engine_state:
            new_ctx["engine"] = engine_state
        return {"reply": reply, "suggestions": suggestions,
                "intent": intent_name, "context": new_ctx}

    raw = (message or "").strip()
    if not raw:
        return _out(GREETING_REPLY, DEFAULT_SUGGESTIONS, "greeting")

    # Checked against the raw text, before synonym folding, so the normalizer
    # can't be used to smuggle a probe past the filter.
    if is_unsafe(raw):
        return _out(SAFETY_REPLY, DEFAULT_SUGGESTIONS, "safety")

    text = _normalize(raw)

    # 0) Task engine: multi-turn slot-filling flows (trip planning, waitlist
    #    joins). Runs before intent matching so an in-progress conversation
    #    ("2 adults", "friday") is understood as an answer, not a new question.
    #    Deterministic and offline, like everything else here.
    try:
        from . import chatbot_engine
        engine_result, engine_state = chatbot_engine.handle(raw, text, context, user=user)
    except Exception:
        engine_result, engine_state = None, engine_state
    if engine_result:
        return _out(engine_result["reply"],
                    engine_result.get("suggestions") or DEFAULT_SUGGESTIONS,
                    engine_result["intent"])

    ports = extract_ports(text)
    ctx = {"user": user, "is_authenticated": is_authenticated, "ports": ports}

    # 1) Follow-up resolution: we asked for a route and the visitor replied with
    #    a place — fulfil the original intent now, with that place.
    if pending and pending.get("slot") == "route" and ports:
        intent = _intent_by_name(pending.get("intent", ""))
        if intent:
            reply, suggestions, new_pending = _run_intent(intent, ctx, is_authenticated)
            return _out(reply, suggestions, intent["name"], new_pending)

    # 2) Greeting — only short, greeting-like messages.
    if len(text.split()) <= 3 and any(
        re.search(r"\b" + re.escape(g) + r"\b", text) for g in GREETING_KEYWORDS
    ):
        return _out(GREETING_REPLY, DEFAULT_SUGGESTIONS, "greeting")

    # 3) Normal intent match, with a confidence floor.
    ranked = _rank_intents(text)
    best, best_score = (ranked[0] if ranked else (None, 0))
    if best_score < _MIN_CONFIDENCE:
        best, best_score = None, 0

    # 3b) Two intents nearly tied — offer both rather than silently picking one.
    tie = _ambiguous(ranked) if best else None
    if tie:
        a, b = tie
        chips = [_TOPIC_PROMPTS.get(a["name"]), _TOPIC_PROMPTS.get(b["name"])]
        chips = [c for c in chips if c]
        if len(chips) == 2:
            return _out(
                "I can help with either of these — which did you mean?",
                chips, "clarify",
            )

    # 4) No intent matched, but a place name + a route-aware last intent → reuse
    #    it ("how much is the fare?" … then just "Yasawa").
    if (best is None or best_score == 0) and ports:
        last = _intent_by_name(context.get("last_intent", ""))
        if last and last["name"] in _ROUTE_AWARE:
            reply, suggestions, new_pending = _run_intent(last, ctx, is_authenticated)
            return _out(reply, suggestions, last["name"], new_pending)

    if best is None or best_score == 0:
        # Nothing matched on keywords. Offer the closest topics by fuzzy overlap
        # instead of a bare apology, so a rephrase is one tap away.
        near = _nearest_topics(text)
        if near:
            return _out(
                "I'm not sure I understood that. Did you mean one of these?",
                near, "clarify",
            )
        return _out(FALLBACK_REPLY, DEFAULT_SUGGESTIONS, "fallback")

    reply, suggestions, new_pending = _run_intent(best, ctx, is_authenticated)
    return _out(reply, suggestions, best["name"], new_pending)
