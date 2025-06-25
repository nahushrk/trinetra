"""
Moonraker API integration module for Trinetra
Handles communication with Moonraker API to get print history and other information
"""

import json
import logging
import subprocess
import requests
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

logger = logging.getLogger(__name__)


class MoonrakerAPI:
    """Client for interacting with Moonraker API"""

    def __init__(self, base_url: str = "http://klipper.local:7125"):
        """
        Initialize Moonraker API client

        Args:
            base_url: Base URL for Moonraker API (default: http://klipper.local:7125)
        """
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.timeout = 10  # 10 second timeout

    def _make_request_curl(
        self, endpoint: str, params: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Make a request to the Moonraker API using curl as fallback

        Args:
            endpoint: API endpoint (e.g., "/server/history/list")
            params: Query parameters

        Returns:
            Response data as dictionary or None if request failed
        """
        url = urljoin(self.base_url, endpoint)

        # Build curl command with proper query parameter handling
        cmd = ["curl", "-s"]
        if params:
            # Build query string
            query_parts = []
            for key, value in params.items():
                query_parts.append(f"{key}={value}")
            url = f"{url}?{'&'.join(query_parts)}"

        cmd.append(url)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                logger.error(f"Curl request failed for {url}: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            logger.error(f"Curl request timeout for {url}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response from curl {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error with curl request to {url}: {e}")
            return None

    def _make_request(
        self, endpoint: str, method: str = "GET", **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        Make a request to the Moonraker API

        Args:
            endpoint: API endpoint (e.g., "/server/history/list")
            method: HTTP method (GET, POST, etc.)
            **kwargs: Additional arguments for requests

        Returns:
            Response data as dictionary or None if request failed
        """
        url = urljoin(self.base_url, endpoint)

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Moonraker API request failed for {url}: {e}")
            # Fallback to curl for network issues
            logger.info(f"Attempting curl fallback for {url}")
            return self._make_request_curl(endpoint, kwargs.get("params"))
        except ValueError as e:
            logger.error(f"Failed to parse JSON response from {url}: {e}")
            return None

    def get_print_history(self, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        """
        Get print history from Moonraker

        Args:
            limit: Maximum number of history entries to return

        Returns:
            List of print history entries or None if request failed
        """
        params = {"limit": limit}
        response = self._make_request("/server/history/list", params=params)

        if response and "result" in response:
            return response["result"].get("jobs", [])
        return None

    def get_print_stats_for_file(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        Get print statistics for a specific G-code file

        Args:
            filename: Name of the G-code file

        Returns:
            Dictionary with print statistics or None if not found
        """
        history = self.get_print_history(limit=1000)  # Get more history to find the file
        if not history:
            return None

        # Find all entries for this file
        file_entries = []
        for entry in history:
            if entry.get("filename") == filename:
                file_entries.append(entry)

        if not file_entries:
            return None

        # Calculate statistics
        total_prints = len(file_entries)
        successful_prints = sum(1 for entry in file_entries if entry.get("status") == "completed")
        canceled_prints = sum(1 for entry in file_entries if entry.get("status") == "cancelled")

        # Calculate average duration
        durations = []
        for entry in file_entries:
            if entry.get("status") == "completed" and entry.get("total_duration"):
                durations.append(entry["total_duration"])

        avg_duration = sum(durations) / len(durations) if durations else 0

        # Find most recent print
        most_recent = max(file_entries, key=lambda x: x.get("start_time", 0))

        return {
            "filename": filename,
            "total_prints": total_prints,
            "successful_prints": successful_prints,
            "canceled_prints": canceled_prints,
            "avg_duration": avg_duration,
            "most_recent_print": most_recent.get("start_time"),
            "most_recent_status": most_recent.get("status"),
            "print_history": file_entries,
        }

    def get_server_info(self) -> Optional[Dict[str, Any]]:
        """
        Get basic server information

        Returns:
            Server information dictionary or None if request failed
        """
        return self._make_request("/server/info")

    def get_printer_info(self) -> Optional[Dict[str, Any]]:
        """
        Get current printer information

        Returns:
            Printer information dictionary or None if request failed
        """
        return self._make_request("/printer/info")

    def get_history(self, limit: int = 1000) -> Optional[Dict[str, Any]]:
        """
        Get all print history from Moonraker API.

        Args:
            limit: Maximum number of history entries to return

        Returns:
            Dictionary containing print history or None if failed
        """
        params = {"limit": limit}
        response = self._make_request("/server/history/list", params=params)
        if response and "result" in response:
            return response["result"]
        return None


def get_moonraker_history(moonraker_url: str = None) -> Optional[Dict[str, Any]]:
    """
    Get all print history from Moonraker API.

    Args:
        moonraker_url: Moonraker API URL (if None, uses default from config)

    Returns:
        Dictionary containing print history or None if failed
    """
    if not moonraker_url:
        moonraker_url = "http://klipper.local:7125"

    api = MoonrakerAPI(moonraker_url)
    return api.get_history()


def get_moonraker_stats(filename: str, moonraker_url: str = None) -> Optional[Dict[str, Any]]:
    """
    Convenience function to get print statistics for a file

    Args:
        filename: Name of the G-code file
        moonraker_url: Moonraker API base URL

    Returns:
        Print statistics dictionary or None if not available
    """
    if not moonraker_url:
        moonraker_url = "http://klipper.local:7125"

    try:
        api = MoonrakerAPI(moonraker_url)
        return api.get_print_stats_for_file(filename)
    except Exception as e:
        logger.error(f"Failed to get Moonraker stats for {filename}: {e}")
        return None
