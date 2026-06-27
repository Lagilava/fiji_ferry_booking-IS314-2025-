"""Cybersecurity agent — read-only security-posture auditor bound to the server.

This is the third in-process daemon, a sibling to ``bookings/automation.py``
(self-tests) and ``bookings/monitor.py`` (infrastructure heartbeat). Staff asked
for an agent that acts as the *cybersecurity* watchdog: on each interval it runs a
**non-destructive, internet-free** battery of security checks and records the
result to ``logs/security_status.json`` + ``logs/security.log`` so the posture is
visible even offline and inside the admin Agent dashboard.

What it audits (all read-only — never mutates data or settings):
  1. Django deployment checks  — ``manage.py check --deploy`` (HSTS, SSL redirect,
     secure cookies, referrer policy, etc.), the authoritative source.
  2. Core settings hardening    — DEBUG, SECRET_KEY strength, ALLOWED_HOSTS.
  3. Transport / cookie security — SSL redirect, Secure/HttpOnly cookies, HSTS,
     clickjacking (X-Frame-Options), security middleware presence.
  4. Account hygiene            — superuser count, staff without usable passwords,
     accounts flagged for repeated failed logins (if such tracking exists).
  5. Repository hygiene         — stray debug/throwaway scripts left in the project
     root, world-readable SQLite DB file.

Each check yields (name, ok, severity, detail) where severity is one of
"critical" | "warning" | "info". The agent's overall ``ok`` is True only when no
*critical* finding is present, so dev-mode noise (e.g. DEBUG=True locally) is
reported as a warning rather than blocking.
"""
import atexit
import json
import logging
import os
import threading
from datetime import datetime, timezone as dt_timezone

logger = logging.getLogger("bookings.security")

_thread = None
_stop_event = threading.Event()

# Tokens that flag an obviously insecure / placeholder SECRET_KEY.
_INSECURE_SECRET_TOKENS = (
    "django-insecure", "changeme", "change-me", "secret", "your-secret-key",
    "dev", "test", "example",
)

# Throwaway scripts that should not ship — surfaced as a hygiene warning.
_STRAY_SCRIPT_PREFIXES = ("check_", "debug_", "fix_", "scratch_", "tmp_")


def _sev_rank(sev):
    return {"critical": 3, "warning": 2, "info": 1}.get(sev, 0)


# --------------------------------------------------------------------------- #
# Checks  (each appends (name, ok, severity, detail) tuples)
# --------------------------------------------------------------------------- #
def _check_django_deploy():
    """Run Django's own --deploy system checks; map each message to a finding."""
    results = []
    try:
        # Use the checks registry directly with the 'security' tag so we get
        # structured messages instead of parsing stdout.
        from django.core.checks.registry import registry
        messages = registry.run_checks(tags=["security"], include_deployment_checks=True)
        if not messages:
            results.append(("django deploy checks", True, "info", "no deployment security warnings"))
            return results
        for m in messages:
            # m.level: 40=ERROR/CRITICAL, 30=WARNING, 20=INFO
            sev = "critical" if m.level >= 40 else ("warning" if m.level >= 30 else "info")
            ident = getattr(m, "id", None) or ""
            label = f"{ident}".strip() or str(m.msg)[:40]
            results.append((f"deploy: {label}", False, sev, str(m.msg)[:200]))
    except Exception as e:  # pragma: no cover - defensive
        results.append(("django deploy checks", False, "warning", f"could not run: {str(e)[:160]}"))
    return results


def _check_core_settings():
    from django.conf import settings
    results = []

    debug = bool(getattr(settings, "DEBUG", False))
    results.append((
        "DEBUG disabled",
        not debug,
        "warning" if debug else "info",
        "DEBUG=True — safe locally, MUST be False in production" if debug else "DEBUG=False",
    ))

    secret = str(getattr(settings, "SECRET_KEY", "") or "")
    low = secret.lower()
    weak = (len(secret) < 50) or any(tok in low for tok in _INSECURE_SECRET_TOKENS)
    results.append((
        "SECRET_KEY strength",
        not weak,
        "critical" if weak else "info",
        "weak/placeholder SECRET_KEY — rotate before production" if weak
        else f"{len(secret)} chars, no placeholder tokens",
    ))

    hosts = list(getattr(settings, "ALLOWED_HOSTS", []) or [])
    if not debug:
        bad_hosts = (not hosts) or ("*" in hosts)
        results.append((
            "ALLOWED_HOSTS restricted",
            not bad_hosts,
            "critical" if bad_hosts else "info",
            "empty or wildcard ALLOWED_HOSTS with DEBUG=False" if bad_hosts
            else ", ".join(hosts)[:120],
        ))
    else:
        results.append((
            "ALLOWED_HOSTS restricted", True, "info",
            "not enforced while DEBUG=True",
        ))
    return results


