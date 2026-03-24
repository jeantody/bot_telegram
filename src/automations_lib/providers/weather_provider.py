from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx


@dataclass(frozen=True)
class WeatherSnapshot:
    current_temperature_c: float
    temperature_12_c: float
    temperature_19_c: float
    temperature_21_c: float
    rain_probability_avg_1700_1900: float
    rain_probability_peak_1700_1900: float
    generated_at_local: datetime


class WeatherProvider:
    GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds
        self._cached_coords: tuple[float, float] | None = None

    async def fetch_weather(self, city_name: str, timezone_name: str) -> WeatherSnapshot:
        coords = await self._get_coordinates(city_name)
        payload = await self._get_forecast(coords[0], coords[1], timezone_name)
        now_local = self.current_local_datetime(timezone_name)
        return self.build_snapshot(payload["hourly"], now_local)

    @staticmethod
    def current_local_datetime(timezone_name: str) -> datetime:
        try:
            return datetime.now(ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            # Windows environments may not have IANA tzdata available by default.
            if timezone_name == "America/Sao_Paulo":
                return datetime.now(timezone(timedelta(hours=-3)))
            return datetime.now(timezone.utc)

    async def _get_coordinates(self, city_name: str) -> tuple[float, float]:
        if self._cached_coords:
            return self._cached_coords

        params = {"name": city_name, "count": 1, "language": "pt", "format": "json"}
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(self.GEOCODE_URL, params=params)
            response.raise_for_status()
            data = response.json()

        results = data.get("results", [])
        if not results:
            raise ValueError(f"Nao foi possivel localizar cidade: {city_name}")
        lat = float(results[0]["latitude"])
        lon = float(results[0]["longitude"])
        self._cached_coords = (lat, lon)
        return self._cached_coords

    async def _get_forecast(
        self, latitude: float, longitude: float, timezone_name: str
    ) -> dict:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": "temperature_2m,precipitation_probability",
            "timezone": timezone_name,
            "forecast_days": 1,
        }
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(self.FORECAST_URL, params=params)
            response.raise_for_status()
            return response.json()

    @staticmethod
    def build_snapshot(hourly: dict, now_local: datetime) -> WeatherSnapshot:
        times = [datetime.fromisoformat(raw) for raw in hourly["time"]]
        temps = [float(v) for v in hourly["temperature_2m"]]
        rains = [float(v) for v in hourly["precipitation_probability"]]
        index_by_key = {t.strftime("%Y-%m-%dT%H:00"): idx for idx, t in enumerate(times)}

        def temp_for_hour(hour: int) -> float:
            key = now_local.strftime("%Y-%m-%d") + f"T{hour:02d}:00"
            idx = index_by_key.get(key)
            if idx is None:
                raise ValueError(f"Horario indisponivel na previsao: {key}")
            return temps[idx]

        naive_now = now_local.replace(tzinfo=None)
        current_idx = min(
            range(len(times)), key=lambda idx: abs(times[idx] - naive_now)
        )
        rain_17 = temp_for_series(rains, index_by_key, now_local, 17)
        rain_18 = temp_for_series(rains, index_by_key, now_local, 18)
        rain_19 = temp_for_series(rains, index_by_key, now_local, 19)
        rain_values = [rain_17, rain_18, rain_19]

        return WeatherSnapshot(
            current_temperature_c=temps[current_idx],
            temperature_12_c=temp_for_hour(12),
            temperature_19_c=temp_for_hour(19),
            temperature_21_c=temp_for_hour(21),
            rain_probability_avg_1700_1900=sum(rain_values) / len(rain_values),
            rain_probability_peak_1700_1900=max(rain_values),
            generated_at_local=now_local,
        )


def temp_for_series(
    values: list[float],
    index_by_key: dict[str, int],
    now_local: datetime,
    hour: int,
) -> float:
    key = now_local.strftime("%Y-%m-%d") + f"T{hour:02d}:00"
    idx = index_by_key.get(key)
    if idx is None:
        raise ValueError(f"Horario indisponivel na previsao: {key}")
    return values[idx]
