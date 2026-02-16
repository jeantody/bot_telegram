from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from src.automations_lib.providers.host_status_provider import HostStatusProvider


TEST_SITE_TARGETS: tuple[tuple[str, str], ...] = (
    ("Site 01", "https://site01.test/"),
    ("Site 02", "https://site02.test/"),
    ("Site 03", "https://site03.test/"),
    ("Site 04", "https://site04.test/"),
    ("Site 05", "https://site05.test/"),
    ("Site 06", "https://site06.test/login"),
    ("Site 07", "https://site07.test/login"),
    ("Site 08", "http://site08.test:5001/"),
    ("Site 09", "http://site09.test"),
    ("Site 10", "https://site10.test/ui/"),
    ("Site 11", "https://site11.test/signin?redirect=%252F"),
)


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

    async def get(self, url: str, **kwargs):
        del kwargs
        if url not in self._responses:
            raise RuntimeError(f"unexpected url: {url}")
        item = self._responses[url]
        if isinstance(item, Exception):
            raise item
        return item


def _build_day_offset_iso(day_offset: int, hour: int, minute: int) -> str:
    sao_paulo = timezone(timedelta(hours=-3))
    now = datetime.now(sao_paulo)
    target = now + timedelta(days=day_offset)
    return target.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def _build_hours_offset_iso(hours: int) -> str:
    sao_paulo = timezone(timedelta(hours=-3))
    target = datetime.now(sao_paulo) + timedelta(hours=hours)
    return target.replace(second=0, microsecond=0).isoformat()


def _ok_site_responses() -> dict[str, object]:
    return {url: FakeResponse({}, status_code=200) for _, url in TEST_SITE_TARGETS}


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

    now_iso = _build_day_offset_iso(0, 10, 15)
    yesterday_iso = _build_day_offset_iso(-1, 9, 10)
    two_days_ago_iso = _build_day_offset_iso(-2, 8, 0)
    today_past_iso = _build_day_offset_iso(0, 0, 30)
    today_past_end_iso = _build_day_offset_iso(0, 1, 30)
    yesterday_cross_start_iso = _build_day_offset_iso(-1, 23, 0)
    yesterday_cross_end_iso = _build_day_offset_iso(0, 0, 0)
    today_future_iso = _build_hours_offset_iso(2)
    today_future_end_iso = _build_hours_offset_iso(3)
    tomorrow_iso = _build_day_offset_iso(1, 23, 0)
    tomorrow_end_iso = _build_day_offset_iso(1, 23, 30)
    after_tomorrow_iso = _build_day_offset_iso(2, 10, 0)
    after_tomorrow_end_iso = _build_day_offset_iso(2, 11, 0)
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
        hostinger_summary_url: FakeResponse(
            {
                "components": [
                    {"name": "VPS BR-01", "status": "operational"},
                    {"name": "pve-node-22", "status": "major_outage"},
                    {"name": "Shared Hosting", "status": "degraded_performance"},
                ],
                "incidents": [
                    {
                        "id": "h1",
                        "name": "Hostinger incident major",
                        "status": "investigating",
                        "impact": "major",
                        "created_at": now_iso,
                        "started_at": now_iso,
                        "incident_updates": [],
                    },
                    {
                        "id": "h2",
                        "name": "Hostinger incident yesterday",
                        "status": "resolved",
                        "impact": "minor",
                        "created_at": yesterday_iso,
                        "started_at": yesterday_iso,
                        "incident_updates": [],
                    },
                    {
                        "id": "h3",
                        "name": "Hostinger incident none",
                        "status": "resolved",
                        "impact": "none",
                        "created_at": now_iso,
                        "started_at": now_iso,
                        "incident_updates": [],
                    },
                    {
                        "id": "h4",
                        "name": "Hostinger incident old",
                        "status": "resolved",
                        "impact": "critical",
                        "created_at": two_days_ago_iso,
                        "started_at": two_days_ago_iso,
                        "incident_updates": [],
                    },
                ],
                "scheduled_maintenances": [
                    {
                        "id": "m_yesterday_to_today",
                        "name": "Maintenance yesterday crossing midnight",
                        "scheduled_for": yesterday_cross_start_iso,
                        "scheduled_until": yesterday_cross_end_iso,
                    },
                    {
                        "id": "m_before_now_today",
                        "name": "Maintenance today past hour",
                        "scheduled_for": today_past_iso,
                        "scheduled_until": today_past_end_iso,
                    },
                    {
                        "id": "m0",
                        "name": "Maintenance today",
                        "scheduled_for": today_future_iso,
                        "scheduled_until": today_future_end_iso,
                    },
                    {
                        "id": "m1",
                        "name": "Maintenance future",
                        "scheduled_for": tomorrow_iso,
                        "scheduled_until": tomorrow_end_iso,
                    },
                    {
                        "id": "m2",
                        "name": "Maintenance after tomorrow",
                        "scheduled_for": after_tomorrow_iso,
                        "scheduled_until": after_tomorrow_end_iso,
                    },
                    {
                        "id": "m3",
                        "name": "Maintenance past",
                        "scheduled_for": two_days_ago_iso,
                        "scheduled_until": yesterday_iso,
                    },
                ],
            }
        ),
        **_ok_site_responses(),
        "https://site07.test/login": FakeResponse({}, status_code=502),
    }

    monkeypatch.setattr(
        "src.automations_lib.providers.host_status_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, **kwargs),
    )

    provider = HostStatusProvider(
        timeout_seconds=10,
        report_timezone="America/Sao_Paulo",
        site_targets=TEST_SITE_TARGETS,
    )
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
    assert snapshot.hostinger.overall_ok is False
    assert "pve-node-22" in snapshot.hostinger.vps_components_non_operational
    assert "VPS BR-01" not in snapshot.hostinger.vps_components_non_operational
    assert len(snapshot.hostinger.incidents_active_recent) == 2
    assert len(snapshot.hostinger.upcoming_maintenances) == 2
    names = {item.name for item in snapshot.hostinger.upcoming_maintenances}
    assert "Maintenance today past hour" in names
    assert "Maintenance today" in names
    assert "Maintenance yesterday crossing midnight" not in names
    assert "Maintenance future" not in names
    assert "Maintenance after tomorrow" not in names
    assert len(snapshot.websites.checks) == 11
    site07 = next(item for item in snapshot.websites.checks if item.label == "Site 07")
    assert site07.is_up is False


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
        hostinger_summary_url: httpx.ReadTimeout("timeout"),
        **_ok_site_responses(),
    }

    monkeypatch.setattr(
        "src.automations_lib.providers.host_status_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, **kwargs),
    )

    provider = HostStatusProvider(
        timeout_seconds=10,
        report_timezone="America/Sao_Paulo",
        site_targets=TEST_SITE_TARGETS,
    )
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
    assert snapshot.hostinger.overall_ok is False
    assert snapshot.hostinger.error is not None


