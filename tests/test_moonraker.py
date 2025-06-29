"""
Tests for moonraker.py module
Covers positive and negative test cases for Moonraker API integration
"""

import json
import unittest
from unittest.mock import Mock, patch, MagicMock
import requests
from typing import Dict, Any
import os

# Setup logging for tests
from trinetra.logger import get_logger

logger = get_logger(__name__)

from trinetra.moonraker import (
    MoonrakerAPI,
    get_moonraker_history,
    get_moonraker_stats,
    add_to_queue,
)


class MockMoonrakerServer:
    """Mock Moonraker server that returns realistic responses"""

    def __init__(self):
        self.mock_responses_dir = os.path.join(os.path.dirname(__file__), "mock_responses")
        self._load_responses()

    def _load_responses(self):
        """Load mock responses from JSON files"""
        self.responses = {}

        # Load server info response
        with open(os.path.join(self.mock_responses_dir, "server_info.json")) as f:
            self.responses["/server/info"] = json.load(f)

        # Load printer info response
        with open(os.path.join(self.mock_responses_dir, "printer_info.json")) as f:
            self.responses["/printer/info"] = json.load(f)

        # Load history list response
        with open(os.path.join(self.mock_responses_dir, "history_list.json")) as f:
            self.responses["/server/history/list"] = json.load(f)

        # Load queue job responses
        with open(os.path.join(self.mock_responses_dir, "queue_job_success.json")) as f:
            self.responses["/server/job_queue/job_success"] = json.load(f)

        with open(os.path.join(self.mock_responses_dir, "queue_job_error.json")) as f:
            self.responses["/server/job_queue/job_error"] = json.load(f)

    def get_response(self, endpoint: str, method: str = "GET", **kwargs) -> Dict[str, Any]:
        """Get mock response for given endpoint and method"""
        if endpoint == "/server/job_queue/job" and method == "POST":
            # Check if this is a test for error case
            json_data = kwargs.get("json", {})
            filenames = json_data.get("filenames", [])

            # Return error for nonexistent files, success for others
            if any("nonexistent" in fname for fname in filenames):
                return self.responses["/server/job_queue/job_error"]
            else:
                return self.responses["/server/job_queue/job_success"]

        # Return stored response for other endpoints
        return self.responses.get(endpoint, {"result": {}})


