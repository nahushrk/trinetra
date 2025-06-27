"""
Tests for moonraker.py module
Covers positive and negative test cases for Moonraker API integration
"""

import json
import unittest
from unittest.mock import Mock, patch, MagicMock
import requests
from typing import Dict, Any

from trinetra.moonraker import (
    MoonrakerAPI,
    get_moonraker_history,
    get_moonraker_stats,
    add_to_queue,
)


class TestMoonrakerAPI(unittest.TestCase):
    """Test cases for MoonrakerAPI class"""

    def setUp(self):
        """Set up test fixtures"""
        self.base_url = "http://localhost:7125"
        self.api = MoonrakerAPI(self.base_url)

    def test_init_with_valid_url(self):
        """Test successful API initialization with valid URL"""
        api = MoonrakerAPI("http://localhost:7125")
        self.assertEqual(api.base_url, "http://localhost:7125")
        self.assertIsNotNone(api.session)
        self.assertEqual(api.session.timeout, 10)

    def test_init_with_trailing_slash(self):
        """Test API initialization removes trailing slash"""
        api = MoonrakerAPI("http://localhost:7125/")
        self.assertEqual(api.base_url, "http://localhost:7125")

    def test_make_request_success(self):
        """Test successful API request"""
        mock_response = Mock()
        mock_response.json.return_value = {"result": {"jobs": []}}
        mock_response.raise_for_status.return_value = None

        with patch.object(self.api.session, "request", return_value=mock_response):
            result = self.api._make_request("/server/history/list")
            self.assertEqual(result, {"result": {"jobs": []}})

    def test_make_request_with_params(self):
        """Test API request with query parameters"""
        mock_response = Mock()
        mock_response.json.return_value = {"result": {"jobs": []}}
        mock_response.raise_for_status.return_value = None

        with patch.object(self.api.session, "request", return_value=mock_response) as mock_request:
            result = self.api._make_request("/server/history/list", params={"limit": 10})
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            self.assertEqual(call_args[1]["params"], {"limit": 10})

    def test_make_request_network_error_returns_none(self):
        """Test that network errors return None (no curl fallback)"""
        # Mock requests to fail with network error
        with patch.object(
            self.api.session, "request", side_effect=requests.exceptions.ConnectionError
        ):
            result = self.api._make_request("/server/history/list")
            self.assertIsNone(result)

    def test_make_request_json_error_returns_none(self):
        """Test that JSON parsing errors return None"""
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.side_effect = ValueError("Invalid JSON")

        with patch.object(self.api.session, "request", return_value=mock_response):
            result = self.api._make_request("/server/history/list")
            self.assertIsNone(result)

    def test_get_print_history_success(self):
        """Test successful print history retrieval"""
        mock_response = {
            "result": {
                "jobs": [
                    {"filename": "test1.gcode", "status": "completed"},
                    {"filename": "test2.gcode", "status": "cancelled"},
                ]
            }
        }

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.get_print_history(limit=10)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["filename"], "test1.gcode")

    def test_get_print_history_no_result(self):
        """Test print history with no result"""
        with patch.object(self.api, "_make_request", return_value=None):
            result = self.api.get_print_history()
            self.assertIsNone(result)

    def test_get_print_history_missing_jobs(self):
        """Test print history with missing jobs field"""
        mock_response = {"result": {}}

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.get_print_history()
            self.assertEqual(result, [])

    def test_get_print_stats_for_file_success(self):
        """Test successful print statistics calculation"""
        mock_history = [
            {
                "filename": "test.gcode",
                "status": "completed",
                "total_duration": 3600,
                "start_time": 1000,
            },
            {
                "filename": "test.gcode",
                "status": "completed",
                "total_duration": 7200,
                "start_time": 2000,
            },
            {"filename": "test.gcode", "status": "cancelled", "start_time": 3000},
        ]

        with patch.object(self.api, "get_print_history", return_value=mock_history):
            result = self.api.get_print_stats_for_file("test.gcode")

            self.assertIsNotNone(result)
            self.assertEqual(result["filename"], "test.gcode")
            self.assertEqual(result["total_prints"], 3)
            self.assertEqual(result["successful_prints"], 2)
            self.assertEqual(result["canceled_prints"], 1)
            self.assertEqual(result["avg_duration"], 5400)  # (3600 + 7200) / 2
            self.assertEqual(result["most_recent_status"], "cancelled")

    def test_get_print_stats_for_file_not_found(self):
        """Test print statistics for non-existent file"""
        mock_history = [{"filename": "other.gcode", "status": "completed"}]

        with patch.object(self.api, "get_print_history", return_value=mock_history):
            result = self.api.get_print_stats_for_file("test.gcode")
            self.assertIsNone(result)

    def test_get_print_stats_for_file_no_history(self):
        """Test print statistics with no history"""
        with patch.object(self.api, "get_print_history", return_value=None):
            result = self.api.get_print_stats_for_file("test.gcode")
            self.assertIsNone(result)

    def test_get_server_info_success(self):
        """Test successful server info retrieval"""
        mock_response = {"result": {"server": "info"}}

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.get_server_info()
            self.assertEqual(result, {"result": {"server": "info"}})

    def test_get_printer_info_success(self):
        """Test successful printer info retrieval"""
        mock_response = {"result": {"printer": "info"}}

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.get_printer_info()
            self.assertEqual(result, {"result": {"printer": "info"}})

    def test_get_history_success(self):
        """Test successful history retrieval"""
        mock_response = {"result": {"jobs": [], "count": 0}}

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.get_history(limit=100)
            self.assertEqual(result, {"jobs": [], "count": 0})

    def test_queue_job_success(self):
        """Test successful job queueing"""
        mock_response = {"result": {"queued_jobs": ["test.gcode"]}}

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.queue_job(["test.gcode"], reset=False)
            self.assertTrue(result)

    def test_queue_job_failure(self):
        """Test failed job queueing"""
        with patch.object(self.api, "_make_request", return_value=None):
            result = self.api.queue_job(["test.gcode"], reset=False)
            self.assertFalse(result)

    def test_queue_job_with_reset(self):
        """Test job queueing with reset flag"""
        mock_response = {"result": {"queued_jobs": ["test.gcode"]}}

        with patch.object(self.api, "_make_request", return_value=mock_response) as mock_request:
            result = self.api.queue_job(["test.gcode"], reset=True)
            self.assertTrue(result)
            mock_request.assert_called_once()
            call_args = mock_request.call_args
            self.assertEqual(call_args[1]["json"], {"filenames": ["test.gcode"], "reset": True})

    def test_requests_session_configuration(self):
        """Test requests session configuration"""
        api = MoonrakerAPI("http://localhost:7125")

        # Check session timeout
        self.assertEqual(api.session.timeout, 10)

        # Check session headers and other configurations
        self.assertIsInstance(api.session, requests.Session)


