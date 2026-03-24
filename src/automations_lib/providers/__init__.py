"""Data providers for automations."""

from src.automations_lib.providers.zabbix_provider import (
    ZabbixError,
    ZabbixIntegrationStatus,
    ZabbixProvider,
)

__all__ = [
    "ZabbixError",
    "ZabbixIntegrationStatus",
    "ZabbixProvider",
]