class TestMoonrakerAPI(unittest.TestCase):
    """Test cases for MoonrakerAPI class"""

    def setUp(self):
        """Set up test fixtures"""
        self.base_url = "http://localhost:7125"
        self.api = MoonrakerAPI(self.base_url)
        self.mock_server = MockMoonrakerServer()

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
        """Test successful API request using mock server"""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_server.get_response("/server/history/list")
        mock_response.raise_for_status.return_value = None

        with patch.object(self.api.session, "request", return_value=mock_response):
            result = self.api._make_request("/server/history/list")
            self.assertEqual(result, self.mock_server.get_response("/server/history/list"))

    def test_make_request_with_params(self):
        """Test API request with query parameters"""
        mock_response = Mock()
        mock_response.json.return_value = self.mock_server.get_response("/server/history/list")
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
        """Test successful print history retrieval using mock server"""
        mock_response = self.mock_server.get_response("/server/history/list")

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.get_print_history(limit=10)
            self.assertEqual(len(result), 3)  # 3 jobs in mock response
            self.assertEqual(result[0]["filename"], "test1.gcode")
            self.assertEqual(result[0]["status"], "completed")

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
        """Test successful print statistics calculation using mock server"""
        mock_history = self.mock_server.get_response("/server/history/list")["result"]["jobs"]

        with patch.object(self.api, "get_print_history", return_value=mock_history):
            result = self.api.get_print_stats_for_file("test.gcode")

            self.assertIsNotNone(result)
            self.assertEqual(result["filename"], "test.gcode")
            self.assertEqual(result["total_prints"], 1)  # Only one entry for test.gcode
            self.assertEqual(result["successful_prints"], 1)
            self.assertEqual(result["canceled_prints"], 0)
            self.assertEqual(result["most_recent_status"], "completed")

    def test_get_print_stats_for_file_not_found(self):
        """Test print statistics for non-existent file"""
        mock_history = self.mock_server.get_response("/server/history/list")["result"]["jobs"]

        with patch.object(self.api, "get_print_history", return_value=mock_history):
            result = self.api.get_print_stats_for_file("nonexistent.gcode")
            self.assertIsNone(result)

    def test_get_print_stats_for_file_no_history(self):
        """Test print statistics with no history"""
        with patch.object(self.api, "get_print_history", return_value=None):
            result = self.api.get_print_stats_for_file("test.gcode")
            self.assertIsNone(result)

    def test_get_server_info_success(self):
        """Test successful server info retrieval using mock server"""
        mock_response = self.mock_server.get_response("/server/info")

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.get_server_info()
            self.assertEqual(result, mock_response)
            self.assertEqual(result["result"]["klippy_state"], "ready")

    def test_get_printer_info_success(self):
        """Test successful printer info retrieval using mock server"""
        mock_response = self.mock_server.get_response("/printer/info")

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.get_printer_info()
            self.assertEqual(result, mock_response)
            self.assertEqual(result["result"]["state"], "ready")

    def test_get_history_success(self):
        """Test successful history retrieval using mock server"""
        mock_response = self.mock_server.get_response("/server/history/list")

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.get_history(limit=100)
            self.assertEqual(result, mock_response["result"])
            self.assertEqual(result["count"], 5)

    def test_queue_job_success(self):
        """Test successful job queueing using mock server"""
        mock_response = self.mock_server.get_response(
            "/server/job_queue/job",
            method="POST",
            json={"filenames": ["test.gcode"], "reset": False},
        )

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.queue_job(["test.gcode"], reset=False)
            self.assertTrue(result)

    def test_queue_job_failure(self):
        """Test failed job queueing using mock server"""
        mock_response = self.mock_server.get_response(
            "/server/job_queue/job",
            method="POST",
            json={"filenames": ["nonexistent.gcode"], "reset": False},
        )

        with patch.object(self.api, "_make_request", return_value=mock_response):
            result = self.api.queue_job(["nonexistent.gcode"], reset=False)
            self.assertFalse(result)

    def test_queue_job_with_reset(self):
        """Test job queueing with reset flag using mock server"""
        mock_response = self.mock_server.get_response(
            "/server/job_queue/job",
            method="POST",
            json={"filenames": ["test.gcode"], "reset": True},
        )

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

    def setUp(self):
        """Set up test fixtures"""
        self.mock_server = MockMoonrakerServer()

    def test_get_moonraker_history_success(self):
        """Test successful history retrieval via convenience function"""
        mock_response = self.mock_server.get_response("/server/history/list")

        with patch("trinetra.moonraker.MoonrakerAPI") as mock_api_class:
            mock_api = Mock()
            mock_api.get_history.return_value = mock_response["result"]
            mock_api_class.return_value = mock_api

            result = get_moonraker_history("http://localhost:7125")
            self.assertEqual(result, mock_response["result"])

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

    def test_mock_server_response_formats(self):
        """Test that mock server returns responses in correct Klipper format"""
        # Test server info response
        server_info = self.mock_server.get_response("/server/info")
        self.assertIn("result", server_info)
        self.assertIn("klippy_state", server_info["result"])
        self.assertIn("components", server_info["result"])
        self.assertIn("api_version", server_info["result"])

        # Test printer info response
        printer_info = self.mock_server.get_response("/printer/info")
        self.assertIn("result", printer_info)
        self.assertIn("state", printer_info["result"])
        self.assertIn("hostname", printer_info["result"])

        # Test history list response
        history_list = self.mock_server.get_response("/server/history/list")
        self.assertIn("result", history_list)
        self.assertIn("count", history_list["result"])
        self.assertIn("jobs", history_list["result"])
        self.assertIsInstance(history_list["result"]["jobs"], list)

        # Test successful queue job response
        queue_success = self.mock_server.get_response(
            "/server/job_queue/job",
            method="POST",
            json={"filenames": ["test.gcode"], "reset": False},
        )
        self.assertIn("result", queue_success)
        self.assertIn("queued_jobs", queue_success["result"])
        self.assertIn("queue_state", queue_success["result"])

        # Test failed queue job response
        queue_error = self.mock_server.get_response(
            "/server/job_queue/job",
            method="POST",
            json={"filenames": ["nonexistent.gcode"], "reset": False},
        )
        self.assertIn("error", queue_error)
        self.assertIn("code", queue_error["error"])
        self.assertIn("message", queue_error["error"])


if __name__ == "__main__":
    unittest.main()
