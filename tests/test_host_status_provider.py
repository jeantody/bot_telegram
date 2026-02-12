from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.automations_lib.providers.host_status_provider import HostStatusProvider


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, responses: dict[str, object], **kwargs) -> None:
        del kwargs
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    async def get(self, url: str):
        if url not in self._responses:
            raise RuntimeError(f"unexpected url: {url}")
        item = self._responses[url]
        if isinstance(item, Exception):
            raise item
        return item


def _build_today_iso(hour: int, minute: int) -> str:
    sao_paulo = timezone(timedelta(hours=-3))
    now = datetime.now(sao_paulo)
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


@pytest.mark.asyncio
async def test_fetch_snapshot_parses_locaweb_meta_and_umbrella(monkeypatch) -> None:
    locaweb_components_url = "https://statusblog.locaweb.com.br/api/v2/components.json"
    locaweb_incidents_url = "https://statusblog.locaweb.com.br/api/v2/incidents.json"
    meta_orgs_url = "https://metastatus.com/data/orgs.json"
    meta_outages_template = "https://metastatus.com/data/outages/{org}.history.json"
    meta_metrics_template = "https://metastatus.com/metrics/{org}/{metric}.json"
    umbrella_summary_url = "https://status.umbrella.com/api/v2/summary.json"
    umbrella_incidents_url = "https://status.umbrella.com/api/v2/incidents.json"
    hostinger_summary_url = "https://statuspage.hostinger.com/api/v2/summary.json"
    hostinger_components_url = "https://statuspage.hostinger.com/api/v2/components.json"
    hostinger_incidents_url = "https://statuspage.hostinger.com/api/v2/incidents.json"
    hostinger_status_page_url = "https://statuspage.hostinger.com/"

    now_iso = _build_today_iso(10, 15)
    responses = {
        locaweb_components_url: FakeResponse(
            {
                "components": [
                    {"name": "Hospedagem", "status": "operational"},
                    {"name": "Email", "status": "operational"},
                    {"name": "Central do Cliente", "status": "operational"},
                    {"name": "Outros Servicos", "status": "operational"},
                ]
            }
        ),
        locaweb_incidents_url: FakeResponse(
            {
                "incidents": [
                    {
                        "id": "lw1",
                        "name": "Instabilidade no acesso",
                        "status": "resolved",
                        "started_at": now_iso,
                        "created_at": now_iso,
                        "incident_updates": [
                            {
                                "status": "identified",
                                "body": "Investigando",
                                "display_at": now_iso,
                            }
                        ],
                    }
                ]
            }
        ),
        meta_orgs_url: FakeResponse(
            [
                {"id": "admin-center", "services": [{"status": "No known issues"}]},
                {"id": "workplace", "services": [{"status": "No known issues"}]},
                {"id": "messenger", "services": [{"status": "No known issues"}]},
                {"id": "whatsapp-business-api", "services": [{"status": "No known issues"}]},
            ]
        ),
        meta_outages_template.format(org="whatsapp-business-api"): FakeResponse(
            [
                {
                    "id": "meta1",
                    "status": "resolved",
                    "time": now_iso,
                    "posts": [{"status": "resolved", "description": "Normalizado", "time": now_iso}],
                }
            ]
        ),
        meta_metrics_template.format(
            org="whatsapp-business-api",
            metric="cloudapi_uptime_daily",
        ): FakeResponse({"values": [99.97]}),
        meta_metrics_template.format(
            org="whatsapp-business-api",
            metric="event_tagging_latency_last_31_days_p90_s3",
        ): FakeResponse({"values": [1397]}),
        meta_metrics_template.format(
            org="whatsapp-business-api",
            metric="event_tagging_latency_last_31_days_p99_s3",
        ): FakeResponse({"values": [2891]}),
        umbrella_summary_url: FakeResponse(
            {
                "components": [
                    {"name": "Umbrella Global", "status": "operational"},
                    {"name": "Umbrella South America", "status": "degraded_performance"},
                ]
            }
        ),
        umbrella_incidents_url: FakeResponse(
            {
                "incidents": [
                    {
                        "id": "umb1",
                        "name": "Latency increase",
                        "status": "investigating",
                        "started_at": now_iso,
                        "created_at": now_iso,
                        "incident_updates": [
                            {"status": "investigating", "body": "Analisando", "display_at": now_iso}
                        ],
                    }
                ]
            }
        ),
        hostinger_summary_url: FakeResponse({"status": {"indicator": "none"}}),
        hostinger_components_url: FakeResponse(
            {"components": [{"name": "Global API", "status": "operational"}]}
        ),
        hostinger_incidents_url: FakeResponse({"incidents": []}),
        hostinger_status_page_url: FakeResponse("<html></html>"),
        "https://private-site-01.example/": FakeResponse({}, status_code=200),
        "https://private-site-02.example/": FakeResponse({}, status_code=200),
        "https://private-site-03.example/": FakeResponse({}, status_code=200),
        "https://private-site-04.example/": FakeResponse({}, status_code=200),
        "https://private-site-05.example:4433/": FakeResponse({}, status_code=200),
        "https://private-site-06.example/app/login": FakeResponse({}, status_code=200),
        "https://private-site-07.example/app/login": FakeResponse({}, status_code=502),
        "http://private-site-08.example:5001/": FakeResponse({}, status_code=200),
        "http://private-site-09.example": FakeResponse({}, status_code=200),
        "https://private-site-10.example/ui/": FakeResponse({}, status_code=200),
        "https://private-site-11.example/signin?redirect=%252F": FakeResponse({}, status_code=200),
    }

    monkeypatch.setattr(
        "src.automations_lib.providers.host_status_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, **kwargs),
    )

    provider = HostStatusProvider(timeout_seconds=10, report_timezone="America/Sao_Paulo")
    snapshot = await provider.fetch_snapshot(
        locaweb_components_url=locaweb_components_url,
        locaweb_incidents_url=locaweb_incidents_url,
        meta_orgs_url=meta_orgs_url,
        meta_outages_url_template=meta_outages_template,
        meta_metrics_url_template=meta_metrics_template,
        umbrella_summary_url=umbrella_summary_url,
        umbrella_incidents_url=umbrella_incidents_url,
        hostinger_summary_url=hostinger_summary_url,
        hostinger_components_url=hostinger_components_url,
        hostinger_incidents_url=hostinger_incidents_url,
        hostinger_status_page_url=hostinger_status_page_url,
    )

    assert snapshot.locaweb.error is None
    assert snapshot.locaweb.all_operational is True
    assert len(snapshot.locaweb.incidents_today) == 1
    assert snapshot.meta.error is None
    assert snapshot.meta.whatsapp_availability == pytest.approx(99.97)
    assert snapshot.meta.whatsapp_latency_p90_ms == pytest.approx(1397)
    assert snapshot.meta.whatsapp_latency_p99_ms == pytest.approx(2891)
    assert len(snapshot.meta.incidents_today) == 1
    assert snapshot.umbrella.error is None
    assert snapshot.umbrella.component_statuses_human["Umbrella South America"] == "Lento"
    assert len(snapshot.umbrella.incidents_active_or_today) == 1
    assert snapshot.hostinger.mode == "api"
    assert snapshot.hostinger.overall_ok is True
    assert len(snapshot.websites.checks) == 11
    chat_accbook = next(
        item for item in snapshot.websites.checks if item.label == "Chat Accbook"
    )
    assert chat_accbook.is_up is False


