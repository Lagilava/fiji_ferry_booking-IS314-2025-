# Architecture & Design Notes

This document explains *how* the Fiji Ferry Booking System stays correct under
concurrency, money movement, and unreliable networks. It's written for engineers
(and interviewers) who want the reasoning behind the code, not just a feature list.

## Guiding principle: a single authoritative service layer

Every operation that touches **money** or **inventory** lives in
[`bookings/services.py`](../bookings/services.py). Views map HTTP → service calls
and render responses; they never mutate `Booking.status`, `Payment.payment_status`,
or `Schedule.available_seats` directly. This gives us one place to reason about
correctness.

```
HTTP view  ──►  services.py  ──►  models / DB
(input only)    (locks, atomicity,   (constraints as
                idempotency, state    a backstop)
                 transitions)
```

## Concurrency: no overbooking, no double-refunds

Seat, vehicle-slot and cargo-weight reservations all take a **row-level lock** on
the affected `Schedule` and mutate inventory with atomic `F()` expressions:

```python
locked = Schedule.objects.select_for_update().get(pk=schedule_id)
if locked.available_seats < qty:
    return False
Schedule.objects.filter(pk=schedule_id).update(available_seats=F('available_seats') - qty)
```

Two concurrent bookings for the last seat **serialize on the locked row**, so only
one can pass the availability check. Under READ COMMITTED (the InnoDB/Postgres
default) or stricter, overbooking is impossible.

As a final backstop, the database itself refuses to go negative:

```python
constraints = [
    models.CheckConstraint(check=models.Q(available_seats__gte=0),
                           name='schedule_available_seats_non_negative'),
    # …vehicle slots, cargo kg…
]
```

Even if a future code path bypassed the service layer, the DB would reject the
oversell.

## Idempotency: safe against retries and webhook re-delivery

Stripe delivers webhooks *at least once*, and users refresh success pages. Both
payment confirmation and refunds are therefore idempotent:

- **Confirmation** keys off a unique `(booking, session_id)` `Payment` row via
  `get_or_create`. Calling it twice confirms once.
- **Refunds** pass a stable `idempotency_key=f"ferry-refund-{booking.id}"`, so a
  retried cancellation collapses into a single Stripe refund.
- **Cancellation** checks the booking's terminal state *under lock* and returns
  `changed=False` on the second call.

## Booking state machine

Illegal transitions are rejected centrally, so there's no path to a bad state:

```
pending ──► confirmed ──► cancelled
   │                          ▲
   └──────────────────────────┘
(cancelled is terminal; cancelled → confirmed raises InvalidTransition)
```

## Disruption broadcast

`services.disrupt_schedule(schedule_id, kind, do_refund=True)` is the "big red
button" for operations. For a cancellation it:

1. Locks and flips the `Schedule` to `cancelled`.
2. Cancels **and refunds** every active booking via the idempotent
   `cancel_booking()` — releasing seats/vehicles/cargo and voiding tickets.
3. Fans out email **and** SMS/WhatsApp to each passenger, with a free one-click
   rebooking offer to the next suitable sailing.

For a delay or weather-hold the bookings are left intact and only notifications go
out. The whole thing is idempotent and safe to retry — already-cancelled bookings
are skipped, and refunds are keyed.

## Notifications: multi-channel, best-effort

`notifications.py` (email) and `sms.py` (Twilio SMS + WhatsApp) are **best-effort
by contract** — a failure is logged and swallowed, never propagated. A down SMTP
server or missing Twilio config must not break a booking cancellation or a Celery
task. SMS quietly no-ops when unconfigured, so dev and CI never send real messages.

Phone numbers are normalised to E.164 with a configurable default country
(`SMS_DEFAULT_COUNTRY_CODE`, defaulting to Fiji's +679), so locally-entered numbers
still resolve to a sendable address.

## Real-time updates

Django Channels pushes schedule/seat/booking/ticket changes over WebSockets to two
audiences: the customer live-departures view and the admin control hub. Redis is
the channel layer. When Redis or the socket is unavailable, the frontends fall back
to periodic polling, so the UI degrades rather than breaks.

## Weather-aware operations

`scheduling.py` evaluates live route weather against configurable thresholds
(`WEATHER_HOLD_WIND_KMH`, `WEATHER_HOLD_PRECIP_PCT`) and moves upcoming sailings to
a **`weather_hold`** status (non-bookable, flagged for staff review). Sailings are
never auto-cancelled — a human always makes the final call, from the Operations
dashboard.

## Boarding / check-in

Each passenger gets a `Ticket` with a unique QR token. Gate staff scan tickets in
the admin; a ticket moves `active → boarding → used`. The **Boarding board**
aggregates these into a live "X of Y checked in" per departure, auto-refreshing
every few seconds — giving crew a real headcount against capacity before departure.

## Testing strategy

The suite runs **fully offline**: Stripe and email are mocked, and channels use an
in-memory layer (`ferry_system/test_settings.py`). Coverage spans the state machine,
seat-inventory concurrency (including `TransactionTestCase` race tests), payment and
refund tiers, the disruption broadcast, SMS routing/normalisation, weather holds,
and API authorization boundaries.

```bash
python manage.py test bookings --settings=ferry_system.test_settings
```