def _check_transport_security():
    from django.conf import settings
    results = []
    debug = bool(getattr(settings, "DEBUG", False))
    # In dev these are expected to be relaxed → report as info, not failure.
    prod_sev = "info" if debug else "warning"

    flags = [
        ("SECURE_SSL_REDIRECT", "force HTTPS"),
        ("SESSION_COOKIE_SECURE", "session cookie HTTPS-only"),
        ("CSRF_COOKIE_SECURE", "CSRF cookie HTTPS-only"),
    ]
    for name, desc in flags:
        on = bool(getattr(settings, name, False))
        results.append((
            f"{name}", on or debug, prod_sev if not on else "info",
            f"{desc}: {'on' if on else 'off'}" + (" (dev)" if debug and not on else ""),
        ))

    hsts = int(getattr(settings, "SECURE_HSTS_SECONDS", 0) or 0)
    results.append((
        "SECURE_HSTS_SECONDS set", hsts > 0 or debug,
        "info" if (hsts > 0 or debug) else "warning",
        f"{hsts}s" if hsts else ("not set (dev)" if debug else "HSTS not configured"),
    ))

    xfo = str(getattr(settings, "X_FRAME_OPTIONS", "") or "").upper()
    results.append((
        "X_FRAME_OPTIONS anti-clickjacking",
        xfo in ("DENY", "SAMEORIGIN"),
        "warning" if xfo not in ("DENY", "SAMEORIGIN") else "info",
        xfo or "unset",
    ))

    mw = list(getattr(settings, "MIDDLEWARE", []) or [])
    required = {
        "SecurityMiddleware": "django.middleware.security.SecurityMiddleware",
        "CsrfViewMiddleware": "django.middleware.csrf.CsrfViewMiddleware",
        "XFrameOptionsMiddleware": "django.middleware.clickjacking.XFrameOptionsMiddleware",
        "AuthenticationMiddleware": "django.contrib.auth.middleware.AuthenticationMiddleware",
    }
    missing = [short for short, path in required.items() if path not in mw]
    results.append((
        "core security middleware present",
        not missing,
        "critical" if missing else "info",
        "missing: " + ", ".join(missing) if missing else "all present",
    ))
    return results


def _check_account_hygiene():
    results = []
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        superusers = User.objects.filter(is_superuser=True, is_active=True).count()
        results.append((
            "superuser count reasonable",
            superusers <= 5,
            "warning" if superusers > 5 else "info",
            f"{superusers} active superuser(s)",
        ))
        # Staff accounts that can authenticate but have no usable password are a
        # red flag (e.g. left over from imports).
        no_pw = sum(
            1 for u in User.objects.filter(is_staff=True, is_active=True)
            if not u.has_usable_password()
        )
        results.append((
            "staff accounts have usable passwords",
            no_pw == 0,
            "warning" if no_pw else "info",
            f"{no_pw} staff account(s) without a usable password" if no_pw else "ok",
        ))
    except Exception as e:
        results.append(("account hygiene", False, "warning", str(e)[:160]))
    return results


def _check_repo_hygiene():
    from django.conf import settings
    results = []
    base = str(settings.BASE_DIR)
    try:
        stray = []
        for entry in os.listdir(base):
            if not entry.endswith(".py"):
                continue
            if any(entry.startswith(p) for p in _STRAY_SCRIPT_PREFIXES):
                stray.append(entry)
        results.append((
            "no stray debug scripts in project root",
            not stray,
            "warning" if stray else "info",
            ("found: " + ", ".join(sorted(stray)[:6])) if stray else "clean",
        ))
    except Exception as e:
        results.append(("repo hygiene scan", False, "info", str(e)[:120]))

    # SQLite DB world-readable check (POSIX only; informational on Windows).
    try:
        db = settings.DATABASES.get("default", {})
        name = str(db.get("NAME", ""))
        if db.get("ENGINE", "").endswith("sqlite3") and name and os.path.exists(name):
            if hasattr(os, "stat") and os.name == "posix":
                mode = os.stat(name).st_mode
                world = bool(mode & 0o004)
                results.append((
                    "database file not world-readable",
                    not world,
                    "warning" if world else "info",
                    "world-readable SQLite DB" if world else "ok",
                ))
            else:
                results.append((
                    "database file permissions", True, "info",
                    "permission bits not enforced on this OS",
                ))
    except Exception as e:
        results.append(("db file permission check", False, "info", str(e)[:120]))
    return results


