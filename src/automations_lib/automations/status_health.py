from __future__ import annotations

from datetime import timezone
import html

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.providers.health_provider import HealthProvider
from src.automations_lib.providers.weather_provider import WeatherProvider


class StatusHealthAutomation:
    name = "status_health"
    trigger = "health"

    def __init__(self, provider: HealthProvider) -> None:
        self._provider = provider

    async def run(self, context: AutomationContext) -> AutomationResult:
        settings = context.settings
        probes = [
            ("Noticias:G1", "https://g1.globo.com/rss/g1/"),
            ("Noticias:TecMundo", "https://rss.tecmundo.com.br/feed"),
            ("Noticias:BoletimSec", "https://boletimsec.com/feed/"),
            ("Clima:Geocoding", WeatherProvider.GEOCODE_URL),
            ("Clima:Forecast", WeatherProvider.FORECAST_URL),
            ("Trends:Primario", settings.trends_primary_url),
            ("Trends:Fallback", settings.trends_fallback_url),
            ("Finance:AwesomeAPI", settings.finance_awesomeapi_url),
            ("Finance:YahooB3", settings.finance_yahoo_b3_url),
            ("Locaweb:Components", settings.locaweb_components_url),
            ("Locaweb:Incidents", settings.locaweb_incidents_url),
            ("Meta:Orgs", settings.meta_orgs_url),
            (
                "Meta:Outages",
                settings.meta_outages_url_template.format(org="whatsapp-business-api"),
            ),
            (
                "Meta:Metrics",
                settings.meta_metrics_url_template.format(
                    org="whatsapp-business-api",
                    metric="cloudapi_uptime_daily",
                ),
            ),
            ("Umbrella:Summary", settings.umbrella_summary_url),
            ("Umbrella:Incidents", settings.umbrella_incidents_url),
            ("Hostinger:Summary", settings.hostinger_summary_url),
        ]
        results = await self._provider.fetch_health(probes)
        ok_count = sum(1 for item in results if item.ok)
        total = len(results)
        lines = [
            "<b>Health Check</b>",
            f"Trace: <code>{html.escape(context.trace_id)}</code>",
            f"Fontes OK: <b>{ok_count}/{total}</b>",
        ]
        failed = [item for item in results if not item.ok]
        for item in results:
            status = "OK" if item.ok else "FALHA"
            latency = (
                f"{item.latency_ms}ms" if item.latency_ms is not None else "n/a"
            )
            status_code = (
                str(item.status_code) if item.status_code is not None else "-"
            )
            lines.append(
                f"- {html.escape(item.source)}: {status} | latency {latency} | status {status_code}"
            )
        if failed:
            lines.append("<b>Falhas por fonte</b>")
            for item in failed:
                lines.append(
                    f"- {html.escape(item.source)}: {html.escape(item.error or 'erro desconhecido')}"
                )
        return AutomationResult(
            title="Health",
            message="\n".join(lines),
            source_label="Internal Provider Health",
            generated_at=context.utc_now().astimezone(timezone.utc),
            ok=len(failed) == 0,
            severity="info" if not failed else "alerta",
        )

