from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _resolve_timezone(timezone_name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "America/Sao_Paulo":
            return timezone(timedelta(hours=-3))
        return timezone.utc


def _is_today_in_timezone(dt: datetime | None, tzinfo: timezone | ZoneInfo) -> bool:
    if dt is None:
        return False
    return dt.astimezone(tzinfo).date() == datetime.now(tzinfo).date()


def _is_today_or_yesterday_in_timezone(
    dt: datetime | None, tzinfo: timezone | ZoneInfo
) -> bool:
    if dt is None:
        return False
    current_date = datetime.now(tzinfo).date()
    candidate = dt.astimezone(tzinfo).date()
    return candidate in {current_date, current_date - timedelta(days=1)}


def _is_today_or_tomorrow_in_timezone(
    dt: datetime | None, tzinfo: timezone | ZoneInfo
) -> bool:
    if dt is None:
        return False
    current_date = datetime.now(tzinfo).date()
    candidate = dt.astimezone(tzinfo).date()
    return candidate in {current_date, current_date + timedelta(days=1)}


def _title_case_status(status: str) -> str:
    if not status:
        return "Unknown"
    return status.replace("_", " ").strip().title()


@dataclass(frozen=True)
class HostIncidentUpdate:
    status: str
    body: str
    display_at: datetime | None


@dataclass(frozen=True)
class HostIncident:
    source_id: str
    title: str
    status: str
    started_at: datetime | None
    updates: list[HostIncidentUpdate]


@dataclass(frozen=True)
class LocawebReport:
    component_statuses: dict[str, str]
    all_operational: bool
    incidents_today: list[HostIncident]
    error: str | None


@dataclass(frozen=True)
class MetaOrgReport:
    org_id: str
    display_name: str
    statuses: list[str]
    all_no_known_issues: bool


@dataclass(frozen=True)
class MetaReport:
    orgs: list[MetaOrgReport]
    whatsapp_availability: float | None
    whatsapp_latency_p90_ms: float | None
    whatsapp_latency_p99_ms: float | None
    incidents_today: list[HostIncident]
    error: str | None


@dataclass(frozen=True)
class UmbrellaReport:
    component_statuses: dict[str, str]
    component_statuses_human: dict[str, str]
    all_operational: bool
    incidents_active_or_today: list[HostIncident]
    error: str | None


@dataclass(frozen=True)
class HostingerReport:
    overall_ok: bool
    vps_components_non_operational: dict[str, str]
    incidents_active_recent: list[HostIncident]
    upcoming_maintenances: list["HostMaintenance"]
    error: str | None


@dataclass(frozen=True)
class HostMaintenance:
    name: str
    scheduled_for: datetime | None
    scheduled_until: datetime | None


@dataclass(frozen=True)
class WebsiteCheckResult:
    label: str
    url: str
    is_up: bool
    final_status_code: int | None
    error: str | None


@dataclass(frozen=True)
class WebsiteChecksReport:
    checks: list[WebsiteCheckResult]


@dataclass(frozen=True)
class HostSnapshot:
    locaweb: LocawebReport
    meta: MetaReport
    umbrella: UmbrellaReport
    hostinger: HostingerReport
    websites: WebsiteChecksReport


class HostStatusProvider:
    META_ORG_MAPPING = {
        "admin-center": "Meta Admin Center",
        "workplace": "Workplace from Meta",
        "messenger": "Messenger Platform",
        "whatsapp-business-api": "WhatsApp Business API",
    }

    UMBRELLA_STATUS_HUMAN = {
        "operational": "Normal",
        "degraded_performance": "Lento",
        "partial_outage": "Instavel",
        "major_outage": "Fora do ar",
    }
    SITE_TARGETS = [
        ("MV", "https://private-site-01.example/"),
        ("Melior", "https://private-site-02.example/"),
        ("Collis", "https://private-site-03.example/"),
        ("VoipRogini", "https://private-site-04.example/"),
        ("Voip Pet/Sind", "https://private-site-05.example:4433/"),
        ("Chat Rogini", "https://private-site-06.example/app/login"),
        ("Chat Accbook", "https://private-site-07.example/app/login"),
        ("QPanel", "http://private-site-08.example:5001/"),
        ("Resultado", "http://private-site-09.example"),
        ("Echo", "https://private-site-10.example/ui/"),
        ("Node accb", "https://private-site-11.example/signin?redirect=%252F"),
    ]

    def __init__(self, timeout_seconds: int, report_timezone: str) -> None:
        self._timeout_seconds = timeout_seconds
        self._report_tz = _resolve_timezone(report_timezone)

    async def fetch_snapshot(
        self,
        locaweb_components_url: str,
        locaweb_incidents_url: str,
        meta_orgs_url: str,
        meta_outages_url_template: str,
        meta_metrics_url_template: str,
        umbrella_summary_url: str,
        umbrella_incidents_url: str,
        hostinger_summary_url: str,
        hostinger_components_url: str,
        hostinger_incidents_url: str,
        hostinger_status_page_url: str,
    ) -> HostSnapshot:
        locaweb_task = self._fetch_locaweb(locaweb_components_url, locaweb_incidents_url)
        meta_task = self._fetch_meta(
            meta_orgs_url, meta_outages_url_template, meta_metrics_url_template
        )
        umbrella_task = self._fetch_umbrella(umbrella_summary_url, umbrella_incidents_url)
        hostinger_task = self._fetch_hostinger(
            hostinger_summary_url=hostinger_summary_url,
            hostinger_components_url=hostinger_components_url,
            hostinger_incidents_url=hostinger_incidents_url,
            hostinger_status_page_url=hostinger_status_page_url,
        )
        websites_task = self._fetch_websites()
        (
            locaweb_report,
            meta_report,
            umbrella_report,
            hostinger_report,
            websites_report,
        ) = await asyncio.gather(
            locaweb_task,
            meta_task,
            umbrella_task,
            hostinger_task,
            websites_task,
        )
        return HostSnapshot(
            locaweb=locaweb_report,
            meta=meta_report,
            umbrella=umbrella_report,
            hostinger=hostinger_report,
            websites=websites_report,
        )

    async def _fetch_locaweb(
        self,
        components_url: str,
        incidents_url: str,
    ) -> LocawebReport:
        targets = {
            "Hospedagem": "Hospedagem",
            "Email": "Email",
            "Central do Cliente": "Central do Cliente",
            "Outros": "Outros...",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                follow_redirects=True,
            ) as client:
                components_resp, incidents_resp = await asyncio.gather(
                    client.get(components_url),
                    client.get(incidents_url),
                )
            components_resp.raise_for_status()
            incidents_resp.raise_for_status()
            components_payload = components_resp.json()
            incidents_payload = incidents_resp.json()
        except Exception as exc:
            return LocawebReport(
                component_statuses={},
                all_operational=False,
                incidents_today=[],
                error=f"Falha ao consultar Locaweb: {exc}",
            )

        component_statuses: dict[str, str] = {}
        components = components_payload.get("components", [])
        for target_key, label in targets.items():
            match = next(
                (
                    item
                    for item in components
                    if str(item.get("name", "")).strip().startswith(target_key)
                ),
                None,
            )
            component_statuses[label] = str(match.get("status", "unknown")) if match else "not_found"

        all_operational = all(status == "operational" for status in component_statuses.values())
        incidents_today = self._locaweb_incidents_today(incidents_payload)
        return LocawebReport(
            component_statuses=component_statuses,
            all_operational=all_operational,
            incidents_today=incidents_today,
            error=None,
        )

    def _locaweb_incidents_today(self, payload: dict) -> list[HostIncident]:
        incidents = payload.get("incidents", [])
        selected: list[HostIncident] = []
        for incident in incidents:
            created = _parse_dt(incident.get("created_at"))
            started = _parse_dt(incident.get("started_at"))
            if not (_is_today_in_timezone(created, self._report_tz) or _is_today_in_timezone(started, self._report_tz)):
                continue

            updates_raw = incident.get("incident_updates", [])
            updates = [
                HostIncidentUpdate(
                    status=_title_case_status(str(update.get("status", ""))),
                    body=str(update.get("body", "")).strip(),
                    display_at=_parse_dt(update.get("display_at")),
                )
                for update in updates_raw
            ]
            updates.sort(
                key=lambda item: item.display_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            selected.append(
                HostIncident(
                    source_id=str(incident.get("id", "")),
                    title=str(incident.get("name", "")).strip(),
                    status=_title_case_status(str(incident.get("status", ""))),
                    started_at=started,
                    updates=updates,
                )
            )
        selected.sort(
            key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return selected

    async def _fetch_meta(
        self,
        orgs_url: str,
        outages_template: str,
        metrics_template: str,
    ) -> MetaReport:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                follow_redirects=True,
            ) as client:
                orgs_resp = await client.get(orgs_url)
            orgs_resp.raise_for_status()
            orgs_payload = orgs_resp.json()
        except Exception as exc:
            return MetaReport(
                orgs=[],
                whatsapp_availability=None,
                whatsapp_latency_p90_ms=None,
                whatsapp_latency_p99_ms=None,
                incidents_today=[],
                error=f"Falha ao consultar Meta: {exc}",
            )

        orgs_lookup = {str(org.get("id")): org for org in orgs_payload}
        org_reports: list[MetaOrgReport] = []
        for org_id, display_name in self.META_ORG_MAPPING.items():
            org = orgs_lookup.get(org_id)
            if not org:
                org_reports.append(
                    MetaOrgReport(
                        org_id=org_id,
                        display_name=display_name,
                        statuses=["not_found"],
                        all_no_known_issues=False,
                    )
                )
                continue
            statuses = [str(service.get("status", "unknown")) for service in org.get("services", [])]
            all_no_known_issues = len(statuses) > 0 and all(status == "No known issues" for status in statuses)
            org_reports.append(
                MetaOrgReport(
                    org_id=org_id,
                    display_name=display_name,
                    statuses=sorted(set(statuses)),
                    all_no_known_issues=all_no_known_issues,
                )
            )

        availability, p90, p99 = await self._fetch_meta_whatsapp_metrics(metrics_template)
        incidents_today = await self._fetch_meta_whatsapp_incidents_today(outages_template)
        return MetaReport(
            orgs=org_reports,
            whatsapp_availability=availability,
            whatsapp_latency_p90_ms=p90,
            whatsapp_latency_p99_ms=p99,
            incidents_today=incidents_today,
            error=None,
        )

    async def _fetch_meta_whatsapp_metrics(
        self, metrics_template: str
    ) -> tuple[float | None, float | None, float | None]:
        def metric_url(metric: str) -> str:
            return metrics_template.format(org="whatsapp-business-api", metric=metric)

        metric_names = [
            "cloudapi_uptime_daily",
            "event_tagging_latency_last_31_days_p90_s3",
            "event_tagging_latency_last_31_days_p99_s3",
        ]
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=True,
        ) as client:
            responses = await asyncio.gather(
                *(client.get(metric_url(name)) for name in metric_names),
                return_exceptions=True,
            )

        values: list[float | None] = []
        for response in responses:
            if isinstance(response, Exception):
                values.append(None)
                continue
            try:
                response.raise_for_status()
                payload = response.json()
                metric_values = payload.get("values", [])
                values.append(float(metric_values[-1]) if metric_values else None)
            except Exception:
                values.append(None)

        availability = values[0]
        if availability is not None and availability <= 1:
            availability *= 100
        return availability, values[1], values[2]

    async def _fetch_meta_whatsapp_incidents_today(
        self, outages_template: str
    ) -> list[HostIncident]:
        url = outages_template.format(org="whatsapp-business-api")
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []

        selected: list[HostIncident] = []
        for incident in payload:
            started = _parse_dt(incident.get("time"))
            if not _is_today_in_timezone(started, self._report_tz):
                continue
            updates = [
                HostIncidentUpdate(
                    status=str(update.get("status", "")).strip(),
                    body=str(update.get("description", "")).strip(),
                    display_at=_parse_dt(update.get("time")),
                )
                for update in incident.get("posts", [])
            ]
            updates.sort(
                key=lambda item: item.display_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            selected.append(
                HostIncident(
                    source_id=str(incident.get("id", "")),
                    title=f"WhatsApp Business API - {str(incident.get('status', '')).strip()}",
                    status=str(incident.get("status", "")).strip(),
                    started_at=started,
                    updates=updates,
                )
            )
        selected.sort(
            key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return selected

    async def _fetch_hostinger(
        self,
        hostinger_summary_url: str,
        hostinger_components_url: str,
        hostinger_incidents_url: str,
        hostinger_status_page_url: str,
    ) -> HostingerReport:
        del hostinger_components_url, hostinger_incidents_url, hostinger_status_page_url
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                follow_redirects=True,
                verify=False,
            ) as client:
                summary_resp = await client.get(
                    hostinger_summary_url,
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json",
                    },
                )
            summary_resp.raise_for_status()
            summary_payload = summary_resp.json()
            if not isinstance(summary_payload, dict):
                raise ValueError("summary payload invalido")
        except httpx.TimeoutException as exc:
            return HostingerReport(
                overall_ok=False,
                vps_components_non_operational={},
                incidents_active_recent=[],
                upcoming_maintenances=[],
                error=f"Falha ao consultar Hostinger (timeout): {exc}",
            )
        except httpx.HTTPError as exc:
            return HostingerReport(
                overall_ok=False,
                vps_components_non_operational={},
                incidents_active_recent=[],
                upcoming_maintenances=[],
                error=f"Falha ao consultar Hostinger (HTTP): {exc}",
            )
        except Exception as exc:
            return HostingerReport(
                overall_ok=False,
                vps_components_non_operational={},
                incidents_active_recent=[],
                upcoming_maintenances=[],
                error=f"Falha ao consultar Hostinger: {exc}",
            )

        vps_components = self._hostinger_vps_components_non_operational(
            summary_payload.get("components", [])
        )
        incidents = self._hostinger_recent_incidents_with_impact(
            summary_payload.get("incidents", [])
        )
        maintenances = self._hostinger_upcoming_maintenances(
            summary_payload.get("scheduled_maintenances", [])
        )
        overall_ok = len(vps_components) == 0 and len(incidents) == 0
        return HostingerReport(
            overall_ok=overall_ok,
            vps_components_non_operational=vps_components,
            incidents_active_recent=incidents,
            upcoming_maintenances=maintenances,
            error=None,
        )

    def _hostinger_recent_incidents_with_impact(
        self, incidents: list[dict]
    ) -> list[HostIncident]:
        selected: dict[str, HostIncident] = {}
        for incident in incidents:
            status = str(incident.get("status", "")).strip()
            created = _parse_dt(incident.get("created_at"))
            started = _parse_dt(incident.get("started_at"))
            impact = str(incident.get("impact", "")).strip().lower()
            recent = _is_today_or_yesterday_in_timezone(
                created, self._report_tz
            ) or _is_today_or_yesterday_in_timezone(started, self._report_tz)
            if not recent:
                continue
            if impact == "none":
                continue

            updates = [
                HostIncidentUpdate(
                    status=_title_case_status(str(update.get("status", ""))),
                    body=str(update.get("body", "")).strip(),
                    display_at=_parse_dt(update.get("display_at")),
                )
                for update in incident.get("incident_updates", [])
            ]
            updates.sort(
                key=lambda item: item.display_at
                or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            source_id = str(incident.get("id", "")).strip()
            if not source_id:
                source_id = (
                    f"{str(incident.get('name', '')).strip()}-{started}-{created}"
                )
            entry = HostIncident(
                source_id=source_id,
                title=str(incident.get("name", "")).strip(),
                status=_title_case_status(status),
                started_at=started,
                updates=updates,
            )
            selected[entry.source_id] = entry

        values = list(selected.values())
        values.sort(
            key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return values

    def _hostinger_vps_components_non_operational(
        self, components: list[dict]
    ) -> dict[str, str]:
        result: dict[str, str] = {}
        for component in components:
            name = str(component.get("name", "")).strip()
            if not name:
                continue
            lowered = name.lower()
            if "vps" not in lowered and "pve-node" not in lowered:
                continue
            status = str(component.get("status", "")).strip().lower()
            if status == "operational":
                continue
            result[name] = status or "unknown"
        return result

    def _hostinger_upcoming_maintenances(
        self, maintenances: list[dict]
    ) -> list[HostMaintenance]:
        now = datetime.now(self._report_tz)
        result: list[HostMaintenance] = []
        for maintenance in maintenances:
            scheduled_for = _parse_dt(maintenance.get("scheduled_for"))
            if scheduled_for is None:
                continue
            if scheduled_for.astimezone(self._report_tz) <= now:
                continue
            if not _is_today_or_tomorrow_in_timezone(
                scheduled_for, self._report_tz
            ):
                continue
            result.append(
                HostMaintenance(
                    name=str(maintenance.get("name", "")).strip(),
                    scheduled_for=scheduled_for,
                    scheduled_until=_parse_dt(maintenance.get("scheduled_until")),
                )
            )
        result.sort(
            key=lambda item: item.scheduled_for or datetime.max.replace(tzinfo=timezone.utc)
        )
        return result

    async def _fetch_websites(self) -> WebsiteChecksReport:
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=True,
            verify=False,
        ) as client:
            checks = await asyncio.gather(
                *(
                    self._check_single_website(client=client, label=label, url=url)
                    for label, url in self.SITE_TARGETS
                )
            )
        return WebsiteChecksReport(checks=checks)

    async def _check_single_website(
        self,
        client: httpx.AsyncClient,
        label: str,
        url: str,
    ) -> WebsiteCheckResult:
        try:
            response = await client.get(url)
            status_code = int(response.status_code)
            return WebsiteCheckResult(
                label=label,
                url=url,
                is_up=status_code == 200,
                final_status_code=status_code,
                error=None if status_code == 200 else f"HTTP {status_code}",
            )
        except Exception as exc:
            return WebsiteCheckResult(
                label=label,
                url=url,
                is_up=False,
                final_status_code=None,
                error=str(exc),
            )

    async def _fetch_umbrella(
        self,
        summary_url: str,
        incidents_url: str,
    ) -> UmbrellaReport:
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                follow_redirects=True,
            ) as client:
                summary_resp, incidents_resp = await asyncio.gather(
                    client.get(summary_url),
                    client.get(incidents_url),
                )
            summary_resp.raise_for_status()
            incidents_resp.raise_for_status()
            summary_payload = summary_resp.json()
            incidents_payload = incidents_resp.json()
        except Exception as exc:
            return UmbrellaReport(
                component_statuses={},
                component_statuses_human={},
                all_operational=False,
                incidents_active_or_today=[],
                error=f"Falha ao consultar Cisco Umbrella: {exc}",
            )

        components = summary_payload.get("components", [])
        component_statuses: dict[str, str] = {}
        for target in ("Umbrella Global", "Umbrella South America"):
            match = next(
                (
                    item
                    for item in components
                    if str(item.get("name", "")).strip() == target
                ),
                None,
            )
            if not match and target == "Umbrella South America":
                # Some Statuspage setups expose region names without the product prefix.
                match = next(
                    (
                        item
                        for item in components
                        if str(item.get("name", "")).strip() == "South America"
                    ),
                    None,
                )
            component_statuses[target] = str(match.get("status", "not_found")) if match else "not_found"

        component_statuses_human = {
            name: self.UMBRELLA_STATUS_HUMAN.get(status, _title_case_status(status))
            for name, status in component_statuses.items()
        }
        all_operational = all(status == "operational" for status in component_statuses.values())
        incidents = self._umbrella_incidents_active_or_today(incidents_payload)
        return UmbrellaReport(
            component_statuses=component_statuses,
            component_statuses_human=component_statuses_human,
            all_operational=all_operational,
            incidents_active_or_today=incidents,
            error=None,
        )

    def _umbrella_incidents_active_or_today(self, payload: dict) -> list[HostIncident]:
        incidents = payload.get("incidents", [])
        selected: dict[str, HostIncident] = {}
        for incident in incidents:
            status = str(incident.get("status", "")).strip()
            created = _parse_dt(incident.get("created_at"))
            started = _parse_dt(incident.get("started_at"))
            active = status not in {"resolved", "completed"}
            today = _is_today_in_timezone(created, self._report_tz) or _is_today_in_timezone(started, self._report_tz)
            if not (active or today):
                continue
            updates = [
                HostIncidentUpdate(
                    status=_title_case_status(str(update.get("status", ""))),
                    body=str(update.get("body", "")).strip(),
                    display_at=_parse_dt(update.get("display_at")),
                )
                for update in incident.get("incident_updates", [])
            ]
            updates.sort(
                key=lambda item: item.display_at or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            item = HostIncident(
                source_id=str(incident.get("id", "")),
                title=str(incident.get("name", "")).strip(),
                status=_title_case_status(status),
                started_at=started,
                updates=updates,
            )
            selected[item.source_id] = item

        items = list(selected.values())
        items.sort(
            key=lambda item: item.started_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return items
