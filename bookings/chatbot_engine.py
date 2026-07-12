"""Deterministic slot-filling dialog engine for the help assistant.

Level-2 upgrade of the rule-based chatbot: the bot doesn't just answer
questions, it *does* things — plans a trip end-to-end ("book 2 seats Nadi to
Suva on Friday" → real schedule options with live seats, a fare quote for the
exact party, and a pre-filled booking link) and joins waitlists for sold-out
sailings, all through conversation.

Design constraints (inherited from chatbot.py and deliberate):
- Local, offline, zero-cost: no LLM, no API, no network. Pure regex + dates +
  ORM lookups against our own database.
- Deterministic: the same conversation always produces the same replies, so
  flows are unit-testable.
- JSON-safe state: everything the engine remembers between turns lives in a
  small dict the caller persists on the session (see ``handle``).

The engine understands four entity types (route endpoints, travel dates,
party composition, email addresses) and runs multi-turn *tasks*. A task
declares the slots it needs; each user message fills whatever slots it can,
and the engine asks for the next missing one — so "book a ferry" takes three
short turns while "2 adults and a baby to Savusavu tomorrow" finishes in one.
"""
import datetime
import re

from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

WORD_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "couple": 2,
}

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

#: Words that abandon whatever task is in progress. Deliberately does NOT
#: include a bare "cancel" — "cancel my booking" is a real question that the
#: static cancel_refund intent must keep answering.
RESET_PHRASES = ("never mind", "nevermind", "forget it", "start over",
                 "start again", "reset", "stop that")

MAX_PASSENGERS = 20


# --------------------------------------------------------------------------- #
# Entity extraction
# --------------------------------------------------------------------------- #
def _all_ports():
    from .models import Port
    return list(Port.objects.values("id", "name"))


def find_ports(text):
    """Locate port mentions with their text position and any preposition role.

    Returns a list of ``{"id", "name", "pos", "role"}`` sorted by position,
    where role is "origin" ("from Nadi"), "destination" ("to Suva") or None.
    Matches the full port name or any distinctive (>=4 char) word of it.
    """
    hits = []
    try:
        ports = _all_ports()
    except Exception:
        return []
    for p in ports:
        name = (p["name"] or "").lower()
        if not name:
            continue
        pos = -1
        m = re.search(r"\b" + re.escape(name) + r"\b", text)
        if m:
            pos = m.start()
        else:
            for word in re.split(r"[^a-z0-9]+", name):
                if len(word) >= 4:
                    m = re.search(r"\b" + re.escape(word) + r"\b", text)
                    if m:
                        pos = m.start()
                        break
        if pos < 0:
            continue
        prefix = text[max(0, pos - 12):pos]
        role = None
        if re.search(r"\bfrom\s+(?:the\s+)?$", prefix):
            role = "origin"
        elif re.search(r"\b(?:to|into|for)\s+(?:the\s+)?$", prefix):
            role = "destination"
        hits.append({"id": p["id"], "name": p["name"], "pos": pos, "role": role})
    hits.sort(key=lambda h: h["pos"])
    return hits


def extract_route(text):
    """Return ``(origin, destination)`` port dicts (either may be None)."""
    hits = find_ports(text)
    origin = next((h for h in hits if h["role"] == "origin"), None)
    dest = next((h for h in hits if h["role"] == "destination"), None)
    unassigned = [h for h in hits if h is not origin and h is not dest]
    if origin is None and dest is None and len(unassigned) >= 2:
        # "Nadi to Suva" / "Nadi - Suva": positional order decides.
        origin, dest = unassigned[0], unassigned[1]
    elif dest is None and origin is None and len(unassigned) == 1:
        # A lone place name is almost always where they want to go.
        dest = unassigned[0]
    elif origin is not None and dest is None and unassigned:
        dest = unassigned[0]
    elif dest is not None and origin is None and unassigned:
        origin = unassigned[0]
    return origin, dest


