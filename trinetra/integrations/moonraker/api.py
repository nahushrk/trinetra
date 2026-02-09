"""
Moonraker API integration module for Trinetra
Handles communication with Moonraker API to get print history and other information
"""

import requests
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from trinetra.logger import get_logger

logger = get_logger(__name__)


class MoonrakerAPI:
    """Client for interacting with Moonraker API"""

    def __init__(self, base_url: str) -> None:
        """
        Initialize Moonraker API client

        Args:
            base_url: Base URL for Moonraker API
        """
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.timeout = 10  # 10 second timeout

    def _make_request(
        self, endpoint: str, method: str = "GET", **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        Make a request to the Moonraker API using requests library

        Args:
            endpoint: API endpoint (e.g., "/server/history/list")
            method: HTTP method (GET, POST, etc.)
            **kwargs: Additional arguments for requests

        Returns:
            Response data as dictionary or None if request failed
        """
        url = urljoin(self.base_url, endpoint)

        try:
            logger.debug(f"Making request to {url} with params {kwargs.get('params', {})}")
            response = self.session.request(method, url, **kwargs)
            logger.debug(f"Response status code: {response.status_code}")
            response.raise_for_status()
            result = response.json()
            logger.debug(f"Response JSON: {result}")
            return result
        except requests.exceptions.RequestException as e:
            logger.error(f"Moonraker API request failed for {url}: {e}")
            return None
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
        logger.debug(f"Getting history with limit {limit}")
        params = {"limit": limit}
        response = self._make_request("/server/history/list", params=params)
        logger.debug(f"History response: {response}")
        if response and "result" in response:
            return response["result"]
        return None

    def queue_job(self, filenames: List[str], reset: bool = False) -> bool:
        """
        Add jobs to the Moonraker print queue.

        Args:
            filenames: List of relative file paths to queue
            reset: Whether to reset the queue (default False)

        Returns:
            True if successfully added to queue, False otherwise
        """
        payload = {"filenames": filenames, "reset": reset}
        logger.debug(f"Moonraker queue_job payload: {payload}")
        response = self._make_request("/server/job_queue/job", method="POST", json=payload)
        logger.debug(f"Moonraker queue_job response: {response}")

        # Check if the request was successful
        if response is not None:
            # Moonraker typically returns a response with result field on success
            return "result" in response
        return False


def get_moonraker_history(moonraker_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Get all print history from Moonraker API.

    Args:
        moonraker_url: Moonraker API URL (if None, uses default from config)

    Returns:
        Dictionary containing print history or None if failed
    """
    api = MoonrakerAPI(moonraker_url)
    return api.get_history()


def get_moonraker_stats(
    filename: str, moonraker_url: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Convenience function to get print statistics for a file

    Args:
        filename: Name of the G-code file
        moonraker_url: Moonraker API base URL

    Returns:
        Print statistics dictionary or None if not available
    """
    try:
        api = MoonrakerAPI(moonraker_url)
        return api.get_print_stats_for_file(filename)
    except Exception as e:
        logger.error(f"Failed to get Moonraker stats for {filename}: {e}")
        return None


def add_to_queue(
    filenames: List[str], reset: bool = False, moonraker_url: Optional[str] = None
) -> bool:
    """
    Add jobs to the Moonraker print queue.

    Args:
        filenames: List of relative file paths to queue
        reset: Whether to reset the queue (default False)
        moonraker_url: Moonraker API base URL

    Returns:
        True if successfully added to queue, False otherwise
    """
    try:
        api = MoonrakerAPI(moonraker_url)
        return api.queue_job(filenames, reset)
    except Exception as e:
        logger.error(f"Failed to add to Moonraker queue for {filenames}: {e}")
        logger.error(f"Error: {e}")
        return False
