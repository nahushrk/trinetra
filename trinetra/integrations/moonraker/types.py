"""Moonraker-specific settings and config typing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict


class MoonrakerConfigBlock(TypedDict, total=False):
    enabled: bool
    base_url: str


@dataclass(frozen=True)
class MoonrakerIntegrationSettings:
    enabled: bool = False
    base_url: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def to_ui_settings(self) -> dict[str, str]:
        return {"base_url": self.base_url}
