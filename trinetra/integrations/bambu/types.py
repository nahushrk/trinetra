"""Bambu integration-specific settings and config typing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypedDict


class BambuCloudConfigBlock(TypedDict, total=False):
    access_token: str
    refresh_token: str
    region: str


class BambuConfigBlock(TypedDict, total=False):
    enabled: bool
    mode: str
    cloud: BambuCloudConfigBlock


@dataclass(frozen=True)
class BambuIntegrationSettings:
    enabled: bool = False
    mode: str = "cloud"
    access_token: str = ""
    refresh_token: str = ""
    region: str = "global"

    @property
    def configured(self) -> bool:
        if self.mode == "cloud":
            return bool(self.access_token)
        return False

    def to_ui_settings(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "region": self.region,
        }
