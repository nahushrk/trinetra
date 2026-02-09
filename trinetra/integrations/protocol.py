"""Protocols for pluggable printer integrations."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, TypeVar, TypedDict, runtime_checkable


class JobHistoryEntry(TypedDict, total=False):
    filename: str
    status: str
    print_duration: float
    total_duration: float
    filament_used: float
    start_time: float
    end_time: float
    job_id: str


class HistoryPayload(TypedDict, total=False):
    jobs: List[JobHistoryEntry]


RuntimeIntegrationConfig = Mapping[str, Any]


class IntegrationUIState(TypedDict):
    id: str
    name: str
    description: str
    enabled: bool
    configured: bool
    settings: Dict[str, Any]


SettingsT = TypeVar("SettingsT", covariant=True)


@runtime_checkable
class PrinterServiceClient(Protocol):
    """Client capabilities needed by Trinetra for printer integrations."""

    def get_history(self, limit: int = 1000) -> Optional[HistoryPayload]:
        """Return print history payload for statistics sync."""

    def queue_job(self, filenames: Sequence[str], reset: bool = False) -> bool:
        """Queue one or more print jobs."""


@runtime_checkable
class PrinterIntegration(Protocol[SettingsT]):
    """Protocol implemented by each printer integration plugin."""

    integration_id: str
    display_name: str
    description: str

    def get_settings(self, config: RuntimeIntegrationConfig) -> SettingsT:
        """Read integration settings from app config."""

    def is_enabled(self, config: RuntimeIntegrationConfig) -> bool:
        """Whether integration is enabled."""

    def is_configured(self, config: RuntimeIntegrationConfig) -> bool:
        """Whether integration has enough config to operate."""

    def create_client(self, config: RuntimeIntegrationConfig) -> Optional[PrinterServiceClient]:
        """Create provider client or return None if unavailable."""

    def queue_jobs(
        self, config: RuntimeIntegrationConfig, filenames: Sequence[str], reset: bool = False
    ) -> bool:
        """Queue print jobs via this integration."""

    def get_ui_state(self, config: RuntimeIntegrationConfig) -> IntegrationUIState:
        """Return UI-friendly integration state."""
