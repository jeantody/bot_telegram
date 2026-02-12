from __future__ import annotations

from datetime import timezone
import html

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.providers.weather_provider import WeatherProvider


class StatusWeatherAutomation:
    name = "status_weather"
    trigger = "status"

    def __init__(self, provider: WeatherProvider) -> None:
        self._provider = provider

    async def run(self, context: AutomationContext) -> AutomationResult:
        snapshot = await self._provider.fetch_weather(
            city_name=context.settings.weather_city_name,
            timezone_name=context.settings.weather_timezone,
        )
        message = (
            "<b>Clima - Sao Paulo (capital)</b>\n"
            f"Agora: <b>{snapshot.current_temperature_c:.1f}C</b>\n"
            f"12:00 ------- : <b>{snapshot.temperature_12_c:.1f}C</b>\n"
            f"19:00 ------- : <b>{snapshot.temperature_19_c:.1f}C</b>\n"
            f"21:00 ------- : <b>{snapshot.temperature_21_c:.1f}C</b>\n"
            f"Probabilidade de Chuva 17h/19h: "
            f"media <b>{snapshot.rain_probability_avg_1700_1900:.0f}%</b>, "
            f"pico <b>{snapshot.rain_probability_peak_1700_1900:.0f}%</b>."
        )
        return AutomationResult(
            title="Clima",
            message=message,
            source_label=html.escape("Open-Meteo"),
            generated_at=context.utc_now().astimezone(timezone.utc),
            ok=True,
        )