def extract_date(text, today=None):
    """Parse a travel date from free text. Returns ``datetime.date`` or None.

    Handles: ISO (2026-07-14), numeric d/m or d/m/y (day-first, as written in
    Fiji), "14 July" / "July 14" (optional year), today / tonight / tomorrow,
    weekday names ("on Friday", "next friday"), and "this weekend".
    """
    today = today or timezone.localdate()
    t = text.lower()

    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    m = re.search(r"\b(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{2,4}))?\b", t)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else today.year
        if year < 100:
            year += 2000
        try:
            d = datetime.date(year, month, day)
            if d < today and not m.group(3):
                d = datetime.date(year + 1, month, day)
            return d
        except ValueError:
            pass

    month_names = "|".join(MONTHS)
    m = (re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + month_names + r")\b(?:\s+(\d{4}))?", t)
         or re.search(r"\b(" + month_names + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:\s+(\d{4}))?", t))
    if m:
        a, b = m.group(1), m.group(2)
        day, month = (int(a), MONTHS[b]) if a.isdigit() else (int(b), MONTHS[a])
        year = int(m.group(3)) if m.group(3) else today.year
        try:
            d = datetime.date(year, month, day)
            if d < today and not m.group(3):
                d = datetime.date(year + 1, month, day)
            return d
        except ValueError:
            pass

    if re.search(r"\btoday\b|\btonight\b", t):
        return today
    if re.search(r"\btomorrow\b|\btmrw?\b", t):
        return today + datetime.timedelta(days=1)
    if re.search(r"\bthis weekend\b|\bweekend\b", t):
        delta = (5 - today.weekday()) % 7  # upcoming Saturday
        return today + datetime.timedelta(days=delta or 7)

    for name, wd in WEEKDAYS.items():
        if re.search(r"\b" + name + r"\b", t):
            delta = (wd - today.weekday()) % 7
            if delta == 0:
                delta = 7  # "on Friday", said on a Friday, means next week
            if re.search(r"\bnext\s+" + name, t) and delta <= 3:
                delta += 7  # "next Mon" said on a Sat means the week after
            return today + datetime.timedelta(days=delta)
    return None


def _num(tok):
    if tok.isdigit():
        return int(tok)
    return WORD_NUMBERS.get(tok)


def extract_party(text, allow_bare_number=False):
    """Parse party composition. Returns {adults, children, infants} or None.

    Recognises "3 people/passengers/seats/pax/tickets", "family of four",
    "2 adults and 1 child", "a baby"… Numbers may be digits or words. With
    ``allow_bare_number`` (used when the bot just asked "how many?"), a lone
    "3" counts as 3 adults.
    """
    t = text.lower()
    party = {"adults": 0, "children": 0, "infants": 0}
    found = False

    num = r"(\d{1,2}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|couple(?:\s+of)?)"

    def n(tok):
        return _num(tok.split()[0]) or 0

    for m in re.finditer(num + r"\s+adults?\b", t):
        party["adults"] += n(m.group(1)); found = True
    for m in re.finditer(num + r"\s+(?:child(?:ren)?|kids?|minors?)\b", t):
        party["children"] += n(m.group(1)); found = True
    for m in re.finditer(num + r"\s+(?:infants?|bab(?:y|ies)|toddlers?)\b", t):
        party["infants"] += n(m.group(1)); found = True

    if not found:
        # "a ticket" / "a seat" is phrasing, not a headcount — require a real
        # number for the generic nouns ("how do I book a ticket?" must not
        # start a trip-planning dialog).
        num_strict = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|couple(?:\s+of)?)"
        m = (re.search(num_strict + r"\s+(?:people|persons?|passengers?|pax|seats?|tickets?|travellers?|travelers?)\b", t)
             or re.search(r"\bfamily of\s+" + num, t)
             or re.search(r"\bparty of\s+" + num, t))
        if m:
            party["adults"] = n(m.group(1)); found = True
    if not found and re.search(r"\bjust me\b|\bby myself\b|\bsolo\b|\balone\b", t):
        party["adults"] = 1; found = True
    if not found and allow_bare_number:
        m = re.fullmatch(r"\s*(\d{1,2})\s*", t)
        if m:
            party["adults"] = int(m.group(1)); found = True

    if not found:
        return None
    total = party["adults"] + party["children"] + party["infants"]
    if not 1 <= total <= MAX_PASSENGERS:
        return None
    if party["adults"] == 0 and (party["children"] or party["infants"]):
        party["adults"] = 1  # children can't sail alone; assume one adult
    return party


def extract_email(raw_text):
    m = EMAIL_RE.search(raw_text or "")
    return m.group(0).lower() if m else None


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #
def _fmt_dt(dt):
    try:
        return timezone.localtime(dt).strftime("%a %d %b, %H:%M")
    except Exception:
        return dt.strftime("%a %d %b, %H:%M")


