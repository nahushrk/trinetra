"""Bambu cloud integration implementation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from trinetra.integrations.bambu.api import BambuCloudAPI
from trinetra.integrations.bambu.types import (
    BambuConfigBlock,
    BambuIntegrationSettings,
)
from trinetra.integrations.protocol import (
    IntegrationUIState,
    PrinterIntegration,
    PrinterServiceClient,
    RuntimeIntegrationConfig,
)


class BambuIntegration(PrinterIntegration[BambuIntegrationSettings]):
    integration_id = "bambu"
    display_name = "Bambu Lab"
    description = "Bambu cloud telemetry integration (history sync)."

    def _integration_block(self, config: RuntimeIntegrationConfig) -> BambuConfigBlock:
        integrations = config.get("integrations")
        if not isinstance(integrations, dict):
            return {}
        bambu = integrations.get("bambu")
        if not isinstance(bambu, dict):
            return {}
        return bambu

    def get_settings(self, config: RuntimeIntegrationConfig) -> BambuIntegrationSettings:
        block = self._integration_block(config)
        mode = str(block.get("mode") or "cloud").strip().lower() or "cloud"
        cloud = block.get("cloud") if isinstance(block.get("cloud"), dict) else {}

        return BambuIntegrationSettings(
            enabled=bool(block.get("enabled", False)),
            mode=mode,
            access_token=str(cloud.get("access_token") or "").strip(),
            refresh_token=str(cloud.get("refresh_token") or "").strip(),
            region=str(cloud.get("region") or "global").strip().lower() or "global",
        )

    def is_enabled(self, config: RuntimeIntegrationConfig) -> bool:
        return self.get_settings(config).enabled

    def is_configured(self, config: RuntimeIntegrationConfig) -> bool:
        return self.get_settings(config).configured

    def create_client(self, config: RuntimeIntegrationConfig) -> Optional[PrinterServiceClient]:
        settings = self.get_settings(config)
        if not settings.enabled or not settings.configured:
            return None
        if settings.mode != "cloud":
            return None
        return BambuCloudAPI(
            access_token=settings.access_token,
            refresh_token=settings.refresh_token,
            region=settings.region,
        )

    def queue_jobs(
        self, config: RuntimeIntegrationConfig, filenames: Sequence[str], reset: bool = False
    ) -> bool:
        # Cloud mode is intentionally telemetry-only for v1.
        return False

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

    def fetch_history_events(
        self,
        config: RuntimeIntegrationConfig,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        settings = self.get_settings(config)
        if not settings.enabled or not settings.configured or settings.mode != "cloud":
            return []

        client = self.create_client(config)
        if not isinstance(client, BambuCloudAPI):
            return []

        tasks = client.get_tasks(limit=limit)
        events: List[Dict[str, Any]] = []
        for task in tasks:
            event_uid = str(
                task.get("id")
                or task.get("task_id")
                or task.get("taskId")
                or task.get("job_id")
                or ""
            ).strip()
            if not event_uid:
                # Dedup is id-only, so events without a stable id cannot be persisted safely.
                continue

            file_name = _extract_filename(task)
            start_at = _parse_dt(_first_of(task, "startTime", "start_time", "start"))
            end_at = _parse_dt(_first_of(task, "endTime", "end_time", "end"))
            event_at = end_at or start_at
            status = _normalize_status(task)

            events.append(
                {
                    "event_uid": event_uid,
                    "printer_uid": str(
                        task.get("device_id")
                        or task.get("deviceId")
                        or task.get("dev_id")
                        or ""
                    ).strip(),
                    "job_uid": str(
                        task.get("job_id") or task.get("taskId") or task.get("id") or ""
                    ).strip(),
                    "file_name": file_name,
                    "file_path": str(
                        task.get("file_path") or task.get("filePath") or task.get("path") or ""
                    ).strip(),
                    "status": status,
                    "started_at": start_at,
                    "ended_at": end_at,
                    "event_at": event_at,
                    "duration_seconds": _to_float(
                        _first_of(task, "costTime", "cost_time", "printDuration", "print_duration")
                    ),
                    "filament_used_mm": _to_float(
                        _first_of(task, "length", "filamentUsed", "filament_used")
                    ),
                    "raw_payload": task,
                }
            )
        return events


def _first_of(task: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in task and task.get(key) is not None:
            return task.get(key)
    return None


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if abs(numeric) > 1e11:
            numeric /= 1000.0
        try:
            return datetime.utcfromtimestamp(numeric)
        except (TypeError, ValueError, OSError):
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            numeric = float(raw)
            if abs(numeric) > 1e11:
                numeric /= 1000.0
            return datetime.utcfromtimestamp(numeric)
        except (TypeError, ValueError, OSError):
            pass
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo:
                return dt.astimezone(tz=None).replace(tzinfo=None)
            return dt
        except ValueError:
            return None
    return None


def _normalize_status(task: Dict[str, Any]) -> str:
    raw_status = task.get("status")
    if raw_status is None:
        raw_status = task.get("state")

    if isinstance(raw_status, (int, float)):
        status_code = int(raw_status)
        if status_code == 2:
            return "completed"
        if status_code in {3, 4}:
            return "cancelled"
        return str(status_code)

    status = str(raw_status or "unknown").strip().lower()
    if status.isdigit():
        status_code = int(status)
        if status_code == 2:
            return "completed"
        if status_code in {3, 4}:
            return "cancelled"
        return status

    if status in {"completed", "finished", "success", "succeeded"}:
        return "completed"
    if status in {"cancelled", "canceled", "failed", "aborted"}:
        return "cancelled"
    return status


def _extract_filename(task: Dict[str, Any]) -> str:
    keys = (
        "filename",
        "file_name",
        "fileName",
        "gcode_name",
        "gcodeName",
        "project_name",
        "projectName",
        "title",
        "design_title",
        "designTitle",
    )
    for key in keys:
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
