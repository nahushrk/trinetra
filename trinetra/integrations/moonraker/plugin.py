"""Moonraker implementation of the printer integration protocol."""

from __future__ import annotations

from typing import Optional, Sequence

from trinetra.integrations.moonraker.api import MoonrakerAPI
from trinetra.integrations.moonraker.types import (
    MoonrakerConfigBlock,
    MoonrakerIntegrationSettings,
)
from trinetra.integrations.protocol import (
    IntegrationUIState,
    PrinterIntegration,
    PrinterServiceClient,
    RuntimeIntegrationConfig,
)


class MoonrakerIntegration(PrinterIntegration[MoonrakerIntegrationSettings]):
    integration_id = "moonraker"
    display_name = "Moonraker"
    description = "Klipper/Moonraker integration for print stats and queue management."

    def _integration_block(self, config: RuntimeIntegrationConfig) -> MoonrakerConfigBlock:
        integrations = config.get("integrations")
        if not isinstance(integrations, dict):
            return {}
        moonraker = integrations.get("moonraker")
        if not isinstance(moonraker, dict):
            return {}
        return moonraker

    def get_settings(self, config: RuntimeIntegrationConfig) -> MoonrakerIntegrationSettings:
        block = self._integration_block(config)
        base_url = block.get("base_url") or config.get("moonraker_url") or ""
        enabled = bool(block.get("enabled", False))
        return MoonrakerIntegrationSettings(enabled=enabled, base_url=str(base_url).strip())

    def is_enabled(self, config: RuntimeIntegrationConfig) -> bool:
        return self.get_settings(config).enabled

    def is_configured(self, config: RuntimeIntegrationConfig) -> bool:
        settings = self.get_settings(config)
        return settings.configured

    def create_client(self, config: RuntimeIntegrationConfig) -> Optional[PrinterServiceClient]:
        settings = self.get_settings(config)
        if not settings.enabled or not settings.base_url:
            return None
        return MoonrakerAPI(settings.base_url)

    def queue_jobs(
        self, config: RuntimeIntegrationConfig, filenames: Sequence[str], reset: bool = False
    ) -> bool:
        client = self.create_client(config)
        if client is None:
            return False
        return client.queue_job(list(filenames), reset)

    def get_ui_state(self, config: RuntimeIntegrationConfig) -> IntegrationUIState:
        settings = self.get_settings(config)
        return {
            "id": self.integration_id,
            "name": self.display_name,
            "description": self.description,
            "enabled": settings.enabled,
            "configured": settings.configured,
            "settings": settings.to_ui_settings(),
        }