@pytest.mark.asyncio
async def test_hostinger_http_error_is_handled(monkeypatch) -> None:
    responses = {
        "https://statuspage.hostinger.com/api/v2/summary.json": httpx.HTTPError(
            "http 403"
        ),
        **_ok_site_responses(),
        "https://statusblog.locaweb.com.br/api/v2/components.json": FakeResponse({"components": []}),
        "https://statusblog.locaweb.com.br/api/v2/incidents.json": FakeResponse({"incidents": []}),
        "https://metastatus.com/data/orgs.json": FakeResponse([]),
        "https://metastatus.com/data/outages/whatsapp-business-api.history.json": FakeResponse([]),
        "https://metastatus.com/metrics/whatsapp-business-api/cloudapi_uptime_daily.json": FakeResponse({"values": []}),
        "https://metastatus.com/metrics/whatsapp-business-api/event_tagging_latency_last_31_days_p90_s3.json": FakeResponse({"values": []}),
        "https://metastatus.com/metrics/whatsapp-business-api/event_tagging_latency_last_31_days_p99_s3.json": FakeResponse({"values": []}),
        "https://status.umbrella.com/api/v2/summary.json": FakeResponse({"components": []}),
        "https://status.umbrella.com/api/v2/incidents.json": FakeResponse({"incidents": []}),
    }
    monkeypatch.setattr(
        "src.automations_lib.providers.host_status_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, **kwargs),
    )
    provider = HostStatusProvider(
        timeout_seconds=10,
        report_timezone="America/Sao_Paulo",
        site_targets=TEST_SITE_TARGETS,
    )
    snapshot = await provider.fetch_snapshot(
        locaweb_components_url="https://statusblog.locaweb.com.br/api/v2/components.json",
        locaweb_incidents_url="https://statusblog.locaweb.com.br/api/v2/incidents.json",
        meta_orgs_url="https://metastatus.com/data/orgs.json",
        meta_outages_url_template="https://metastatus.com/data/outages/{org}.history.json",
        meta_metrics_url_template="https://metastatus.com/metrics/{org}/{metric}.json",
        umbrella_summary_url="https://status.umbrella.com/api/v2/summary.json",
        umbrella_incidents_url="https://status.umbrella.com/api/v2/incidents.json",
        hostinger_summary_url="https://statuspage.hostinger.com/api/v2/summary.json",
        hostinger_components_url="https://statuspage.hostinger.com/api/v2/components.json",
        hostinger_incidents_url="https://statuspage.hostinger.com/api/v2/incidents.json",
        hostinger_status_page_url="https://statuspage.hostinger.com/",
    )
    assert snapshot.hostinger.overall_ok is False
    assert "Falha ao consultar Hostinger" in (snapshot.hostinger.error or "")


