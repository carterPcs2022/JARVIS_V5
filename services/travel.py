"""
JARVIS V5 - Travel Intelligence Service
Flight status, weather, timezones, currency, and package tracking.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    _requests = None

try:
    from zoneinfo import ZoneInfo
    ZONEINFO_AVAILABLE = True
except ImportError:
    ZONEINFO_AVAILABLE = False

try:
    import pytz
    PYTZ_AVAILABLE = True
except ImportError:
    PYTZ_AVAILABLE = False

CITY_TIMEZONE_MAP = {
    "New York": "America/New_York",
    "Los Angeles": "America/Los_Angeles",
    "Chicago": "America/Chicago",
    "London": "Europe/London",
    "Paris": "Europe/Paris",
    "Tokyo": "Asia/Tokyo",
    "Sydney": "Australia/Sydney",
    "Dubai": "Asia/Dubai",
    "Singapore": "Asia/Singapore",
    "Hong Kong": "Asia/Hong_Kong",
    "Berlin": "Europe/Berlin",
    "Toronto": "America/Toronto",
    "São Paulo": "America/Sao_Paulo",
    "Mexico City": "America/Mexico_City",
    "Cairo": "Africa/Cairo",
    "Mumbai": "Asia/Kolkata",
    "Beijing": "Asia/Shanghai",
    "Seoul": "Asia/Seoul",
    "Amsterdam": "Europe/Amsterdam",
    "Madrid": "Europe/Madrid",
    "Rome": "Europe/Rome",
    "Moscow": "Europe/Moscow",
    "Istanbul": "Europe/Istanbul",
    "Bangkok": "Asia/Bangkok",
    "Jakarta": "Asia/Jakarta",
    "Johannesburg": "Africa/Johannesburg",
    "Lagos": "Africa/Lagos",
    "Nairobi": "Africa/Nairobi",
    "Buenos Aires": "America/Argentina/Buenos_Aires",
    "Lima": "America/Lima",
    "Bogota": "America/Bogota",
    "Santiago": "America/Santiago",
    "Vancouver": "America/Vancouver",
    "Seattle": "America/Los_Angeles",
    "Miami": "America/New_York",
    "Atlanta": "America/New_York",
    "Boston": "America/New_York",
    "Dallas": "America/Chicago",
    "Denver": "America/Denver",
    "Phoenix": "America/Phoenix",
    "Las Vegas": "America/Los_Angeles",
    "San Francisco": "America/Los_Angeles",
    "Honolulu": "Pacific/Honolulu",
    "Anchorage": "America/Anchorage",
    "Stockholm": "Europe/Stockholm",
    "Oslo": "Europe/Oslo",
    "Helsinki": "Europe/Helsinki",
    "Zurich": "Europe/Zurich",
    "Vienna": "Europe/Vienna",
    "Prague": "Europe/Prague",
}

CARRIER_TRACKING_URLS = {
    "ups": "https://www.ups.com/track?tracknum={tracking_number}",
    "fedex": "https://www.fedex.com/fedextrack/?trknbr={tracking_number}",
    "usps": "https://tools.usps.com/go/TrackConfirmAction?tLabels={tracking_number}",
    "dhl": "https://www.dhl.com/en/express/tracking.html?AWB={tracking_number}",
}


class TravelIntelligence:
    """Handles flight status, weather, timezones, currency conversion, and travel briefs."""

    def flight_status(self, flight_number: str) -> dict:
        """
        Look up flight status via AviationStack API.
        Requires AVIATIONSTACK_KEY environment variable.
        """
        api_key = os.environ.get("AVIATIONSTACK_KEY")
        if not api_key:
            return {
                "status": "not_configured",
                "message": "Set AVIATIONSTACK_KEY env var to enable flight tracking.",
                "flight_number": flight_number,
            }

        if not REQUESTS_AVAILABLE:
            return {
                "status": "error",
                "message": "requests library not installed.",
                "flight_number": flight_number,
            }

        flight_number_clean = flight_number.upper().strip().replace(" ", "")
        url = (
            f"http://api.aviationstack.com/v1/flights"
            f"?access_key={api_key}&flight_iata={flight_number_clean}"
        )

        try:
            resp = _requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            flights = data.get("data", [])
            if not flights:
                return {
                    "status": "not_found",
                    "flight_number": flight_number_clean,
                    "message": "No flight data found for this flight number.",
                }

            f = flights[0]
            dep = f.get("departure", {})
            arr = f.get("arrival", {})

            return {
                "flight_number": flight_number_clean,
                "airline": f.get("airline", {}).get("name"),
                "status": f.get("flight_status"),
                "departure": {
                    "airport": dep.get("airport"),
                    "iata": dep.get("iata"),
                    "scheduled": dep.get("scheduled"),
                    "actual": dep.get("actual"),
                    "terminal": dep.get("terminal"),
                    "gate": dep.get("gate"),
                },
                "arrival": {
                    "airport": arr.get("airport"),
                    "iata": arr.get("iata"),
                    "scheduled": arr.get("scheduled"),
                    "estimated": arr.get("estimated"),
                    "actual": arr.get("actual"),
                    "terminal": arr.get("terminal"),
                    "gate": arr.get("gate"),
                },
                "delay": dep.get("delay") or arr.get("delay"),
                "as_of": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"AviationStack error for {flight_number}: {e}")
            return {
                "status": "error",
                "flight_number": flight_number_clean,
                "message": str(e),
            }

    def weather_travel(self, city: str, date: Optional[str] = None) -> dict:
        """
        Fetch weather for a city using wttr.in free API.
        Returns clean dict with temp, humidity, condition.
        """
        if not REQUESTS_AVAILABLE:
            return {"status": "error", "message": "requests library not installed.", "city": city}

        city_encoded = city.strip().replace(" ", "+")
        url = f"https://wttr.in/{city_encoded}?format=j1"

        try:
            resp = _requests.get(url, timeout=10, headers={"User-Agent": "JARVIS/5.0"})
            resp.raise_for_status()
            data = resp.json()

            current = data.get("current_condition", [{}])[0]
            nearest_area = data.get("nearest_area", [{}])[0]
            area_name = nearest_area.get("areaName", [{}])[0].get("value", city)
            country = nearest_area.get("country", [{}])[0].get("value", "")

            temp_c = float(current.get("temp_C", 0))
            temp_f = float(current.get("temp_F", 0))
            feels_like_c = float(current.get("FeelsLikeC", temp_c))
            humidity = int(current.get("humidity", 0))
            wind_kph = float(current.get("windspeedKmph", 0))
            condition = current.get("weatherDesc", [{}])[0].get("value", "Unknown")
            visibility_km = int(current.get("visibility", 0))
            uv_index = int(current.get("uvIndex", 0))

            # Tomorrow's forecast if date provided
            forecast = None
            if date:
                weather_list = data.get("weather", [])
                for w in weather_list:
                    if w.get("date") == date:
                        hourly = w.get("hourly", [{}])
                        mid = hourly[len(hourly) // 2] if hourly else {}
                        forecast = {
                            "date": date,
                            "max_temp_c": float(w.get("maxtempC", 0)),
                            "min_temp_c": float(w.get("mintempC", 0)),
                            "condition": w.get("hourly", [{}])[0].get("weatherDesc", [{}])[0].get("value", ""),
                            "precipitation_mm": float(w.get("hourly", [{}])[0].get("precipMM", 0)),
                        }
                        break

            result = {
                "city": area_name,
                "country": country,
                "temperature_c": temp_c,
                "temperature_f": temp_f,
                "feels_like_c": feels_like_c,
                "humidity_pct": humidity,
                "wind_kph": wind_kph,
                "condition": condition,
                "visibility_km": visibility_km,
                "uv_index": uv_index,
                "as_of": datetime.now().isoformat(),
                "status": "ok",
            }
            if forecast:
                result["forecast"] = forecast
            return result

        except Exception as e:
            logger.error(f"wttr.in error for {city}: {e}")
            return {"status": "error", "city": city, "message": str(e)}

    def timezone_manager(self, cities: list) -> dict:
        """
        Return timezone info for a list of cities.
        Uses zoneinfo (stdlib, Python 3.9+) or pytz fallback.
        """
        results = {}

        for city in cities:
            # Find timezone: try exact match, then case-insensitive
            tz_name = CITY_TIMEZONE_MAP.get(city)
            if not tz_name:
                for key, val in CITY_TIMEZONE_MAP.items():
                    if key.lower() == city.lower():
                        tz_name = val
                        break

            if not tz_name:
                results[city] = {
                    "timezone": None,
                    "current_time": None,
                    "utc_offset": None,
                    "error": f"City '{city}' not found in timezone map.",
                }
                continue

            try:
                if ZONEINFO_AVAILABLE:
                    tz = ZoneInfo(tz_name)
                    now_local = datetime.now(tz)
                elif PYTZ_AVAILABLE:
                    tz = pytz.timezone(tz_name)
                    now_local = datetime.now(tz)
                else:
                    results[city] = {
                        "timezone": tz_name,
                        "current_time": None,
                        "utc_offset": None,
                        "error": "No timezone library available (zoneinfo or pytz required).",
                    }
                    continue

                utc_offset = now_local.strftime("%z")
                # Format as +HH:MM
                if len(utc_offset) == 5:
                    utc_offset = f"{utc_offset[:3]}:{utc_offset[3:]}"

                results[city] = {
                    "timezone": tz_name,
                    "current_time": now_local.strftime("%Y-%m-%d %H:%M:%S"),
                    "utc_offset": utc_offset,
                    "day_of_week": now_local.strftime("%A"),
                }
            except Exception as e:
                results[city] = {
                    "timezone": tz_name,
                    "current_time": None,
                    "utc_offset": None,
                    "error": str(e),
                }

        return results

    def currency_convert(
        self,
        amount: float,
        from_cur: str,
        to_cur: str,
    ) -> dict:
        """
        Convert currency using open.er-api.com (free, no key required).
        Returns conversion result with rate and timestamp.
        """
        if not REQUESTS_AVAILABLE:
            return {"status": "error", "message": "requests library not installed."}

        from_cur = from_cur.upper().strip()
        to_cur = to_cur.upper().strip()
        url = f"https://open.er-api.com/v6/latest/{from_cur}"

        try:
            resp = _requests.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()

            if data.get("result") != "success":
                return {
                    "status": "error",
                    "message": data.get("error-type", "Unknown error from exchange rate API."),
                    "from": from_cur,
                    "to": to_cur,
                }

            rates = data.get("rates", {})
            if to_cur not in rates:
                return {
                    "status": "error",
                    "message": f"Currency '{to_cur}' not found in exchange rates.",
                    "from": from_cur,
                    "to": to_cur,
                    "available_currencies": list(rates.keys()),
                }

            rate = rates[to_cur]
            result = amount * rate
            time_last_update = data.get("time_last_update_utc", datetime.now().isoformat())

            return {
                "from": from_cur,
                "to": to_cur,
                "amount": amount,
                "result": round(result, 4),
                "rate": round(rate, 6),
                "timestamp": time_last_update,
                "status": "ok",
            }

        except Exception as e:
            logger.error(f"Currency conversion error {from_cur}→{to_cur}: {e}")
            return {
                "status": "error",
                "from": from_cur,
                "to": to_cur,
                "amount": amount,
                "message": str(e),
            }

    def travel_brief(self, destination: str, date: Optional[str] = None) -> str:
        """
        Combine weather, timezone, and LLM knowledge for a comprehensive travel brief.
        Returns brief string.
        """
        from core.llm.router import think

        weather = self.weather_travel(destination, date)
        timezone_info = self.timezone_manager([destination])

        context = {
            "destination": destination,
            "travel_date": date,
            "weather": weather,
            "timezone": timezone_info.get(destination, {}),
        }

        prompt = (
            f"You are JARVIS, an AI assistant. Generate a comprehensive travel brief for "
            f"'{destination}'{' on ' + date if date else ''}. Include weather conditions, "
            f"local time, practical travel tips, and any notable information about the destination. "
            f"Keep it under 250 words.\n\nData available:\n{json.dumps(context, indent=2, default=str)}"
        )
        return think(prompt)

    def package_tracker(self, tracking_number: str, carrier: str) -> dict:
        """
        Return tracking URL for a package. Cannot auto-track without carrier accounts.
        Supports UPS, FedEx, USPS, DHL.
        """
        carrier_lower = carrier.lower().strip()
        carrier_key = None

        # Normalize carrier name
        if "ups" in carrier_lower:
            carrier_key = "ups"
        elif "fedex" in carrier_lower or "fed ex" in carrier_lower:
            carrier_key = "fedex"
        elif "usps" in carrier_lower or "postal" in carrier_lower or "post office" in carrier_lower:
            carrier_key = "usps"
        elif "dhl" in carrier_lower:
            carrier_key = "dhl"

        if not carrier_key or carrier_key not in CARRIER_TRACKING_URLS:
            available = list(CARRIER_TRACKING_URLS.keys())
            return {
                "status": "unsupported_carrier",
                "carrier": carrier,
                "tracking_number": tracking_number,
                "message": f"Carrier '{carrier}' not supported. Supported: {', '.join(available)}",
                "tracking_url": None,
            }

        url_template = CARRIER_TRACKING_URLS[carrier_key]
        tracking_url = url_template.format(tracking_number=tracking_number)

        return {
            "carrier": carrier_key.upper(),
            "tracking_number": tracking_number,
            "tracking_url": tracking_url,
            "note": "Visit the tracking URL for current status. Automated tracking requires carrier API credentials.",
        }


travel = TravelIntelligence()