def _party_total(slots):
    return (slots.get("adults") or 1) + (slots.get("children") or 0) + (slots.get("infants") or 0)


def _party_text(slots):
    bits = []
    a, c, i = slots.get("adults"), slots.get("children") or 0, slots.get("infants") or 0
    if a is None:
        return "1 adult"
    bits.append(f"{a} adult{'s' if a != 1 else ''}")
    if c:
        bits.append(f"{c} child{'ren' if c != 1 else ''}")
    if i:
        bits.append(f"{i} infant{'s' if i != 1 else ''}")
    return ", ".join(bits)


def _fare_for(slots, schedule):
    try:
        from .pricing import calculate_passenger_price
        fare = calculate_passenger_price(
            slots.get("adults") or 1, slots.get("children") or 0,
            slots.get("infants") or 0, schedule,
        )
        return f"FJ${fare:.2f}"
    except Exception:
        return None


def _book_url(schedule_id, slots):
    return (f"{reverse('bookings:book_ticket')}?schedule_id={schedule_id}"
            f"&passengers={_party_total(slots)}")


# --------------------------------------------------------------------------- #
# plan_trip task
# --------------------------------------------------------------------------- #
PLAN_TRIGGERS = (
    "book", "travel", "sail", "ferry to", "go to", "going to", "get to",
    "trip to", "take a ferry", "take the ferry", "plan", "crossing to",
    "need to be in", "heading to", "want to go",
)

WAITLIST_TRIGGERS = ("waitlist", "wait list", "notify me", "let me know when",
                     "when seats open", "seats open up")


def _fill_plan_slots(slots, raw, text, awaiting=None):
    """Merge everything extractable from this message into the task's slots."""
    origin, dest = extract_route(text)
    if awaiting == "origin" and dest and not origin:
        # The bot asked "where from?" — a lone place name answers that.
        origin, dest = dest, None
    if origin and (awaiting == "origin" or not slots.get("origin_id")):
        slots["origin_id"], slots["origin"] = origin["id"], origin["name"]
    if dest and (awaiting == "destination" or not slots.get("destination_id")):
        # Don't let the destination silently overwrite the origin.
        if dest["id"] != slots.get("origin_id"):
            slots["destination_id"], slots["destination"] = dest["id"], dest["name"]

    d = extract_date(raw)
    if d:
        slots["date"] = d.isoformat()

    party = extract_party(text, allow_bare_number=(awaiting == "party"))
    if party:
        slots.update(party)
    return slots


def _resolve_route(slots):
    """Fill the missing endpoint from the route table where unambiguous.

    Returns (route, ask) — ``route`` when resolved, or ``ask`` as a dict
    {"reply", "suggestions", "await"} when the engine needs more input.
    """
    from .models import Route

    qs = Route.objects.select_related("departure_port", "destination_port")
    o, d = slots.get("origin_id"), slots.get("destination_id")

    if o and d:
        route = qs.filter(departure_port_id=o, destination_port_id=d).first()
        if route:
            return route, None
        # No such sailing — check the reverse before giving up.
        rev = qs.filter(departure_port_id=d, destination_port_id=o).first()
        if rev:
            slots["origin_id"], slots["destination_id"] = d, o
            slots["origin"], slots["destination"] = slots["destination"], slots["origin"]
            return rev, None
        return None, {
            "reply": (f"I'm sorry — we don't currently sail between "
                      f"<strong>{escape(slots['origin'])}</strong> and "
                      f"<strong>{escape(slots['destination'])}</strong>. "
                      "You can see every route we operate on the "
                      "<a href=\"/bookings/destinations/\">Destinations</a> page."),
            "suggestions": ["What routes do you have?"],
            "done": True,
        }

    if d and not o:
        candidates = list(qs.filter(destination_port_id=d)[:8])
        if len(candidates) == 1:
            r = candidates[0]
            slots["origin_id"], slots["origin"] = r.departure_port_id, r.departure_port.name
            return r, None
        if candidates:
            names = sorted({r.departure_port.name for r in candidates})
            return None, {
                "reply": (f"We sail to <strong>{escape(slots['destination'])}</strong> from "
                          f"{len(names)} port{'s' if len(names) != 1 else ''} — "
                          "where are you departing from?"),
                "suggestions": [f"From {n}" for n in names[:4]],
                "await": "origin",
            }
        return None, {
            "reply": (f"I couldn't find a route to <strong>{escape(slots['destination'])}</strong>. "
                      "Browse everywhere we sail on the "
                      "<a href=\"/bookings/destinations/\">Destinations</a> page."),
            "suggestions": ["What routes do you have?"],
            "done": True,
        }

    if o and not d:
        candidates = list(qs.filter(departure_port_id=o)[:8])
        if len(candidates) == 1:
            r = candidates[0]
            slots["destination_id"], slots["destination"] = r.destination_port_id, r.destination_port.name
            return r, None
        if candidates:
            names = sorted({r.destination_port.name for r in candidates})
            return None, {
                "reply": (f"From <strong>{escape(slots['origin'])}</strong> you can sail to "
                          + ", ".join(escape(n) for n in names[:6])
                          + ". Where would you like to go?"),
                "suggestions": [f"To {n}" for n in names[:4]],
                "await": "destination",
            }

    return None, {
        "reply": "Happy to help you plan a crossing! Where would you like to go?",
        "suggestions": [],
        "await": "destination",
    }