@pytest.mark.asyncio
async def test_websites_rule_only_200_is_up(monkeypatch) -> None:
    responses = {
        **_ok_site_responses(),
        "https://site02.test/": FakeResponse({}, status_code=301),
        "https://site03.test/": FakeResponse({}, status_code=502),
        "https://site04.test/": RuntimeError("timeout"),
    }
    monkeypatch.setattr(
        "src.automations_lib.providers.host_status_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, **kwargs),
    )
    provider = HostStatusProvider(
        timeout_seconds=10,
        report_timezone="America/Sao_Paulo",
        site_targets=TEST_SITE_TARGETS,
    )
    report = await provider._fetch_websites()

    site01 = next(item for item in report.checks if item.label == "Site 01")
    site02 = next(item for item in report.checks if item.label == "Site 02")
    site03 = next(item for item in report.checks if item.label == "Site 03")
    site04 = next(item for item in report.checks if item.label == "Site 04")
    assert site01.is_up is True
    assert site02.is_up is False
    assert site03.is_up is False
    assert site04.is_up is False


@pytest.mark.asyncio
async def test_hostinger_maintenance_filters_by_scheduled_for_today_only(monkeypatch) -> None:
    hostinger_summary_url = "https://statuspage.hostinger.com/api/v2/summary.json"
    now_iso = _build_day_offset_iso(0, 10, 15)
    yesterday_cross_start_iso = _build_day_offset_iso(-1, 23, 0)
    yesterday_cross_end_iso = _build_day_offset_iso(0, 0, 0)
    today_cross_start_iso = _build_day_offset_iso(0, 23, 0)
    today_cross_end_iso = _build_day_offset_iso(1, 1, 0)
    tomorrow_iso = _build_day_offset_iso(1, 9, 0)
    tomorrow_end_iso = _build_day_offset_iso(1, 10, 0)

    responses = {
        "https://statusblog.locaweb.com.br/api/v2/components.json": FakeResponse({"components": []}),
        "https://statusblog.locaweb.com.br/api/v2/incidents.json": FakeResponse({"incidents": []}),
        "https://metastatus.com/data/orgs.json": FakeResponse([]),
        "https://metastatus.com/data/outages/whatsapp-business-api.history.json": FakeResponse([]),
        "https://metastatus.com/metrics/whatsapp-business-api/cloudapi_uptime_daily.json": FakeResponse({"values": []}),
        "https://metastatus.com/metrics/whatsapp-business-api/event_tagging_latency_last_31_days_p90_s3.json": FakeResponse({"values": []}),
        "https://metastatus.com/metrics/whatsapp-business-api/event_tagging_latency_last_31_days_p99_s3.json": FakeResponse({"values": []}),
        "https://status.umbrella.com/api/v2/summary.json": FakeResponse({"components": []}),
        "https://status.umbrella.com/api/v2/incidents.json": FakeResponse({"incidents": []}),
        hostinger_summary_url: FakeResponse(
            {
                "components": [],
                "incidents": [
                    {
                        "id": "h1",
                        "name": "Hostinger incident major",
                        "status": "investigating",
                        "impact": "major",
                        "created_at": now_iso,
                        "started_at": now_iso,
                        "incident_updates": [],
                    }
                ],
                "scheduled_maintenances": [
                    {
                        "id": "yesterday_to_today",
                        "name": "Started yesterday, ends today",
                        "scheduled_for": yesterday_cross_start_iso,
                        "scheduled_until": yesterday_cross_end_iso,
                    },
                    {
                        "id": "today_to_tomorrow",
                        "name": "Starts today, ends tomorrow",
                        "scheduled_for": today_cross_start_iso,
                        "scheduled_until": today_cross_end_iso,
                    },
                    {
                        "id": "tomorrow_only",
                        "name": "Starts tomorrow",
                        "scheduled_for": tomorrow_iso,
                        "scheduled_until": tomorrow_end_iso,
                    },
                ],
            }
        ),
        **_ok_site_responses(),
    }

    monkeypatch.setattr(
        "src.automations_lib.providers.host_status_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, **kwargs),
    )

    provider = HostStatusProvider(
        timeout_seconds=10,
        report_timezone="America/Sao_Paulo",
        site_targets=TEST_SITE_TARGETS,
    )
    snapshot = await provider.fetch_snapshot(
        locaweb_components_url="https://statusblog.locaweb.com.br/api/v2/components.json",
        locaweb_incidents_url="https://statusblog.locaweb.com.br/api/v2/incidents.json",
        meta_orgs_url="https://metastatus.com/data/orgs.json",
        meta_outages_url_template="https://metastatus.com/data/outages/{org}.history.json",
        meta_metrics_url_template="https://metastatus.com/metrics/{org}/{metric}.json",
        umbrella_summary_url="https://status.umbrella.com/api/v2/summary.json",
        umbrella_incidents_url="https://status.umbrella.com/api/v2/incidents.json",
        hostinger_summary_url=hostinger_summary_url,
        hostinger_components_url="https://statuspage.hostinger.com/api/v2/components.json",
        hostinger_incidents_url="https://statuspage.hostinger.com/api/v2/incidents.json",
        hostinger_status_page_url="https://statuspage.hostinger.com/",
    )

    names = {item.name for item in snapshot.hostinger.upcoming_maintenances}
    assert "Starts today, ends tomorrow" in names
    assert "Started yesterday, ends today" not in names
    assert "Starts tomorrow" not in names