@pytest.mark.asyncio
async def test_fetch_snapshot_keeps_partial_output_when_one_source_fails(monkeypatch) -> None:
    locaweb_components_url = "https://statusblog.locaweb.com.br/api/v2/components.json"
    locaweb_incidents_url = "https://statusblog.locaweb.com.br/api/v2/incidents.json"
    meta_orgs_url = "https://metastatus.com/data/orgs.json"
    meta_outages_template = "https://metastatus.com/data/outages/{org}.history.json"
    meta_metrics_template = "https://metastatus.com/metrics/{org}/{metric}.json"
    umbrella_summary_url = "https://status.umbrella.com/api/v2/summary.json"
    umbrella_incidents_url = "https://status.umbrella.com/api/v2/incidents.json"
    hostinger_summary_url = "https://statuspage.hostinger.com/api/v2/summary.json"
    hostinger_components_url = "https://statuspage.hostinger.com/api/v2/components.json"
    hostinger_incidents_url = "https://statuspage.hostinger.com/api/v2/incidents.json"
    hostinger_status_page_url = "https://statuspage.hostinger.com/"

    responses = {
        locaweb_components_url: RuntimeError("locaweb down"),
        locaweb_incidents_url: FakeResponse({"incidents": []}),
        meta_orgs_url: FakeResponse([]),
        meta_outages_template.format(org="whatsapp-business-api"): FakeResponse([]),
        meta_metrics_template.format(
            org="whatsapp-business-api",
            metric="cloudapi_uptime_daily",
        ): FakeResponse({"values": []}),
        meta_metrics_template.format(
            org="whatsapp-business-api",
            metric="event_tagging_latency_last_31_days_p90_s3",
        ): FakeResponse({"values": []}),
        meta_metrics_template.format(
            org="whatsapp-business-api",
            metric="event_tagging_latency_last_31_days_p99_s3",
        ): FakeResponse({"values": []}),
        umbrella_summary_url: FakeResponse({"components": []}),
        umbrella_incidents_url: FakeResponse({"incidents": []}),
        hostinger_summary_url: RuntimeError("blocked"),
        hostinger_components_url: RuntimeError("blocked"),
        hostinger_incidents_url: RuntimeError("blocked"),
        hostinger_status_page_url: FakeResponse({}, status_code=200),
        "https://private-site-01.example/": FakeResponse({}, status_code=200),
        "https://private-site-02.example/": FakeResponse({}, status_code=200),
        "https://private-site-03.example/": FakeResponse({}, status_code=200),
        "https://private-site-04.example/": FakeResponse({}, status_code=200),
        "https://private-site-05.example:4433/": FakeResponse({}, status_code=200),
        "https://private-site-06.example/app/login": FakeResponse({}, status_code=200),
        "https://private-site-07.example/app/login": FakeResponse({}, status_code=200),
        "http://private-site-08.example:5001/": FakeResponse({}, status_code=200),
        "http://private-site-09.example": FakeResponse({}, status_code=200),
        "https://private-site-10.example/ui/": FakeResponse({}, status_code=200),
        "https://private-site-11.example/signin?redirect=%252F": FakeResponse({}, status_code=200),
    }

    monkeypatch.setattr(
        "src.automations_lib.providers.host_status_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, **kwargs),
    )

    provider = HostStatusProvider(timeout_seconds=10, report_timezone="America/Sao_Paulo")
    snapshot = await provider.fetch_snapshot(
        locaweb_components_url=locaweb_components_url,
        locaweb_incidents_url=locaweb_incidents_url,
        meta_orgs_url=meta_orgs_url,
        meta_outages_url_template=meta_outages_template,
        meta_metrics_url_template=meta_metrics_template,
        umbrella_summary_url=umbrella_summary_url,
        umbrella_incidents_url=umbrella_incidents_url,
        hostinger_summary_url=hostinger_summary_url,
        hostinger_components_url=hostinger_components_url,
        hostinger_incidents_url=hostinger_incidents_url,
        hostinger_status_page_url=hostinger_status_page_url,
    )

    assert snapshot.locaweb.error is not None
    assert snapshot.meta.error is None
    assert snapshot.umbrella.error is None
    assert snapshot.hostinger.mode == "fallback_page"
    assert snapshot.hostinger.overall_ok is True


