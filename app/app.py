"""Application météo (Flask) - Projet Cloud & Edge Computing.

Routes :
  /              page web
  /api/weather   données météo au format JSON  (?city=Rabat)
  /health        contrôle de santé (Jenkins, Ansible, supervision SLA)

Les données viennent d'Open-Meteo (gratuit, sans clé d'API).
La machine qui héberge l'application doit donc avoir accès à Internet et à un DNS.
"""
import logging
import os
import socket
import time
from datetime import datetime, timezone
from threading import Lock

import requests
from flask import Flask, jsonify, render_template, request

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_TTL = int(os.getenv("CACHE_TTL", "600"))  # secondes
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "8"))  # secondes
HOSTNAME = socket.gethostname()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("meteo")

app = Flask(__name__)

# Codes météo WMO -> (libellé français, famille d'icône)
WMO = {
    0: ("Ciel dégagé", "clear"),
    1: ("Plutôt dégagé", "clear"),
    2: ("Partiellement nuageux", "partly"),
    3: ("Couvert", "cloud"),
    45: ("Brouillard", "fog"),
    48: ("Brouillard givrant", "fog"),
    51: ("Bruine légère", "rain"),
    53: ("Bruine", "rain"),
    55: ("Bruine dense", "rain"),
    56: ("Bruine verglaçante", "rain"),
    57: ("Bruine verglaçante dense", "rain"),
    61: ("Pluie faible", "rain"),
    63: ("Pluie", "rain"),
    65: ("Pluie forte", "rain"),
    66: ("Pluie verglaçante", "rain"),
    67: ("Pluie verglaçante forte", "rain"),
    71: ("Neige faible", "snow"),
    73: ("Neige", "snow"),
    75: ("Neige forte", "snow"),
    77: ("Grains de neige", "snow"),
    80: ("Averses faibles", "rain"),
    81: ("Averses", "rain"),
    82: ("Averses violentes", "rain"),
    85: ("Averses de neige", "snow"),
    86: ("Fortes averses de neige", "snow"),
    95: ("Orage", "storm"),
    96: ("Orage avec grêle", "storm"),
    99: ("Orage violent avec grêle", "storm"),
}


class WeatherError(Exception):
    """Erreur métier renvoyée au navigateur avec un code HTTP."""

    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


# --- Cache mémoire simple (évite de rappeler l'API à chaque requête) ---------
_cache = {}
_cache_lock = Lock()


def cache_get(key):
    with _cache_lock:
        item = _cache.get(key)
        if item and time.time() - item[0] < CACHE_TTL:
            return item[1]
        if item:
            del _cache[key]
    return None


def cache_set(key, value):
    with _cache_lock:
        if len(_cache) > 200:  # évite une croissance sans limite
            _cache.clear()
        _cache[key] = (time.time(), value)


# --- Appels à Open-Meteo -----------------------------------------------------
def describe(code):
    label, icon = WMO.get(code, ("Conditions inconnues", "cloud"))
    return label, icon


def geocode(city):
    try:
        r = requests.get(
            GEOCODE_URL,
            params={"name": city, "count": 1, "language": "fr", "format": "json"},
            timeout=HTTP_TIMEOUT,
        )
        r.raise_for_status()
    except requests.RequestException as exc:
        log.error("Géocodage impossible pour %r : %s", city, exc)
        raise WeatherError(
            "Le service de recherche de villes est injoignable. "
            "Vérifiez que le serveur a accès à Internet et à un DNS.",
            502,
        )
    results = r.json().get("results") or []
    if not results:
        raise WeatherError(
            f"Ville introuvable : « {city} ». Vérifiez l'orthographe ou ajoutez le pays.",
            404,
        )
    return results[0]


def fetch_forecast(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "timezone": "auto",
        "forecast_days": 7,
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "is_day",
                "precipitation",
                "weather_code",
                "pressure_msl",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "sunrise",
                "sunset",
                "uv_index_max",
                "precipitation_sum",
                "precipitation_probability_max",
            ]
        ),
    }
    try:
        r = requests.get(FORECAST_URL, params=params, timeout=HTTP_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as exc:
        log.error("Prévisions indisponibles : %s", exc)
        raise WeatherError(
            "Le service météo ne répond pas. Réessayez dans quelques instants.", 502
        )


def build_payload(place, raw):
    cur = raw["current"]
    label, icon = describe(cur["weather_code"])

    hourly = raw["hourly"]
    times = hourly["time"]
    now_hour = cur["time"][:13] + ":00"
    start = next((i for i, t in enumerate(times) if t >= now_hour), 0)
    hours = []
    for i in range(start, min(start + 24, len(times))):
        _, h_icon = describe(hourly["weather_code"][i])
        hours.append(
            {
                "time": times[i],
                "temp": hourly["temperature_2m"][i],
                "precip_prob": hourly["precipitation_probability"][i] or 0,
                "is_day": bool(hourly["is_day"][i]),
                "icon": h_icon,
            }
        )

    daily = raw["daily"]
    days = []
    for i, day in enumerate(daily["time"]):
        d_label, d_icon = describe(daily["weather_code"][i])
        days.append(
            {
                "date": day,
                "label": d_label,
                "icon": d_icon,
                "tmax": daily["temperature_2m_max"][i],
                "tmin": daily["temperature_2m_min"][i],
                "precip_prob": daily["precipitation_probability_max"][i] or 0,
                "precip_sum": daily["precipitation_sum"][i] or 0,
                "uv": daily["uv_index_max"][i],
                "sunrise": daily["sunrise"][i],
                "sunset": daily["sunset"][i],
            }
        )

    return {
        "location": {
            "name": place.get("name"),
            "country": place.get("country"),
            "region": place.get("admin1"),
            "latitude": place.get("latitude"),
            "longitude": place.get("longitude"),
            "timezone": raw.get("timezone"),
        },
        "current": {
            "time": cur["time"],
            "temp": cur["temperature_2m"],
            "feels_like": cur["apparent_temperature"],
            "humidity": cur["relative_humidity_2m"],
            "wind_speed": cur["wind_speed_10m"],
            "wind_dir": cur["wind_direction_10m"],
            "pressure": cur["pressure_msl"],
            "precipitation": cur["precipitation"],
            "is_day": bool(cur["is_day"]),
            "label": label,
            "icon": icon,
        },
        "hourly": hours,
        "daily": days,
    }


# --- Routes ------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/weather")
def api_weather():
    city = (request.args.get("city") or "").strip()
    if not city or len(city) > 80:
        return jsonify(error="Indiquez le nom d'une ville (80 caractères maximum)."), 400

    key = city.casefold()
    payload = cache_get(key)
    from_cache = payload is not None
    if payload is None:
        try:
            place = geocode(city)
            raw = fetch_forecast(place["latitude"], place["longitude"])
            payload = build_payload(place, raw)
        except WeatherError as err:
            return jsonify(error=err.message), err.status
        except (KeyError, IndexError, TypeError) as exc:
            log.error("Réponse inattendue d'Open-Meteo : %r", exc)
            return jsonify(error="Réponse inattendue du service météo."), 502
        cache_set(key, payload)

    body = dict(payload)
    body["meta"] = {"served_by": HOSTNAME, "cached": from_cache}
    return jsonify(body)


@app.route("/health")
def health():
    return jsonify(
        status="ok",
        host=HOSTNAME,
        time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
