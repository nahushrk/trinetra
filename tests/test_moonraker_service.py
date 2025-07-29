"""
Tests for moonraker_service.py module
Covers positive and negative test cases for Moonraker service
"""

import json
import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
import os

# Setup logging for tests
from trinetra.logger import get_logger, configure_logging

# Configure logging for tests
test_config = {"log_level": "INFO", "log_file": "test.log"}
configure_logging(test_config)
logger = get_logger(__name__)

from trinetra.moonraker_service import MoonrakerService
from trinetra.moonraker import MoonrakerAPI
from trinetra.models import GCodeFile, GCodeFileStats
from trinetra.database import DatabaseManager


class TestMoonrakerService(unittest.TestCase):
    """Test cases for MoonrakerService class"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_moonraker_client = Mock(spec=MoonrakerAPI)
        self.service = MoonrakerService(self.mock_moonraker_client)

        # Create a mock database session
        self.mock_session = Mock()

        # Sample file stats data
        self.sample_stats_data = {
            "test.gcode": {
                "print_count": 3,
                "successful_prints": 3,
                "canceled_prints": 0,
                "total_print_time": 7200,  # 2 hours
                "total_filament_used": 10000,  # 10 meters
                "success_rate": 1.0,
                "last_print_date": datetime.now(),
                "job_id": "job_123",
                "last_status": "completed",
            }
        }

    def test_init_with_valid_client(self):
        """Test successful service initialization with valid client"""
        service = MoonrakerService(self.mock_moonraker_client)
        self.assertEqual(service.client, self.mock_moonraker_client)

    @patch("trinetra.moonraker_service.datetime")
    def test_fetch_all_file_statistics_success(self, mock_datetime):
        """Test successful fetching of all file statistics"""
        # Mock datetime for consistent timestamps
        mock_datetime.fromtimestamp.return_value = datetime(2023, 1, 1)

        # Mock history response - get_history() returns the result directly, not wrapped in result key
        mock_history_response = {
            "count": 3,
            "jobs": [
                {
                    "filename": "test.gcode",
                    "status": "completed",
                    "print_duration": 3600,
                    "filament_used": 5000,
                    "end_time": 1640995200,  # 2022-01-01
                    "job_id": "job_1",
                },
                {
                    "filename": "test.gcode",
                    "status": "completed",
                    "print_duration": 3600,
                    "filament_used": 5000,
                    "end_time": 1640995200,  # 2022-01-01
                    "job_id": "job_2",
                },
                {
                    "filename": "other.gcode",
                    "status": "cancelled",
                    "print_duration": 1800,
                    "filament_used": 2500,
                    "end_time": 1640995200,  # 2022-01-01
                    "job_id": "job_3",
                },
            ],
        }

        self.mock_moonraker_client.get_history.return_value = mock_history_response

        # Call the method
        result = self.service.fetch_all_file_statistics()

        # Verify the results
        self.assertIn("test.gcode", result)
        self.assertIn("other.gcode", result)
        self.assertEqual(result["test.gcode"]["print_count"], 2)
        self.assertEqual(result["test.gcode"]["total_print_time"], 7200)
        self.assertEqual(result["test.gcode"]["total_filament_used"], 10000)
        self.assertEqual(result["test.gcode"]["success_rate"], 1.0)
        self.assertEqual(result["other.gcode"]["print_count"], 1)
        self.assertEqual(result["other.gcode"]["success_rate"], 0.0)

    def test_fetch_all_file_statistics_no_result(self):
        """Test fetching file statistics with no result"""
        self.mock_moonraker_client.get_history.return_value = None

        result = self.service.fetch_all_file_statistics()
        self.assertEqual(result, {})

    def test_fetch_all_file_statistics_missing_jobs_key(self):
        """Test fetching file statistics with missing jobs key"""
        self.mock_moonraker_client.get_history.return_value = {"error": "not found"}

        result = self.service.fetch_all_file_statistics()
        self.assertEqual(result, {})

    def test_update_all_file_stats_success(self):
        """Test successful update of all file stats"""
        # Mock the fetch_all_file_statistics method
        with patch.object(
            self.service, "fetch_all_file_statistics", return_value=self.sample_stats_data
        ):
            # Mock GCodeFile objects
            mock_gcode_file = Mock(spec=GCodeFile)
            mock_gcode_file.id = 1
            mock_gcode_file.file_name = "test.gcode"

            # Mock query to return GCodeFile objects
            self.mock_session.query.return_value.all.return_value = [mock_gcode_file]

            # Mock query to check if stats exist (return None to simulate new stats)
            self.mock_session.query.return_value.filter.return_value.first.return_value = None

            # Call the method
            result = self.service.update_all_file_stats(self.mock_session)

            # Verify the results
            self.assertEqual(result["updated"], 1)
            self.assertEqual(result["failed"], 0)

            # Verify that add was called for new stats
            self.mock_session.add.assert_called_once()
            self.mock_session.commit.assert_called_once()

    def test_update_all_file_stats_with_existing_stats(self):
        """Test updating file stats when stats already exist"""
        # Mock the fetch_all_file_statistics method
        with patch.object(
            self.service, "fetch_all_file_statistics", return_value=self.sample_stats_data
        ):
            # Mock GCodeFile objects
            mock_gcode_file = Mock(spec=GCodeFile)
            mock_gcode_file.id = 1
            mock_gcode_file.file_name = "test.gcode"

            # Mock existing stats
            mock_existing_stats = Mock(spec=GCodeFileStats)
            mock_existing_stats.print_count = 1
            mock_existing_stats.total_print_time = 3600
            mock_existing_stats.total_filament_used = 5000
            mock_existing_stats.success_rate = 1.0
            mock_existing_stats.job_id = "old_job"
            mock_existing_stats.last_status = "completed"

            # Mock query to return GCodeFile objects
            self.mock_session.query.return_value.all.return_value = [mock_gcode_file]

            # Mock query to check if stats exist (return existing stats)
            self.mock_session.query.return_value.filter.return_value.first.return_value = (
                mock_existing_stats
            )

            # Call the method
            result = self.service.update_all_file_stats(self.mock_session)

            # Verify the results
            self.assertEqual(result["updated"], 1)
            self.assertEqual(result["failed"], 0)

            # Verify that existing stats were updated
            self.assertEqual(mock_existing_stats.print_count, 3)
            self.assertEqual(mock_existing_stats.total_print_time, 7200)
            self.assertEqual(mock_existing_stats.total_filament_used, 10000)
            self.assertEqual(mock_existing_stats.job_id, "job_123")

            # Verify commit was called
            self.mock_session.commit.assert_called_once()

    def test_update_all_file_stats_no_matching_files(self):
        """Test updating file stats when no files match"""
        # Mock the fetch_all_file_statistics method
        with patch.object(
            self.service, "fetch_all_file_statistics", return_value=self.sample_stats_data
        ):
            # Mock query to return no GCodeFile objects
            self.mock_session.query.return_value.all.return_value = []

            # Call the method
            result = self.service.update_all_file_stats(self.mock_session)

            # Verify the results
            self.assertEqual(result["updated"], 0)
            self.assertEqual(result["failed"], 0)

            # Verify commit was called
            self.mock_session.commit.assert_called_once()

    def test_update_all_file_stats_fetch_fails(self):
        """Test updating file stats when fetching fails"""
        # Mock the fetch_all_file_statistics method to raise an exception
        with patch.object(
            self.service, "fetch_all_file_statistics", side_effect=Exception("Fetch failed")
        ):
            # Mock query to return GCodeFile objects
            self.mock_session.query.return_value.all.return_value = []

            # Call the method
            result = self.service.update_all_file_stats(self.mock_session)

            # Verify the results
            self.assertEqual(result["updated"], 0)
            self.assertEqual(result["failed"], 0)

            # Verify rollback was called
            self.mock_session.rollback.assert_called_once()

    def test_reload_moonraker_only(self):
        """Test reload_moonraker_only method"""
        # Mock the update_all_file_stats method
        with patch.object(
            self.service, "update_all_file_stats", return_value={"updated": 5, "failed": 0}
        ):
            # Call the method
            result = self.service.reload_moonraker_only(self.mock_session)

            # Verify the results
            self.assertEqual(result["updated"], 5)
            self.assertEqual(result["failed"], 0)

    def test_fetch_all_file_statistics_with_test_data(self):
        """Test fetching file statistics with our test data"""
        # Load mock data from our test file
        mock_data_path = os.path.join(
            os.path.dirname(__file__), "test_data", "moonraker_api_response_mock.json"
        )
        with open(mock_data_path, "r") as f:
            mock_history_response = json.load(f)

        self.mock_moonraker_client.get_history.return_value = mock_history_response

        # Call the method
        result = self.service.fetch_all_file_statistics()

        # Verify the results
        # We should have stats for all files in our mock data
        expected_files = [
            "part_a1_0.2mm_PLA.gcode",
            "part_a1-0.3mm_PETG.gcode",
            "part_a2_0.1mm_ABS.gcode",
            "part_b1_0.2mm_PLA.gcode",
            "part_b1-0.3mm_PETG.gcode",
        ]

        for filename in expected_files:
            self.assertIn(filename, result)

        # Check specific stats for one file
        self.assertEqual(result["part_a1_0.2mm_PLA.gcode"]["print_count"], 2)
        self.assertEqual(result["part_a1_0.2mm_PLA.gcode"]["total_print_time"], 7100.0)
        self.assertEqual(result["part_a1_0.2mm_PLA.gcode"]["total_filament_used"], 19800.0)
        self.assertEqual(result["part_a1_0.2mm_PLA.gcode"]["success_rate"], 1.0)

        # Check that the cancelled print affects the success rate
        self.assertEqual(result["part_b1-0.3mm_PETG.gcode"]["print_count"], 1)
        self.assertEqual(result["part_b1-0.3mm_PETG.gcode"]["success_rate"], 0.0)

    def test_update_all_file_stats_with_test_data(self):
        """Test updating all file stats with our test data"""
        # Load mock data from our test file
        mock_data_path = os.path.join(
            os.path.dirname(__file__), "test_data", "moonraker_api_response_mock.json"
        )
        with open(mock_data_path, "r") as f:
            mock_history_response = json.load(f)

        # Process the mock data to get the expected stats
        self.mock_moonraker_client.get_history.return_value = mock_history_response
        expected_stats = self.service.fetch_all_file_statistics()

        # Mock the fetch_all_file_statistics method to return our processed test data
        with patch.object(self.service, "fetch_all_file_statistics", return_value=expected_stats):
            # Create mock GCodeFile objects for our test files
            mock_gcode_files = []
            test_files = [
                "part_a1_0.2mm_PLA.gcode",
                "part_a1-0.3mm_PETG.gcode",
                "part_a2_0.1mm_ABS.gcode",
                "part_b1_0.2mm_PLA.gcode",
                "part_b1-0.3mm_PETG.gcode",
            ]

            for i, filename in enumerate(test_files, 1):
                mock_gcode_file = Mock(spec=GCodeFile)
                mock_gcode_file.id = i
                mock_gcode_file.file_name = filename
                mock_gcode_files.append(mock_gcode_file)

            # Mock query to return GCodeFile objects
            self.mock_session.query.return_value.all.return_value = mock_gcode_files

            # Mock query to check if stats exist (return None to simulate new stats)
            self.mock_session.query.return_value.filter.return_value.first.return_value = None

            # Call the method
            result = self.service.update_all_file_stats(self.mock_session)

            # Verify the results
            self.assertEqual(result["updated"], 5)
            self.assertEqual(result["failed"], 0)

            # Verify that add was called for each file
            self.assertEqual(self.mock_session.add.call_count, 5)
            self.mock_session.commit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
