# Ferry Operations Runbook (Staff)

How the scheduling automation works and how to operate it safely. Aimed at
admin/operations staff — no coding required.

> **Golden rule:** automation *protects* sailings, it never overrides a human on
> safety. It will hold or block a risky sailing, but a staff member always makes
> the final call to run, reschedule, or cancel.

---

## 1. Where to look — the Operations Dashboard

Admin top menu → **Operations** (or go to `/admin/ops/`). It refreshes live and
is the single place to see everything needing a decision. Top section:
**⚓ Schedule Risks — Needs Attention**, with four cards:

| Card | What it means | What to do |
|------|---------------|-----------|
| ⛈️ **Weather Holds** | A sailing was auto-pulled from sale because the route's weather breached safe limits. It is **not bookable** while held. | Check the forecast. **✓ Release** back to Scheduled only if conditions are genuinely safe, or **✕ Cancel** if not. |
| 🛠️ **Maintenance Conflicts** | A scheduled sailing uses a ferry that has an **open** maintenance log. (Usually maintenance was opened *after* the sailing existed.) | **Edit** to reassign another ferry, or **✕ Cancel** the sailing. |
| 🔀 **Ferry Overlaps** | The same ferry is booked for two sailings that overlap in time (not enough turnaround). | **Edit** one of them to fix the time or ferry. |
| 🌦️ **Stale Weather** | A route with upcoming sailings has no fresh weather, so risk checks can't run for it. | Verify the weather feed / wait for the next refresh (every ~20 min). |

Empty cards show a green ✅ — that risk is currently clear.

---

## 2. How sailings get created

Sailings are auto-seeded for a rolling window (default 7 days). **Before any
sailing is created**, the system checks it is operationally valid:

1. The ferry is **active**.
2. The ferry has **no open maintenance** that day.
3. The ferry isn't already at sea — the previous sailing's arrival **+ the
   route's turnaround buffer** must clear before this one departs.
4. The departure falls inside the route's **preferred departure windows** (if set).

Invalid slots are **skipped** (logged with a reason), so you'll never get an
impossible sailing from the auto-seeder. The same checks run when you **add or
edit a Schedule in the admin** — if you try to save an invalid sailing, the form
rejects it and tells you why.

> **Why are there fewer sailings on long routes?** A single ferry physically
> can't do two 12–14 h trips a day. The system correctly skips the impossible
> second sailing. To add it, assign a **second ferry** to that route, then it
> will be allowed.

---

## 3. Weather holds — the full cycle

1. Every ~15 min the system compares each upcoming sailing (next 24 h) to the
   latest weather for its route.
2. If wind, rain chance, or a severe condition (thunderstorm, gale…) breaches the
   limits, the sailing moves to **Weather Hold** — instantly off-sale — and the
   reason is written into the sailing's **Notes**.
3. It will **not** auto-cancel and will **not** auto-release. It waits for you.
4. You decide on the Operations dashboard (or the Schedules list): **Release** or
   **Cancel**.

Thresholds (wind km/h, rain %) are configurable by an administrator via
environment settings (`WEATHER_HOLD_WIND_KMH`, `WEATHER_HOLD_PRECIP_PCT`,
`WEATHER_HOLD_HORIZON_HOURS`). Set `WEATHER_HOLD_ENABLED=False` to pause holds.

---

## 4. Maintenance — keep ferries out of service correctly

To take a ferry out of service: **Admin → Maintenance → Add**, choose the ferry
and the date, and **leave "Completed at" blank**. While that log is open:

- New sailings won't be auto-created for that ferry.
- Existing upcoming sailings on it appear under **Maintenance Conflicts** — go
  reassign or cancel them.

When the work is done, set **Completed at** so the ferry is available again.

---

## 5. Managing schedules directly

**Admin → Schedules.** The **Real-Time Status** column flags risk at a glance,
including a red **"⚠ Weather Hold — needs review"**. Use the bulk **Actions**:

- 🟢 Mark Scheduled · 🟠 Mark Delayed · 🔴 Mark Cancelled
- ✅ **Release weather hold** (held → Scheduled)
- 📅 Duplicate for next day

---

## 6. Quick triage routine (start of shift)

1. Open **Operations**.
2. Clear **Maintenance Conflicts** and **Ferry Overlaps** first (they break the
   day's plan).
3. Work **Weather Holds** against the latest forecast — release or cancel each.
4. Glance at **Stuck Checkouts**, **Failed Payments**, **Unverified Documents**.
5. Anything red with a count is a to-do; green ✅ means clear.

---

## 7. Behind the scenes (for admins)

- Prevention checks: `bookings/scheduling.py` (`validate_schedule_slot`).
- Weather holds: `bookings/scheduling.py` (`evaluate_weather_holds`), run by the
  Celery beat task `bookings.tasks.evaluate_weather_holds` **and** the in-process
  automation agent (so it works even with no Celery worker, e.g. free hosting).
- Read-only anomaly checks (also surfaced at `/admin/agents/`):
  `bookings/automation.py`.