def _finish_plan_trip(slots, user):
    """Route + (optional) date + party are known — show real bookable options."""
    from .models import Route, Schedule

    route = (Route.objects.select_related("departure_port", "destination_port")
             .filter(departure_port_id=slots["origin_id"],
                     destination_port_id=slots["destination_id"]).first())
    if route is None:
        return {"reply": "That route seems to have just changed — please try again.",
                "suggestions": ["What routes do you have?"], "done": True}

    now = timezone.now()
    total = _party_total(slots)
    qs = (Schedule.objects.select_related("ferry")
          .filter(route=route, status="scheduled", departure_time__gt=now)
          .order_by("departure_time"))

    date_txt = ""
    if slots.get("date"):
        day = datetime.date.fromisoformat(slots["date"])
        start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
        end = start + datetime.timedelta(days=1)
        day_qs = qs.filter(departure_time__range=(start, end))
        date_txt = f" on <strong>{day.strftime('%A %d %b')}</strong>"
        if not day_qs.exists():
            nxt = list(qs[:3])
            if not nxt:
                return {"reply": (f"There are no upcoming sailings{date_txt} — or any other day — for "
                                  f"{escape(route.departure_port.name)} → {escape(route.destination_port.name)} "
                                  "right now. Schedules update daily, so please check back soon."),
                        "suggestions": ["Show me the next departures"], "done": True}
            items = "<br>".join(
                f"• <strong>{_fmt_dt(s.departure_time)}</strong> — {escape(s.ferry.name)}"
                for s in nxt)
            return {"reply": (f"No sailings{date_txt} for "
                              f"<strong>{escape(route.departure_port.name)} → "
                              f"{escape(route.destination_port.name)}</strong>, but the next departures are:"
                              f"<br>{items}<br><br>Tell me a different date, or say "
                              "<em>book the first one</em>."),
                    "suggestions": ["Book the first one", "Show me the next departures"],
                    "await": "date", "offer_first": nxt[0].id}
        qs = day_qs

    open_options = [s for s in qs if s.available_seats >= total][:3]
    if not open_options:
        full = qs.first()
        if full is None:
            return {"reply": (f"There are no upcoming sailings for "
                              f"{escape(route.departure_port.name)} → {escape(route.destination_port.name)} "
                              "right now. Schedules update daily, so please check back soon."),
                    "suggestions": ["Show me the next departures"], "done": True}
        return {"reply": (f"The {escape(route.departure_port.name)} → "
                          f"{escape(route.destination_port.name)} sailing{date_txt} is "
                          f"<strong>fully booked</strong> for {_party_text(slots)} "
                          f"({full.available_seats} seat{'s' if full.available_seats != 1 else ''} left). "
                          "I can put you on the <strong>waitlist</strong> and we'll email you the "
                          "moment seats open up — just say the word."),
                "suggestions": ["Join the waitlist", "Try a different date"],
                "offer_schedule_id": full.id, "done": True}

    lines = []
    for s in open_options:
        fare = _fare_for(slots, s)
        fare_txt = f" — <strong>{fare}</strong> for {_party_text(slots)}" if fare else ""
        lines.append(
            f"• <strong>{_fmt_dt(s.departure_time)}</strong> — {escape(s.ferry.name)} "
            f"({s.available_seats} seats left){fare_txt} "
            f"→ <a href=\"{_book_url(s.id, slots)}\">Book this sailing</a>")
    heading = (f"Here's what I found for <strong>{escape(route.departure_port.name)} → "
               f"{escape(route.destination_port.name)}</strong>{date_txt}, {_party_text(slots)}:")
    return {"reply": heading + "<br>" + "<br>".join(lines)
            + "<br><br>The booking page opens with your passenger count pre-filled — "
              "you'll just add names and pay.",
            "suggestions": ["What documents do I need?", "What's the weather like?"],
            "done": True, "offer_schedule_id": open_options[0].id}