class TestMoonrakerFunctions(unittest.TestCase):
    """Test cases for convenience functions"""

    def test_get_moonraker_history_success(self):
        """Test successful history retrieval via convenience function"""
        mock_response = {"result": {"jobs": []}}

        with patch("trinetra.moonraker.MoonrakerAPI") as mock_api_class:
            mock_api = Mock()
            mock_api.get_history.return_value = mock_response
            mock_api_class.return_value = mock_api

            result = get_moonraker_history("http://localhost:7125")
            self.assertEqual(result, {"result": {"jobs": []}})

    def test_get_moonraker_stats_success(self):
        """Test successful stats retrieval via convenience function"""
        mock_stats = {"filename": "test.gcode", "total_prints": 1}

        with patch("trinetra.moonraker.MoonrakerAPI") as mock_api_class:
            mock_api = Mock()
            mock_api.get_print_stats_for_file.return_value = mock_stats
            mock_api_class.return_value = mock_api

            result = get_moonraker_stats("test.gcode", "http://localhost:7125")
            self.assertEqual(result, mock_stats)

    def test_get_moonraker_stats_exception(self):
        """Test stats retrieval with exception handling"""
        with patch("trinetra.moonraker.MoonrakerAPI", side_effect=Exception("API Error")):
            result = get_moonraker_stats("test.gcode", "http://localhost:7125")
            self.assertIsNone(result)

    def test_add_to_queue_success(self):
        """Test successful queue addition via convenience function"""
        with patch("trinetra.moonraker.MoonrakerAPI") as mock_api_class:
            mock_api = Mock()
            mock_api.queue_job.return_value = True
            mock_api_class.return_value = mock_api

            result = add_to_queue(
                ["test.gcode"], reset=False, moonraker_url="http://localhost:7125"
            )
            self.assertTrue(result)

    def test_add_to_queue_exception(self):
        """Test queue addition with exception handling"""
        with patch("trinetra.moonraker.MoonrakerAPI", side_effect=Exception("API Error")):
            result = add_to_queue(
                ["test.gcode"], reset=False, moonraker_url="http://localhost:7125"
            )
            self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
