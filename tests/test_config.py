"""
Tests for ConfigManager functionality
Covers config loading, merging, and override functionality
"""

import os
import tempfile
import yaml
import pytest
from unittest.mock import patch, mock_open

from trinetra.config import ConfigManager, ConfigOptions


class TestConfigManager:
    """Test cases for ConfigManager class"""

    def setup_method(self):
        """Set up test fixtures for each test method"""
        self.temp_dir = tempfile.mkdtemp()
        self.base_config_path = os.path.join(self.temp_dir, "base_config.yaml")
        self.override_config_path = os.path.join(self.temp_dir, "override_config.yaml")

    def teardown_method(self):
        """Clean up temporary files"""
        if os.path.exists(self.temp_dir):
            import shutil

            shutil.rmtree(self.temp_dir)

    def test_config_manager_init_with_files(self):
        """Test ConfigManager initialization with file paths"""
        # Create base config file
        base_config = {
            "base_path": "/test/stl",
            "gcode_path": "/test/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://localhost:7125",
            "mode": "DEV",
        }
        with open(self.base_config_path, "w") as f:
            yaml.dump(base_config, f)

        # Create override config file
        override_config = {"log_level": "DEBUG", "search_result_limit": 50}
        with open(self.override_config_path, "w") as f:
            yaml.dump(override_config, f)

        # Initialize ConfigManager
        config_manager = ConfigManager(self.base_config_path, self.override_config_path)

        # Test base config
        base_config_result = config_manager.get_base_config()
        assert base_config_result == base_config

        # Test override config
        override_config_result = config_manager.get_override_config()
        assert override_config_result == override_config

        # Test merged config
        merged_config = config_manager.get_config()
        assert merged_config.base_path == "/test/stl"
        assert merged_config.gcode_path == "/test/gcode"
        assert merged_config.log_level == "DEBUG"  # Overridden
        assert merged_config.search_result_limit == 50  # Overridden
        assert merged_config.moonraker_url == "http://localhost:7125"
        assert merged_config.mode == "DEV"

    def test_config_manager_from_dict(self):
        """Test ConfigManager.from_dict method for testing"""
        base_config = {
            "base_path": "/test/stl",
            "gcode_path": "/test/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://localhost:7125",
            "mode": "DEV",
        }

        override_config = {"log_level": "DEBUG", "search_result_limit": 50}

        # Test with override
        config_manager = ConfigManager.from_dict(base_config, override_config)

        assert config_manager.get_base_config() == base_config
        assert config_manager.get_override_config() == override_config

        merged_config = config_manager.get_config()
        assert merged_config.log_level == "DEBUG"
        assert merged_config.search_result_limit == 50

        # Test with empty override
        config_manager_empty = ConfigManager.from_dict(base_config, {})
        assert config_manager_empty.get_override_config() == {}

        merged_config_empty = config_manager_empty.get_config()
        assert merged_config_empty.log_level == "INFO"  # Not overridden
        assert merged_config_empty.search_result_limit == 25  # Not overridden

    def test_config_manager_no_override(self):
        """Test ConfigManager with no override file"""
        base_config = {
            "base_path": "/test/stl",
            "gcode_path": "/test/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://localhost:7125",
            "mode": "DEV",
        }
        with open(self.base_config_path, "w") as f:
            yaml.dump(base_config, f)

        # Initialize ConfigManager without override
        config_manager = ConfigManager(self.base_config_path, None)

        assert config_manager.get_base_config() == base_config
        assert config_manager.get_override_config() == {}

        merged_config = config_manager.get_config()
        assert merged_config.base_path == "/test/stl"
        assert merged_config.log_level == "INFO"  # Not overridden

    def test_config_manager_update_override(self):
        """Test updating override configuration"""
        base_config = {
            "base_path": "/test/stl",
            "gcode_path": "/test/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://localhost:7125",
            "mode": "DEV",
        }
        with open(self.base_config_path, "w") as f:
            yaml.dump(base_config, f)

        config_manager = ConfigManager(self.base_config_path, self.override_config_path)

        # Update override
        new_override = {"log_level": "DEBUG", "search_result_limit": 100}

        with patch("builtins.open", mock_open()) as mock_file:
            config_manager.update_override(new_override)

            # Check that file was written
            mock_file.assert_called_once_with(self.override_config_path, "w")

        # Check that override was updated
        assert config_manager.get_override_config() == new_override

        # Check that merged config reflects changes
        merged_config = config_manager.get_config()
        assert merged_config.log_level == "DEBUG"
        assert merged_config.search_result_limit == 100

    def test_config_manager_reload(self):
        """Test reloading configuration"""
        base_config = {
            "base_path": "/test/stl",
            "gcode_path": "/test/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://localhost:7125",
            "mode": "DEV",
        }
        with open(self.base_config_path, "w") as f:
            yaml.dump(base_config, f)

        config_manager = ConfigManager(self.base_config_path, self.override_config_path)

        # Update base config file
        updated_base_config = {
            "base_path": "/updated/stl",
            "gcode_path": "/updated/gcode",
            "log_level": "DEBUG",
            "search_result_limit": 50,
            "moonraker_url": "http://updated:7125",
            "mode": "PROD",
        }
        with open(self.base_config_path, "w") as f:
            yaml.dump(updated_base_config, f)

        # Reload config
        config_manager.reload()

        # Check that base config was reloaded
        assert config_manager.get_base_config() == updated_base_config

        # Check that merged config reflects changes
        merged_config = config_manager.get_config()
        assert merged_config.base_path == "/updated/stl"
        assert merged_config.log_level == "DEBUG"

    def test_config_options_from_dict(self):
        """Test ConfigOptions.from_dict method"""
        config_data = {
            "base_path": "/test/stl",
            "gcode_path": "/test/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://localhost:7125",
            "mode": "DEV",
        }

        config_options = ConfigOptions.from_dict(config_data)

        assert config_options.base_path == "/test/stl"
        assert config_options.gcode_path == "/test/gcode"
        assert config_options.log_level == "INFO"
        assert config_options.search_result_limit == 25
        assert config_options.moonraker_url == "http://localhost:7125"
        assert config_options.mode == "DEV"

    def test_config_options_from_dict_missing_optional(self):
        """Test ConfigOptions.from_dict with missing optional field"""
        config_data = {
            "base_path": "/test/stl",
            "gcode_path": "/test/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "mode": "DEV",
            # moonraker_url is missing (optional)
        }

        config_options = ConfigOptions.from_dict(config_data)

        assert config_options.moonraker_url == ""  # Default empty string

    def test_config_options_from_dict_missing_required(self):
        """Test ConfigOptions.from_dict with missing required field"""
        config_data = {
            "base_path": "/test/stl",
            "gcode_path": "/test/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://localhost:7125",
            # mode is missing (required)
        }

        with pytest.raises(ValueError, match="Missing config fields"):
            ConfigOptions.from_dict(config_data)

    def test_config_options_to_dict(self):
        """Test ConfigOptions.to_dict method"""
        config_options = ConfigOptions(
            base_path="/test/stl",
            gcode_path="/test/gcode",
            log_level="INFO",
            search_result_limit=25,
            moonraker_url="http://localhost:7125",
            mode="DEV",
        )

        config_dict = config_options.to_dict()

        assert config_dict["base_path"] == "/test/stl"
        assert config_dict["gcode_path"] == "/test/gcode"
        assert config_dict["log_level"] == "INFO"
        assert config_dict["search_result_limit"] == 25
        assert config_dict["moonraker_url"] == "http://localhost:7125"
        assert config_dict["mode"] == "DEV"

    def test_config_manager_file_not_found(self):
        """Test ConfigManager with non-existent base config file"""
        with pytest.raises(FileNotFoundError):
            ConfigManager("nonexistent.yaml")

    def test_config_manager_invalid_yaml(self):
        """Test ConfigManager with invalid YAML file"""
        with open(self.base_config_path, "w") as f:
            f.write("invalid: yaml: content: [")

        # Should handle invalid YAML gracefully and not raise an exception
        # The ConfigManager should handle this by loading an empty dict
        # and the app should handle missing required fields gracefully
        try:
            config_manager = ConfigManager(self.base_config_path, self.override_config_path)
            # If it doesn't raise an exception, the base config should be empty
            assert config_manager.get_base_config() == {}
        except ValueError:
            # It's also acceptable for it to raise ValueError for missing required fields
            # since the invalid YAML results in an empty config
            pass

    def test_config_manager_merge_behavior(self):
        """Test that override values properly override base values"""
        base_config = {
            "base_path": "/base/stl",
            "gcode_path": "/base/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://base:7125",
            "mode": "DEV",
        }

        override_config = {
            "log_level": "DEBUG",
            "search_result_limit": 50,
            "moonraker_url": "http://override:7125",
        }

        config_manager = ConfigManager.from_dict(base_config, override_config)
        merged_config = config_manager.get_config()

        # Overridden values
        assert merged_config.log_level == "DEBUG"
        assert merged_config.search_result_limit == 50
        assert merged_config.moonraker_url == "http://override:7125"

        # Non-overridden values
        assert merged_config.base_path == "/base/stl"
        assert merged_config.gcode_path == "/base/gcode"
        assert merged_config.mode == "DEV"

    def test_calculate_and_save_diff(self):
        """Test calculate_and_save_diff method"""
        base_config = {
            "base_path": "/base/stl",
            "gcode_path": "/base/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://base:7125",
            "mode": "DEV",
        }

        config_manager = ConfigManager.from_dict(base_config, {})

        # New config with some changes
        new_config = {
            "base_path": "/base/stl",  # Same as base
            "gcode_path": "/new/gcode",  # Different
            "log_level": "DEBUG",  # Different
            "search_result_limit": 25,  # Same as base
            "moonraker_url": "http://new:7125",  # Different
            "mode": "DEV",  # Same as base
        }

        # Calculate and save diff
        diff = config_manager.calculate_and_save_diff(new_config)

        # Verify diff contains only changed values
        expected_diff = {
            "gcode_path": "/new/gcode",
            "log_level": "DEBUG",
            "moonraker_url": "http://new:7125",
        }
        assert diff == expected_diff

        # Verify override config was updated
        assert config_manager.get_override_config() == expected_diff

        # Verify merged config reflects changes
        merged_config = config_manager.get_config()
        assert merged_config.base_path == "/base/stl"  # Unchanged
        assert merged_config.gcode_path == "/new/gcode"  # Changed
        assert merged_config.log_level == "DEBUG"  # Changed
        assert merged_config.search_result_limit == 25  # Unchanged
        assert merged_config.moonraker_url == "http://new:7125"  # Changed
        assert merged_config.mode == "DEV"  # Unchanged

    def test_calculate_and_save_diff_no_changes(self):
        """Test calculate_and_save_diff with no changes"""
        base_config = {
            "base_path": "/base/stl",
            "gcode_path": "/base/gcode",
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://base:7125",
            "mode": "DEV",
        }

        config_manager = ConfigManager.from_dict(base_config, {})

        # New config identical to base
        new_config = base_config.copy()

        # Calculate and save diff
        diff = config_manager.calculate_and_save_diff(new_config)

        # Verify diff is empty
        assert diff == {}

        # Verify override config is empty
        assert config_manager.get_override_config() == {}

        # Verify merged config is same as base
        merged_config = config_manager.get_config()
        assert merged_config.base_path == "/base/stl"
        assert merged_config.gcode_path == "/base/gcode"
        assert merged_config.log_level == "INFO"
        assert merged_config.search_result_limit == 25
        assert merged_config.moonraker_url == "http://base:7125"
        assert merged_config.mode == "DEV"
