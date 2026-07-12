# Fiji Ferry Booking System

> A production-grade, real-time ferry reservation and fleet-operations platform for inter-island travel in Fiji — online booking, Stripe payments, QR boarding passes, live schedules, automated refunds, weather-aware operations, and a full operations control centre for staff.

Built with **Django 5**, **Django Channels (WebSockets)**, **Celery**, **PostgreSQL/MySQL**, **Redis**, and **Stripe**. Designed for the realities of the Fiji market: intermittent connectivity, mobile-first travellers, and safety-critical maritime operations.

<p align="center">
  <img src="docs/screenshots/homepage.png" alt="Fiji Ferry homepage with live departures, weather and trip search" width="80%">
</p>

---

## Highlights

| | |
|---|---|
| **End-to-end booking** | Multi-step wizard (schedule, passengers, add-ons, review), guest & account checkout, vehicles + cargo, group bookings, unaccompanied minors |
| **Real payments** | Stripe Checkout + webhooks, plus mock Fiji-local rails (ANZ, BSP, M-PAiSA, MyCash). **Idempotent** confirmation safe against webhook re-delivery |
| **Automated refunds** | Tiered, time-based cancellation policy with **idempotent Stripe refunds** and a full payment audit trail |
| **SMS / WhatsApp alerts** | Disruption, cancellation and boarding notifications over Twilio — because in Fiji, SMS reaches travellers when email doesn't |
| **One-button disruption broadcast** | Cancel a sailing, auto-cancel + refund every booking, notify all passengers (email + SMS), offer free one-click rebooking |
| **Live boarding board** | Gate-side "X of Y checked in" per departure, auto-refreshing, driven by QR ticket scans |
| **Real-time updates** | WebSocket-pushed schedule/seat/booking updates to both the customer site and the admin control hub, with a polling fallback |
| **Weather-aware ops** | Live route weather; sailings auto-flagged to *weather hold* when wind/precipitation breach safety thresholds |
| **Ops automation** | Auto-scheduler (fleet turnaround, berth & maintenance constraints), waitlist engine, offline self-test agent, server monitor |
| **QR boarding passes** | Per-passenger tickets with unique QR tokens, PDF generation, and admin-side scan validation |

---

## Screenshots

### Customer experience
| Homepage & live search | Booking wizard | Live departures |
|---|---|---|
| ![Homepage](docs/screenshots/homepage.png) | ![Booking flow](docs/screenshots/booking-flow.png) | ![Live departures](docs/screenshots/live-departures.png) |

| Destinations | Mobile (PWA-installable) |
|---|---|
| ![Destinations](docs/screenshots/destinations.png) | <img src="docs/screenshots/homepage-mobile.png" width="260"> |

### Operations control centre (staff)
| Control Hub dashboard | Live boarding board |
|---|---|
| ![Admin dashboard](docs/screenshots/admin-dashboard.png) | ![Boarding board](docs/screenshots/boarding-board.png) |

| Operations dashboard | Departure manifest |
|---|---|
| ![Ops dashboard](docs/screenshots/ops-dashboard.png) | ![Manifest](docs/screenshots/manifest.png) |

---

## Customer flows

Everything a traveller can do, end to end. Guests can book without an account;
signing in simply remembers their history and skips the per-booking email check.

### 1. Discover & plan

- **Homepage** (`/`) — animated hero with a **trip search** (from, to, date, passengers), a **live "next departures"** strip (seats remaining, fare, and current route weather, pushed over WebSockets), popular-route shortcuts, and an installable **PWA** prompt for offline-friendly mobile use.
- **Live departures** (`/bookings/departures/`) — a full real-time board of upcoming sailings with status (scheduled / delayed / weather hold), seats left, and weather; updates without a page refresh.
- **Destinations** (`/bookings/destinations/`) — island/route guide with an interactive map.
- **Assistant** (chat widget, `/bookings/api/assistant/`) — a trip-planning chatbot that answers routes, fares, baggage, and **live** cancellation/modification policy questions (it reads the real policy settings, so it can never quote a stale fee).

### 2. Create an account (optional)

- **Register** (`/accounts/register/`) — creates an account and sends a **welcome + email-verification** link. Travellers can book immediately; verification just confirms ownership.
- **Verify email** (`/accounts/verify-email/<token>/`) — one-click confirmation from the email.
- **Login / logout** (`/accounts/login/`, `/accounts/logout/`).
- **Password reset** — standard four-step flow (request form, email sent, confirm via token link, complete).
- **Profile** (`/accounts/profile/`) — name, phone number (used for SMS alerts), and preferences.

### 3. Book a sailing — the 4-step wizard (`/bookings/book/`)

A single guided wizard with client- and server-side validation at each step (`/bookings/api/validate_step/`):