def run_audit():
    """Run the full security battery and return a structured result dict."""
    import time as _time
    started = _time.perf_counter()
    checks = []
    groups = (
        ("deploy", _check_django_deploy()),
        ("settings", _check_core_settings()),
        ("transport", _check_transport_security()),
        ("accounts", _check_account_hygiene()),
        ("repo", _check_repo_hygiene()),
    )
    for group_name, group in groups:
        for name, ok, severity, detail in group:
            checks.append({
                "group": group_name, "name": name, "ok": bool(ok),
                "severity": severity, "detail": detail,
            })

    passed = sum(1 for c in checks if c["ok"])
    failed = [c for c in checks if not c["ok"]]
    criticals = [c["name"] for c in failed if c["severity"] == "critical"]
    warnings = [c["name"] for c in failed if c["severity"] == "warning"]
    # Posture is "ok" when there are no CRITICAL findings (warnings are surfaced
    # but don't flip the agent red, so local dev doesn't look perpetually broken).
    posture_ok = len(criticals) == 0
    return {
        "ran_at": datetime.now(dt_timezone.utc).isoformat(),
        "duration_ms": round((_time.perf_counter() - started) * 1000, 1),
        "passed": passed,
        "total": len(checks),
        "ok": posture_ok,
        "critical_count": len(criticals),
        "warning_count": len(warnings),
        "criticals": criticals,
        "warnings": warnings,
        "checks": checks,
    }


# --------------------------------------------------------------------------- #
# Daemon
# --------------------------------------------------------------------------- #
def _paths():
    from django.conf import settings
    logs = os.path.join(settings.BASE_DIR, "logs")
    os.makedirs(logs, exist_ok=True)
    return os.path.join(logs, "security.log"), os.path.join(logs, "security_status.json")


def _write(result):
    log_path, status_path = _paths()
    try:
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
    except Exception:
        logger.exception("security: failed to write status")
    level = logging.WARNING if not result["ok"] else logging.INFO
    summary = (f"{result['passed']}/{result['total']} ok, "
               f"{result['critical_count']} critical, {result['warning_count']} warning")
    if result["criticals"]:
        summary += "; CRITICAL: " + ", ".join(result["criticals"][:5])
    logger.log(level, "audit %s", summary)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{result['ran_at']}] {summary}\n")
    except Exception:
        pass


def _run(interval):
    logger.info("Cybersecurity agent started (interval=%ss)", interval)
    # brief boot delay so settings/DB are fully ready before the first audit
    if _stop_event.wait(7):
        return
    while not _stop_event.is_set():
        try:
            _write(run_audit())
        except Exception:
            logger.exception("security: audit run failed")
        _stop_event.wait(interval)


def _on_exit():
    _stop_event.set()
    try:
        log_path, _ = _paths()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now(dt_timezone.utc).isoformat()}] STOPPED\n")
    except Exception:
        pass


def start_security():
    """Start the cybersecurity daemon once, only for real server processes."""
    global _thread
    from django.conf import settings
    from .monitor import _is_server_process  # shared server-detection guard

    if not getattr(settings, "SECURITY_AGENT_ENABLED", True):
        return
    if not _is_server_process():
        return
    import sys
    argv = sys.argv or []
    if "runserver" in argv and "--noreload" not in argv and os.environ.get("RUN_MAIN") != "true":
        return
    if _thread is not None and _thread.is_alive():
        return

    interval = int(getattr(settings, "SECURITY_AGENT_INTERVAL", 300))
    _stop_event.clear()
    _thread = threading.Thread(target=_run, args=(interval,), name="security-agent", daemon=True)
    _thread.start()
    atexit.register(_on_exit)
