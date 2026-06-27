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
    "What routes do you have?",
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
    "fee": "fare", "fees": "fare", "charge": "fare", "cost": "fare",
    "tix": "ticket", "reservation": "booking", "buy": "book",
}


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
        "answer": (
            "To cancel: open <a href=\"/bookings/history/\">My Bookings</a>, "
            "select the booking, and choose <em>Cancel</em>. Any refund is "
            "calculated according to the cancellation policy shown on your "
            "ticket (it depends on how close to departure you cancel). Confirmed "
            "refunds are returned to your original payment method."
        ),
        "suggestions": ["How do I change my booking?", "Where are my tickets?"],
    },
    {
        "name": "modify",
        "keywords": ["modify", "change my booking", "reschedule", "change date",
                     "change time", "edit booking", "different ferry"],
        "answer": (
            "You can change an upcoming booking from "
            "<a href=\"/bookings/history/\">My Bookings</a> → select it → "
            "<em>Modify</em>. You can update the departure or passenger details "
            "subject to seat availability on the new sailing. Any price "
            "difference is shown before you confirm."
        ),
        "suggestions": ["How do I cancel or get a refund?", "Show me the next departures"],
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
                     "qr code", "qr", "boarding", "check in", "check-in", "board"],
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


def _normalize(text):
    """Lowercase, strip punctuation, and fold synonyms to canonical terms."""
    text = (text or "").lower()
    text = re.sub(r"[^\w\s$-]", " ", text)
    tokens = [SYNONYMS.get(t, t) for t in text.split()]
    # Light typo correction: snap close-but-unknown tokens to a known keyword.
    corrected = []
    for t in tokens:
        if len(t) > 4 and t not in _VOCAB:
            match = difflib.get_close_matches(t, _VOCAB, n=1, cutoff=0.84)
            corrected.append(match[0] if match else t)
        else:
            corrected.append(t)
    return " ".join(corrected)


def _score(text, keywords):
    """Score how strongly `text` matches an intent's keywords.

    Longer/multi-word keywords are weighted higher (more specific). Single
    words match on word boundaries to avoid false hits inside other words.
    """
    score = 0
    for kw in keywords:
        if " " in kw:
            if kw in text:
                score += 3 + kw.count(" ")  # phrases are strong signals
        else:
            if re.search(r"\b" + re.escape(kw) + r"\b", text):
                score += 1
    return score


# Intents whose answers depend on a place/route. A bare port name in a
# follow-up ("…Yasawa") is routed back to the most recent one of these.
_ROUTE_AWARE = {"pricing", "live_departures", "routes_destinations"}


def _intent_by_name(name):
    for intent in INTENTS:
        if intent["name"] == name:
            return intent
    return None


def _match_intent(text):
    """Best-scoring intent for the normalized text (or (None, 0))."""
    best, best_score = None, 0
    for intent in INTENTS:
        s = _score(text, intent["keywords"])
        if s > best_score:
            best, best_score = intent, s
    return best, best_score


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

    def _out(reply, suggestions, intent_name, new_pending=None):
        new_ctx = {"last_intent": intent_name}
        if new_pending:
            new_ctx["pending"] = new_pending
        return {"reply": reply, "suggestions": suggestions,
                "intent": intent_name, "context": new_ctx}

    raw = (message or "").strip()
    if not raw:
        return _out(GREETING_REPLY, DEFAULT_SUGGESTIONS, "greeting")

    text = _normalize(raw)
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

    # 3) Normal intent match.
    best, best_score = _match_intent(text)

    # 4) No intent matched, but a place name + a route-aware last intent → reuse
    #    it ("how much is the fare?" … then just "Yasawa").
    if (best is None or best_score == 0) and ports:
        last = _intent_by_name(context.get("last_intent", ""))
        if last and last["name"] in _ROUTE_AWARE:
            reply, suggestions, new_pending = _run_intent(last, ctx, is_authenticated)
            return _out(reply, suggestions, last["name"], new_pending)

    if best is None or best_score == 0:
        return _out(FALLBACK_REPLY, DEFAULT_SUGGESTIONS, "fallback")

    reply, suggestions, new_pending = _run_intent(best, ctx, is_authenticated)
    return _out(reply, suggestions, best["name"], new_pending)
