from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional
import yaml
import os
import logging

logger = logging.getLogger(__name__)

# Constant for override file name
OVERRIDE_CONFIG_FILE = "config_override.yaml"


@dataclass
class ConfigOptions:
    base_path: str
    gcode_path: str
    moonraker_url: Optional[str]
    log_level: str
    mode: str
    search_result_limit: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConfigOptions":
        field_names = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in field_names}

        # Handle optional fields
        if "moonraker_url" not in filtered:
            filtered["moonraker_url"] = ""

        missing = {f for f in field_names if f not in filtered and f != "moonraker_url"}
        if missing:
            raise ValueError(f"Missing config fields: {missing}")
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConfigManager:
    def __init__(self, base_config_path: str, override_config_path: Optional[str] = None):
        self.base_config_path = base_config_path
        self.override_config_path = override_config_path or OVERRIDE_CONFIG_FILE

        # Load base config, provide defaults if file doesn't exist
        self.base_config = self._load_yaml(self.base_config_path)
        if not self.base_config and not os.path.exists(self.base_config_path):
            raise FileNotFoundError(f"Base config file '{self.base_config_path}' not found")

        self.override_config = (
            self._load_yaml(self.override_config_path)
            if self.override_config_path and os.path.exists(self.override_config_path)
            else {}
        )
        self.config = self._merge_configs(self.base_config, self.override_config)

    @classmethod
    def from_dict(
        cls, base_config: Dict[str, Any], override_config: Optional[Dict[str, Any]] = None
    ):
        """Initialize ConfigManager with config dictionaries instead of file paths.
        Useful for testing or when config is provided programmatically."""
        instance = cls.__new__(cls)
        instance.base_config_path = None
        instance.override_config_path = None
        instance.base_config = base_config
        instance.override_config = override_config or {}
        instance.config = instance._merge_configs(base_config, instance.override_config)
        return instance

    def _load_yaml(self, path: str) -> Dict[str, Any]:
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error loading config file {path}: {e}")
            return {}

    def _merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> ConfigOptions:
        merged = {**base, **override}
        return ConfigOptions.from_dict(merged)

    def get_config(self) -> ConfigOptions:
        return self.config

    def get_base_config(self) -> Dict[str, Any]:
        return self.base_config

    def get_override_config(self) -> Dict[str, Any]:
        return self.override_config

    def update_override(self, new_override: Dict[str, Any]):
        """Update override config with new values and save to file."""
        changed = {k: v for k, v in new_override.items() if self.base_config.get(k) != v}
        self.override_config = changed
        self._save_override_config()
        self.config = self._merge_configs(self.base_config, self.override_config)

    def _save_override_config(self):
        """Save the current override config to the override file."""
        if self.override_config_path:
            try:
                with open(self.override_config_path, "w") as f:
                    yaml.safe_dump(self.override_config, f, default_flow_style=False, indent=2)
                logger.info(f"Override config saved to {self.override_config_path}")
            except Exception as e:
                logger.error(f"Error saving override config to {self.override_config_path}: {e}")

    def calculate_and_save_diff(self, new_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate the difference between base config and new config,
        save the diff as overrides, and return the diff.

        Args:
            new_config: The new configuration values

        Returns:
            Dict containing only the values that differ from base config
        """
        # Calculate diff: only values that differ from base config
        diff = {}
        for key, new_value in new_config.items():
            base_value = self.base_config.get(key)
            if base_value != new_value:
                diff[key] = new_value

        # Update override config with the diff
        self.override_config = diff
        self._save_override_config()

        # Update merged config
        self.config = self._merge_configs(self.base_config, self.override_config)

        logger.info(f"Config diff calculated and saved: {list(diff.keys())}")
        return diff

    def reload(self):
        self.base_config = self._load_yaml(self.base_config_path)
        self.override_config = (
            self._load_yaml(self.override_config_path)
            if self.override_config_path and os.path.exists(self.override_config_path)
            else {}
        )
        self.config = self._merge_configs(self.base_config, self.override_config)