1. **Schedule** — pick a departure. Availability is checked live, and sold-out sailings offer the **waitlist** instead.
2. **Passengers** — add adults, children and infants with the rules enforced (adults 18+, children 2–17, infants under 2; children/infants need an accompanying adult unless flagged as an **unaccompanied minor**). Upload ID **documents** for adults/children, add **contact phone numbers**, designate a **group leader** for group bookings, and optionally add **vehicles** (car/motorcycle/bicycle) and **cargo** (weight-checked against vessel capacity).
   - **Guest checkout**: guests verify their email with a one-time **OTP** code before continuing; logged-in users skip this.
3. **Add-ons** — premium seating, priority boarding, cabins, and meals (breakfast/lunch/dinner/snack), each quantity-capped.
4. **Review & pay** — a full price breakdown (fares, vehicles, cargo, add-ons) before checkout. Seats are atomically reserved when the booking is created, holding inventory while payment completes.

### 4. Pay

- **Stripe Checkout** (`/bookings/api/create_checkout_session/`) — hosted card payment; the booking is confirmed by webhook **and** the success redirect, idempotently.
- **Mock Fiji-local gateways** (`/bookings/api/create_mock_checkout/`) — realistic **ANZ, BSP, Vodafone M-PAiSA, Digicel MyCash, and Card** rails that confirm a booking through the same state machine without moving real money (useful for demos and local rollout).
- **Success** (`/bookings/success/`) confirms and issues tickets; **cancel/back** releases the held seats and returns the traveller to the wizard.

### 5. Get tickets & board

- **Tickets** (`/bookings/ticket/<booking_id>/`) — one **QR boarding pass per passenger**.
- **View a single ticket** by QR token (`/bookings/view_ticket/<token>/`) and its scannable **QR image** (`/bookings/ticket_qr/<token>.png`).
- **PDF** (`/bookings/booking/<booking_id>/pdf/`) — a downloadable ticket PDF (authorization-checked so only the owner/guest can fetch it).
- At the gate, staff scan the QR; the ticket moves `active → boarding → used` and feeds the **live boarding board**.

### 6. Find & manage bookings

- **Booking history** (`/bookings/history/`) — for signed-in users.
- **Find my booking** (`/bookings/find-booking/`) — guests look up a booking by reference/email.
- **Modify** (`/bookings/modify/<id>/`) — add or remove passengers/extras; any **balance due is paid** (`/modify/<id>/pay/`) and **updated tickets are re-issued as a PDF** by email. Removing passengers refunds the fare difference per policy.
- **Cancel** (`/bookings/cancel_booking/<id>/`) — triggers the **tiered refund policy** (full / partial / none by time before departure) with an automatic Stripe refund and an email + SMS confirmation.

### 7. Waitlist & disruption recovery

- **Join the waitlist** (`/bookings/api/waitlist/join/`) on a sold-out sailing — no seats are held; when seats free up, the next person in line is emailed a first-come offer.
- **Leave the waitlist** via a tokenised link (`/bookings/waitlist/leave/<token>/`).
- **One-click rebooking** (`/bookings/rebook/<token>/`) — if a sailing is delayed or cancelled, the disruption email/SMS includes a single link that **moves the whole party to the next suitable sailing for free**.

---

## Architecture

```mermaid
flowchart LR
    subgraph Client
      W[Web + PWA]
      M[Mobile browser]
    end
    subgraph Edge[Django / Daphne ASGI]
      V[Views and REST APIs]
      WS[Channels WebSocket consumers]
      A[Custom Admin Control Hub]
    end
    subgraph Core[Service layer]
      SVC[services.py<br/>atomic inventory, payments, refunds, rebooking]
      NOTIF[notifications.py + sms.py<br/>email, SMS, WhatsApp]
      SCHED[scheduling.py<br/>auto-scheduler, weather holds]
      WAIT[waitlist.py]
    end
    subgraph Async[Celery workers + beat]
      T[Tasks: expiry, weather refresh, self-tests]
    end
    DB[(PostgreSQL / MySQL)]
    R[(Redis<br/>cache, channel layer, broker)]
    STRIPE{{Stripe}}
    TWILIO{{Twilio}}
    WX{{Weather API}}

    W & M --> V & WS
    V --> SVC --> DB
    A --> SVC
    WS <--> R
    V <--> STRIPE
    SVC --> NOTIF --> TWILIO
    SCHED --> WX
    T --> DB
    Edge <--> R
    Async <--> R
```

The **service layer** (`bookings/services.py`) is the heart of the system: every money- or inventory-critical operation (seat reservation, payment confirmation, cancellation/refund, rebooking, disruption broadcast) runs there under row-level locks (`SELECT … FOR UPDATE`) with atomic `F()` inventory updates. Views handle HTTP only. This guarantees **no overbooking and no double-refunds under concurrency**, and idempotency against Stripe webhook re-delivery.

**Deep dive:** see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the concurrency model, state machines, and design guarantees.

---

