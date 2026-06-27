"""Free, key-less weather provider backed by Open-Meteo.

Open-Meteo (https://open-meteo.com) is free for non-commercial use, requires no
API key and no sign-up, and has generous rate limits — so weather "just works"
for free, always. We keep WeatherAPI as a best-effort fallback only if a key is
configured and Open-Meteo is unreachable.

The single entry point is ``fetch_and_store_weather(route)`` which fetches the
current conditions for the route's departure port, upserts a ``WeatherCondition``
row, and returns the serialised weather dict (or ``None`` on total failure).
"""
import logging
import datetime

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
TTL_MINUTES = 30

# WMO weather interpretation codes -> human-readable condition text.
# https://open-meteo.com/en/docs (Weather variable documentation)
WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


def _condition_text(code):
    try:
        return WMO_CODES.get(int(code), "Unknown")
    except (TypeError, ValueError):
        return "Unknown"


def fetch_current_weather(lat, lng):
    """Return a normalised current-weather dict for a coordinate, or None.

    Uses Open-Meteo first (free, no key). Falls back to WeatherAPI only if a key
    is set and Open-Meteo failed.
    """
    # --- Primary: Open-Meteo (free, keyless) ---
    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "current": "temperature_2m,weather_code,wind_speed_10m,precipitation",
                "hourly": "precipitation_probability",
                "forecast_days": 1,
                "timezone": "auto",
            },
            timeout=8,
        )
        resp.raise_for_status()
        data = resp.json()
        cur = data.get("current", {})

        # precipitation probability is an hourly-only variable; take the first
        # available value as a reasonable "right now" approximation.
        precip_prob = 0.0
        hourly = (data.get("hourly") or {}).get("precipitation_probability") or []
        for v in hourly:
            if v is not None:
                precip_prob = float(v)
                break

        return {
            "temperature": float(cur.get("temperature_2m")) if cur.get("temperature_2m") is not None else None,
            "wind_speed": float(cur.get("wind_speed_10m")) if cur.get("wind_speed_10m") is not None else None,
            "precipitation_probability": precip_prob,
            "condition": _condition_text(cur.get("weather_code")),
            "source": "open-meteo",
        }
    except requests.RequestException as e:
        logger.warning(f"Open-Meteo fetch failed for ({lat},{lng}): {e}")

    # --- Fallback: WeatherAPI (only if a key is configured) ---
    key = getattr(settings, "WEATHER_API_KEY", "")
    if key:
        try:
            resp = requests.get(
                "https://api.weatherapi.com/v1/current.json",
                params={"key": key, "q": f"{lat},{lng}", "aqi": "no"},
                timeout=8,
            )
            resp.raise_for_status()
            cur = resp.json()["current"]
            return {
                "temperature": cur["temp_c"],
                "wind_speed": cur["wind_kph"],
                "precipitation_probability": cur.get("precip_mm", 0) * 100,
                "condition": cur["condition"]["text"],
                "source": "weatherapi",
            }
        except (requests.RequestException, KeyError, ValueError) as e:
            logger.error(f"WeatherAPI fallback failed for ({lat},{lng}): {e}")

    return None


def _warning_for(wind_speed, precip_prob):
    if wind_speed and wind_speed > 30:
        return "Strong winds expected, potential delays."
    if precip_prob and precip_prob > 50:
        return "High chance of rain, please prepare accordingly."
    return None


def fetch_and_store_weather(route):
    """Fetch current weather for ``route``'s departure port, upsert a
    WeatherCondition row, and return the serialised weather dict (or None)."""
    from bookings.models import WeatherCondition  # avoid circular import

    port = route.departure_port
    if port is None or port.lat is None or port.lng is None:
        return None

    w = fetch_current_weather(port.lat, port.lng)
    if not w:
        return None

    now = timezone.now()
    expires_at = now + datetime.timedelta(minutes=TTL_MINUTES)
    WeatherCondition.objects.update_or_create(
        route=route,
        port=port,
        defaults={
            "temperature": w["temperature"],
            "wind_speed": w["wind_speed"],
            "precipitation_probability": w["precipitation_probability"],
            "condition": w["condition"],
            "expires_at": expires_at,
            "updated_at": now,
        },
    )
    return {
        "route_id": route.id,
        "port": port.name,
        "temperature": w["temperature"],
        "wind_speed": w["wind_speed"],
        "precipitation_probability": w["precipitation_probability"],
        "condition": w["condition"],
        "updated_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "warning": _warning_for(w["wind_speed"], w["precipitation_probability"]),
    }
