"""Integration registry for printer backends."""

from __future__ import annotations

from typing import Dict, List, Optional

from trinetra.integrations.moonraker.plugin import MoonrakerIntegration
from trinetra.integrations.protocol import (
    IntegrationUIState,
    PrinterIntegration,
    RuntimeIntegrationConfig,
)


_INTEGRATIONS: Dict[str, PrinterIntegration[object]] = {
    "moonraker": MoonrakerIntegration(),
}


def get_printer_integration(integration_id: str) -> Optional[PrinterIntegration[object]]:
    return _INTEGRATIONS.get(integration_id)


def list_printer_integrations(config: RuntimeIntegrationConfig) -> List[IntegrationUIState]:
    return [integration.get_ui_state(config) for integration in _INTEGRATIONS.values()]