# --------------------------------------------------------------------------- #
# join_waitlist task
# --------------------------------------------------------------------------- #
def _run_join_waitlist(state, raw, user):
    """Join the waitlist for the sailing most recently discussed."""
    from .models import Schedule
    from . import waitlist as waitlist_svc

    sched_id = state.get("offer_schedule_id")
    if not sched_id:
        return {"reply": ("Waitlists are per sailing — tell me the trip first "
                          "(e.g. <em>2 seats Nadi to Suva on Friday</em>) and if it's "
                          "full I'll offer you the waitlist, or use the "
                          "<a href=\"/bookings/departures/\">Live Departures</a> board."),
                "suggestions": ["Show me the next departures"], "done": True}

    schedule = Schedule.objects.filter(
        pk=sched_id, status="scheduled", departure_time__gt=timezone.now()
    ).select_related("route__departure_port", "route__destination_port").first()
    if schedule is None:
        return {"reply": "That sailing is no longer accepting waitlist entries — it may have departed.",
                "suggestions": ["Show me the next departures"], "done": True}

    email = extract_email(raw)
    if not email and user is not None and getattr(user, "is_authenticated", False):
        email = (user.email or "").lower() or None
    if not email:
        return {"reply": "Sure — what email address should we notify when seats open up?",
                "suggestions": [], "await": "email"}

    seats = _party_total(state.get("slots") or {})
    if schedule.available_seats >= seats:
        return {"reply": (f"Good news — that sailing now has "
                          f"{schedule.available_seats} seats available, so you can "
                          f"<a href=\"{_book_url(schedule.id, state.get('slots') or {})}\">book it right now</a> "
                          "instead of waiting!"),
                "suggestions": [], "done": True}

    try:
        entry, created = waitlist_svc.join_waitlist(schedule, email, seats, user=user)
    except Exception:
        return {"reply": ("Something went wrong joining the waitlist — please try again, or use the "
                          "sold-out sailing's <em>Join waitlist</em> button on the "
                          "<a href=\"/bookings/departures/\">Live Departures</a> page."),
                "suggestions": [], "done": True}

    route_txt = (f"{escape(schedule.route.departure_port.name)} → "
                 f"{escape(schedule.route.destination_port.name)}")
    if created:
        reply = (f"Done! ✅ You're on the waitlist for the "
                 f"<strong>{_fmt_dt(schedule.departure_time)}</strong> {route_txt} sailing "
                 f"({seats} seat{'s' if seats != 1 else ''}). We'll email "
                 f"<strong>{escape(email)}</strong> the moment seats open up.")
    else:
        reply = (f"You're already on the waitlist for that {route_txt} sailing — "
                 f"we'll email <strong>{escape(email)}</strong> as soon as seats open up.")
    return {"reply": reply, "suggestions": ["Show me the next departures"], "done": True}


# --------------------------------------------------------------------------- #
# Engine entry point
# --------------------------------------------------------------------------- #
def _wants_plan(text):
    return any(trig in text for trig in PLAN_TRIGGERS)


def _wants_waitlist(text):
    return any(trig in text for trig in WAITLIST_TRIGGERS)


def _next_ask(state):
    """After filling slots, either ask for what's still missing or finish."""
    slots = state["slots"]
    route, ask = _resolve_route(slots)
    if ask:
        return ask
    if not slots.get("adults"):
        return {"reply": (f"<strong>{escape(slots['origin'])} → {escape(slots['destination'])}</strong> — "
                          "great choice! How many of you are travelling? "
                          "(e.g. <em>2 adults and 1 child</em>)"),
                "suggestions": ["Just me", "2 adults", "2 adults and 2 children"],
                "await": "party"}
    return None  # ready to finish