## Tech stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11+, Django 5.2, Django REST-style JSON APIs |
| **Real-time** | Django Channels 4, Daphne (ASGI), WebSockets |
| **Async tasks** | Celery 5 + django-celery-beat |
| **Data** | PostgreSQL (prod) / MySQL / SQLite (dev), Redis (cache, channel layer, broker) |
| **Payments** | Stripe Checkout + webhooks; mock Fiji-local gateways |
| **Messaging** | Email (SMTP / Brevo HTTP API), SMS + WhatsApp (Twilio) |
| **Frontend** | Server-rendered templates, vanilla JS, PWA (installable, offline-aware), Jazzmin-based admin |
| **PDF / QR** | ReportLab, qrcode |
| **Testing** | Django test suite, pytest, coverage (~100 tests) |
| **Deploy** | Render (Docker-free), WhiteNoise, Gunicorn/Daphne |

---

## Engineering highlights

- **Concurrency-safe inventory** — seats, vehicle slots and cargo weight are all reserved under a single locked `Schedule` row; DB `CheckConstraint`s act as a last-line backstop that makes overselling physically impossible even if application logic is bypassed.
- **Idempotent payments & refunds** — payment confirmation keys off a unique `(booking, session_id)` row; refunds carry a Stripe `idempotency_key`. Safe to call from both the webhook and the success redirect, repeatedly.
- **Explicit booking state machine** — `transition_booking()` rejects illegal transitions (e.g. `cancelled → confirmed`), so there is no bypass path to a paid/void state.
- **One-button disruption broadcast** — `services.disrupt_schedule()` cancels a sailing and every booking on it, refunds per policy, releases inventory, voids tickets, and fans out email + SMS with a free one-click rebooking link — all idempotent and safe to retry.
- **Graceful degradation** — SMS/WhatsApp, weather, and websockets all **no-op cleanly when unconfigured or unreachable**; a down SMTP server or Redis instance never breaks a booking.

---

## Quick start (local, SQLite — zero external services)

```bash
git clone <repository-url> && cd fiji_ferry_booking
python -m venv venv && source venv/Scripts/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # fill in as needed
python manage.py migrate
python manage.py ensure_demo_data                      # seed ports, routes, ferries, schedules
python manage.py createsuperuser
python manage.py runserver
```

Visit **http://127.0.0.1:8000/** for the traveller site and **/admin/** for the operations control hub.

> Full production setup (PostgreSQL/MySQL, Redis, Celery, Stripe & Twilio keys) is documented in [`DEPLOY.md`](DEPLOY.md) and [`OPERATIONS.md`](OPERATIONS.md).

### Configuration you may want

| Env var | Purpose |
|---|---|
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Real card payments & refunds |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_SMS_FROM` | SMS/WhatsApp alerts (blank = email only) |
| `REFUND_FULL_HOURS` / `REFUND_PARTIAL_HOURS` / `REFUND_PARTIAL_PCT` | Tune the refund policy |
| `WEATHER_HOLD_WIND_KMH` / `WEATHER_HOLD_PRECIP_PCT` | Safety thresholds for auto weather-holds |

---

## Testing

```bash
python manage.py test bookings --settings=ferry_system.test_settings
```

The suite runs fully offline — Stripe and email are mocked, channels use an in-memory layer — and covers the state machine, seat-inventory concurrency, payment/refund flows, the disruption broadcast, SMS routing, weather holds, and API/authorization boundaries.

---

## Project structure

```
fiji_ferry_booking/
├── ferry_system/          # Project config, ASGI, Celery, settings
├── accounts/              # Custom user model, auth, profiles
├── bookings/
│   ├── models.py          # Ports, Ferries, Routes, Schedules, Bookings, Tickets, Waitlist…
│   ├── services.py        # Authoritative money/inventory service layer
│   ├── notifications.py   # Email senders
│   ├── sms.py             # SMS / WhatsApp channel (Twilio)
│   ├── scheduling.py      # Auto-scheduler + weather holds
│   ├── waitlist.py        # Waitlist + one-click rebooking
│   ├── admin.py           # Custom admin site: dashboards, boarding, ops, manifest
│   ├── consumers.py       # WebSocket consumers
│   ├── tasks.py           # Celery tasks
│   └── tests.py           # Test suite
├── templates/             # Customer site + admin control hub
├── docs/screenshots/      # README imagery
└── manage.py
```

---

## Team & origin

Originally built for **IS314** (University of the South Pacific, Semester 2 2025, supervised by Mr. Ravneil Nand) and since extended into a full operations platform.

| Student ID | Name |
|------------|------|
| S11210953  | Lagilava Paulo |
| S11221892  | Pene Konousi |
| S11223573  | Rigieta Nagera |
| S11221570  | Sekove Koroi |
| S11196578  | Kesaia Waqavakatoga |

## License

Educational project (IS314). Not affiliated with any real ferry operator.
