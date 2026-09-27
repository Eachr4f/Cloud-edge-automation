"""Tests de l'application météo, sans accès Internet (Open-Meteo est simulé).

Lancement :  python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
import app as meteo  # noqa: E402


class FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def fake_forecast():
    start = datetime(2026, 9, 20, 0, 0)
    hours = [start + timedelta(hours=i) for i in range(7 * 24)]
    days = [(start + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    return {
        "timezone": "Africa/Casablanca",
        "current": {
            "time": "2026-09-20T18:45", "temperature_2m": 24.3, "relative_humidity_2m": 62,
            "apparent_temperature": 25.1, "is_day": 1, "precipitation": 0.0, "weather_code": 2,
            "pressure_msl": 1016.4, "wind_speed_10m": 14.2, "wind_direction_10m": 250,
        },
        "hourly": {
            "time": [h.strftime("%Y-%m-%dT%H:00") for h in hours],
            "temperature_2m": [18 + (i % 24) / 3 for i in range(len(hours))],
            "precipitation_probability": [None if i % 5 == 0 else (i % 7) * 10 for i in range(len(hours))],
            "weather_code": [2] * len(hours),
            "is_day": [1 if 7 <= h.hour < 19 else 0 for h in hours],
        },
        "daily": {
            "time": days,
            "weather_code": [2, 3, 61, 0, 1, 95, 45],
            "temperature_2m_max": [26, 27, 22, 25, 28, 21, 24],
            "temperature_2m_min": [17, 18, 15, 16, 19, 14, 15],
            "sunrise": [d + "T07:12" for d in days],
            "sunset": [d + "T19:31" for d in days],
            "uv_index_max": [7.2, 6.0, 3.1, 8.0, 8.5, 2.0, 5.0],
            "precipitation_sum": [0, 0, 4.2, 0, 0, 12.0, 0],
            "precipitation_probability_max": [10, 20, 80, 0, 5, 90, None],
        },
    }


def fake_get(url, params=None, timeout=None):
    if "geocoding" in url:
        if params["name"].lower() == "nullepart":
            return FakeResponse({})
        return FakeResponse({"results": [{
            "name": "Casablanca", "country": "Maroc", "admin1": "Casablanca-Settat",
            "latitude": 33.59, "longitude": -7.62,
        }]})
    return FakeResponse(fake_forecast())


class WeatherAppTests(unittest.TestCase):
    def setUp(self):
        meteo._cache.clear()
        self.client = meteo.app.test_client()

    def test_index_page(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Météo".encode(), r.data)

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "ok")

    def test_missing_city(self):
        self.assertEqual(self.client.get("/api/weather").status_code, 400)
        self.assertEqual(self.client.get("/api/weather?city=" + "x" * 81).status_code, 400)

    @mock.patch("app.requests.get", side_effect=fake_get)
    def test_weather_payload(self, _):
        r = self.client.get("/api/weather?city=Casablanca")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["location"]["name"], "Casablanca")
        self.assertEqual(data["current"]["label"], "Partiellement nuageux")
        self.assertEqual(data["current"]["icon"], "partly")
        self.assertEqual(len(data["hourly"]), 24)
        self.assertEqual(data["hourly"][0]["time"], "2026-09-20T18:00")
        self.assertEqual(len(data["daily"]), 7)
        self.assertEqual(data["daily"][6]["precip_prob"], 0)  # None -> 0
        self.assertFalse(data["meta"]["cached"])

    @mock.patch("app.requests.get", side_effect=fake_get)
    def test_cache(self, get):
        self.client.get("/api/weather?city=Casablanca")
        calls = get.call_count
        r = self.client.get("/api/weather?city=casablanca")
        self.assertTrue(r.get_json()["meta"]["cached"])
        self.assertEqual(get.call_count, calls)

    @mock.patch("app.requests.get", side_effect=fake_get)
    def test_unknown_city(self, _):
        r = self.client.get("/api/weather?city=Nullepart")
        self.assertEqual(r.status_code, 404)
        self.assertIn("introuvable", r.get_json()["error"])

    @mock.patch("app.requests.get", side_effect=requests.ConnectionError("DNS"))
    def test_upstream_down(self, _):
        r = self.client.get("/api/weather?city=Rabat")
        self.assertEqual(r.status_code, 502)
        self.assertIn("Internet", r.get_json()["error"])


if __name__ == "__main__":
    unittest.main()
