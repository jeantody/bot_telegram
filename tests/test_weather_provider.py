from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.automations_lib.providers.weather_provider import WeatherProvider


def test_build_snapshot_temperatures_and_rain_window() -> None:
    date = "2026-02-12"
    hourly = {
        "time": [f"{date}T{hour:02d}:00" for hour in range(24)],
        "temperature_2m": [10 + hour for hour in range(24)],
        "precipitation_probability": [hour for hour in range(24)],
    }
    now_local = datetime(2026, 2, 12, 17, 45, tzinfo=timezone(timedelta(hours=-3)))

    snapshot = WeatherProvider.build_snapshot(hourly=hourly, now_local=now_local)

    assert snapshot.current_temperature_c == 28.0
    assert snapshot.temperature_12_c == 22.0
    assert snapshot.temperature_19_c == 29.0
    assert snapshot.temperature_21_c == 31.0
    assert snapshot.rain_probability_avg_1700_1900 == 18.0
    assert snapshot.rain_probability_peak_1700_1900 == 19.0


def test_current_local_datetime_fallback_for_sao_paulo(monkeypatch) -> None:
    class FakeZoneInfoNotFoundError(Exception):
        pass

    def raise_zoneinfo_not_found(_key: str):
        raise FakeZoneInfoNotFoundError("missing tz")

    monkeypatch.setattr(
        "src.automations_lib.providers.weather_provider.ZoneInfoNotFoundError",
        FakeZoneInfoNotFoundError,
    )
    monkeypatch.setattr(
        "src.automations_lib.providers.weather_provider.ZoneInfo",
        raise_zoneinfo_not_found,
    )

    now_local = WeatherProvider.current_local_datetime("America/Sao_Paulo")

    assert now_local.tzinfo is not None
    assert now_local.utcoffset() == timedelta(hours=-3)