def handle(raw, text, context, user=None):
    """Run one engine turn. Returns (result, engine_ctx).

    ``result`` is None when the engine has nothing to say (the caller falls
    back to intent matching); otherwise a dict with ``reply``, ``suggestions``
    and ``intent``. ``engine_ctx`` is the JSON-safe state to persist — an empty
    dict clears it.
    """
    state = dict(context.get("engine") or {})
    state.setdefault("slots", {})

    # A conversational eject seat — always available.
    if any(p in text for p in RESET_PHRASES):
        if state.get("task"):
            return ({"reply": "No problem — I've cleared that. What else can I help with?",
                     "suggestions": None, "intent": "engine_reset"}, {})
        return None, {}

    awaiting = state.get("await")
    active = state.get("task")

    # ----- explicit new-task triggers --------------------------------------
    if _wants_waitlist(text):
        state["task"] = "join_waitlist"
        state.pop("await", None)
        return _step_waitlist(state, raw, user)

    origin, dest = extract_route(text)
    date = extract_date(raw)
    party = extract_party(text)
    has_entities = bool(origin or dest or date or party)

    if _wants_plan(text) and has_entities and active != "plan_trip":
        state = {"task": "plan_trip", "slots": {}}
        _fill_plan_slots(state["slots"], raw, text)
        return _step_plan(state, user)

    # "book the first one" after we listed alternative departures.
    if state.get("offer_first") and re.search(r"\b(first|that) one\b|\bbook the first\b", text):
        sid = state.pop("offer_first")
        slots = state.get("slots") or {}
        return ({"reply": (f"Perfect — <a href=\"{_book_url(sid, slots)}\">here's the booking page "
                           f"for that sailing</a>, pre-filled for {_party_text(slots)}."),
                 "suggestions": ["What documents do I need?"], "intent": "engine_plan_trip"},
                {})

    # ----- continue an active task ------------------------------------------
    if active == "plan_trip":
        before = dict(state["slots"])
        _fill_plan_slots(state["slots"], raw, text, awaiting=awaiting)
        filled_something = state["slots"] != before
        if not filled_something and not has_entities:
            # The user changed the subject — get out of the way, but keep any
            # waitlist offer alive so "join the waitlist" still works later.
            return None, _carry_offers(state)
        state.pop("await", None)
        return _step_plan(state, user)

    if active == "join_waitlist":
        if awaiting == "email" and not extract_email(raw):
            # Changed the subject — drop the ask but keep the offer alive so
            # "join the waitlist" still works later.
            keep = {}
            if state.get("offer_schedule_id"):
                keep["offer_schedule_id"] = state["offer_schedule_id"]
            return None, keep
        return _step_waitlist(state, raw, user)

    # No task, no trigger — carry forward any standing offer and stay silent.
    return None, _carry_offers(state)


def _carry_offers(state):
    """Persist only long-lived context (waitlist offer), dropping dead tasks."""
    keep = {}
    if state.get("offer_schedule_id"):
        keep["offer_schedule_id"] = state["offer_schedule_id"]
    if state.get("task") and not state.get("done"):
        keep.update({k: v for k, v in state.items() if k != "done"})
    return keep


def _step_plan(state, user):
    ask = _next_ask(state)
    if ask is None:
        result = _finish_plan_trip(state["slots"], user)
    else:
        result = ask
    return _pack(state, result, "engine_plan_trip")


def _step_waitlist(state, raw, user):
    result = _run_join_waitlist(state, raw, user)
    return _pack(state, result, "engine_waitlist")


def _pack(state, result, intent):
    """Convert a step result into (reply-dict, persisted-context)."""
    if result.get("done"):
        new_state = {}
        if result.get("offer_schedule_id"):
            new_state["offer_schedule_id"] = result["offer_schedule_id"]
            # Remember the party so a follow-up waitlist join requests the
            # right number of seats.
            slots = state.get("slots") or {}
            party = {k: slots[k] for k in ("adults", "children", "infants") if slots.get(k)}
            if party:
                new_state["slots"] = party
    else:
        state["await"] = result.get("await")
        for key in ("offer_schedule_id", "offer_first"):
            if result.get(key):
                state[key] = result[key]
        new_state = state
    return ({"reply": result["reply"],
             "suggestions": result.get("suggestions") or None,
             "intent": intent}, new_state)
