# Deployment Guide — Fiji Ferry Booking

This guide covers everything required to take the system to production. Items in
**🔴 Blocker** must be done or the deploy will fail or be insecure.

---

## 1. Secrets & configuration

The previous `.env` (with live Stripe keys, the Gmail app password, and the
`SECRET_KEY`) was committed to git history. It has been removed from tracking,
but **the values are still in history and must be rotated.**

- 🔴 **Rotate all secrets** that were ever in `.env`:
  - Stripe secret/publishable/webhook keys
  - Gmail app password (see §5 — current credential is **rejected** by Gmail)
  - Weather API keys
- 🔴 **Generate a fresh `SECRET_KEY`** (the current one is the auto-generated
  `django-insecure-…` value, and it also encrypts the channel layer):
  ```bash
  python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
  ```
- Provision `.env` on the server from `.env.example` (never commit it).

### Production `.env` overrides
```
DEBUG=false
SECRET_KEY=<new 50+ char random key>
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
CSRF_TRUSTED_ORIGINS=https://your-domain.com,https://www.your-domain.com
SITE_URL=https://your-domain.com
SECURE_SSL_REDIRECT=true
SESSION_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
ADMIN_BACKGROUND_TASKS=true
```
With `DEBUG=false`, Django's deploy checks (SSL redirect, secure cookies, HSTS)
resolve automatically. Confirm with:
```bash
python manage.py check --deploy
```

---

## 2. Database & migrations

- 🔴 The `bookings` app previously had **no migration files**; a fresh DB would
  have created no tables. An initial migration now exists
  (`bookings/migrations/0001_initial.py`).
- On a fresh database:
  ```bash
  python manage.py migrate
  ```
- On the existing database (tables already present), the migration is already
  recorded. If you ever hit "table already exists", use:
  ```bash
  python manage.py migrate bookings --fake-initial
  ```

---

## 3. Static files

- 🔴 **Run `collectstatic` on every deploy.** Production uses
  `ManifestStaticFilesStorage` and serves from `staticfiles/`. Source assets
  live in `static/`. These had drifted out of sync (the homepage script in
  `staticfiles/` was stale and missing features).
  ```bash
  python manage.py collectstatic --noinput
  ```
- Going forward, **edit assets in `static/` only** and let `collectstatic`
  regenerate `staticfiles/`. Do not hand-edit `staticfiles/`.

---

## 4. Redis (required)

Channels (WebSockets), the cache, and Celery all need Redis.

- 🔴 Run Redis as a managed service (not the bundled `Redis/redis-server.exe`).
- Verify: `python -c "import redis; print(redis.Redis.from_url('redis://localhost:6379/0').ping())"`

---

## 5. Email (OTP & confirmations)

- 🔴 The current Gmail credentials are **rejected** (SMTP 535 BadCredentials).
  Guest OTP and booking-confirmation emails will not send until fixed.
  - Generate a new Gmail **App Password** (requires 2FA) and set
    `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD`.
  - The OTP endpoint now fails gracefully (HTTP 502 + user message) instead of
    a 500, but email must work for guest checkout.

---

## 6. Background services

Run alongside the web server (ASGI via Daphne):

```bash
# Web (ASGI)
daphne -b 0.0.0.0 -p 8000 ferry_system.asgi:application

# Celery worker + beat (schedule status updates run every 5 min)
celery -A ferry_system worker -l info
celery -A ferry_system beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

---

## 7. Seed data

- The DB currently has only **2 future schedules**; the rest are in the past
  (`departed`). Seed bookable future trips before launch:
  ```bash
  python seed_schedule.py
  ```

---

## 8. Pre-launch smoke test

```bash
python manage.py check
python manage.py check --deploy        # expect 0 issues with DEBUG=false
python manage.py collectstatic --noinput
```

Manually verify: homepage search (route + date), booking → Stripe checkout
(test card), admin dashboard live updates, admin change-list live sync.

---

## Fixed in this release (for the changelog)

- Added missing `bookings` initial migration (fresh deploys now create tables).
- Admin **dashboard** live updates: fixed missing `schedules` payload, dropped
  schedule updates, and a crash that killed the socket on `MaintenanceLog` save.
- Admin **change-list** live sync: fixed wrong admin registry (returned 0 rows),
  connection-rejecting URL parsing, a `database_sync_to_async` double-wrap, and
  dropped/untagged messages — sync now returns real rows.
- Homepage: fixed route free-text search for ports containing "to"
  (Natovi/Lautoka), fixed the "Book Now" 404 on dynamically-loaded cards, and
  synced the stale production homepage script.
- `modify_booking` view pointed at a non-existent template (500) → fixed.
- OTP send now fails gracefully instead of returning a 500 on SMTP errors.
- `.gitignore` rewritten; `.env`, `*.pyc`, and `Redis/dump.rdb` untracked.