@pytest.mark.asyncio
async def test_websites_rule_only_200_is_up(monkeypatch) -> None:
    responses = {
        "https://private-site-01.example/": FakeResponse({}, status_code=200),
        "https://private-site-02.example/": FakeResponse({}, status_code=301),
        "https://private-site-03.example/": FakeResponse({}, status_code=502),
        "https://private-site-04.example/": RuntimeError("timeout"),
        "https://private-site-05.example:4433/": FakeResponse({}, status_code=200),
        "https://private-site-06.example/app/login": FakeResponse({}, status_code=200),
        "https://private-site-07.example/app/login": FakeResponse({}, status_code=200),
        "http://private-site-08.example:5001/": FakeResponse({}, status_code=200),
        "http://private-site-09.example": FakeResponse({}, status_code=200),
        "https://private-site-10.example/ui/": FakeResponse({}, status_code=200),
        "https://private-site-11.example/signin?redirect=%252F": FakeResponse({}, status_code=200),
    }
    monkeypatch.setattr(
        "src.automations_lib.providers.host_status_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, **kwargs),
    )
    provider = HostStatusProvider(timeout_seconds=10, report_timezone="America/Sao_Paulo")
    report = await provider._fetch_websites()

    mv = next(item for item in report.checks if item.label == "MV")
    melior = next(item for item in report.checks if item.label == "Melior")
    collis = next(item for item in report.checks if item.label == "Collis")
    voip = next(item for item in report.checks if item.label == "VoipRogini")
    assert mv.is_up is True
    assert melior.is_up is False
    assert collis.is_up is False
    assert voip.is_up is False
