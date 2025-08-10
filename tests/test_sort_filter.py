"""
Comprehensive tests for sorting and filtering capabilities
of the Trinetra 3D printing catalog application.
"""

import os
import tempfile
import shutil
import json
from unittest.mock import patch, Mock

import pytest
from flask import Flask

# Import the app after setting up test environment
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup logging for tests - will be configured by create_app
from trinetra.logger import get_logger, configure_logging

# Configure logging for tests with a default config
test_config = {"log_level": "INFO", "log_file": "test.log"}
configure_logging(test_config)
logger = get_logger(__name__)

from app import create_app


class TestSortFilter:
    """Test cases for sorting and filtering functionality"""

    def setup_method(self):
        """Set up test fixtures for each test method"""
        # Create temporary directories for testing
        self.temp_dir = tempfile.mkdtemp()
        self.stl_path = os.path.join(self.temp_dir, "stl_files")
        self.gcode_path = os.path.join(self.temp_dir, "gcode_files")
        os.makedirs(self.stl_path, exist_ok=True)
        os.makedirs(self.gcode_path, exist_ok=True)

        self.config = {
            "base_path": self.stl_path,
            "gcode_path": self.gcode_path,
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://localhost:7125",
            "mode": "DEV",
        }
        self.app = create_app(config_overrides=self.config)
        self.client = self.app.test_client()

    def teardown_method(self):
        """Clean up temporary directories"""
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    # STL Files API Sorting Tests

    def test_stl_files_api_sort_by_folder_name_asc(self):
        """Test STL files API sorting by folder name ascending"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "alpha_folder",
                    "top_level_folder": "alpha_folder",
                    "files": [
                        {"file_name": "model1.stl", "rel_path": "alpha_folder/model1.stl"},
                    ],
                },
                {
                    "folder_name": "beta_folder",
                    "top_level_folder": "beta_folder",
                    "files": [
                        {"file_name": "model2.stl", "rel_path": "beta_folder/model2.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 2,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?sort_by=folder_name&sort_order=asc")
            assert response.status_code == 200

            data = json.loads(response.data)
            folders = data["folders"]

            # Verify folders are sorted by name (ascending)
            assert len(folders) == 2
            assert folders[0]["folder_name"] == "alpha_folder"
            assert folders[1]["folder_name"] == "beta_folder"

    def test_stl_files_api_sort_by_folder_name_desc(self):
        """Test STL files API sorting by folder name descending"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "beta_folder",
                    "top_level_folder": "beta_folder",
                    "files": [
                        {"file_name": "model2.stl", "rel_path": "beta_folder/model2.stl"},
                    ],
                },
                {
                    "folder_name": "alpha_folder",
                    "top_level_folder": "alpha_folder",
                    "files": [
                        {"file_name": "model1.stl", "rel_path": "alpha_folder/model1.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 2,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "desc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?sort_by=folder_name&sort_order=desc")
            assert response.status_code == 200

            data = json.loads(response.data)
            folders = data["folders"]

            # Verify folders are sorted by name (descending)
            assert len(folders) == 2
            assert folders[0]["folder_name"] == "beta_folder"
            assert folders[1]["folder_name"] == "alpha_folder"

    def test_stl_files_api_sort_by_file_name_asc(self):
        """Test STL files API sorting by file name ascending"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "test_folder",
                    "top_level_folder": "test_folder",
                    "files": [
                        {"file_name": "alpha_model.stl", "rel_path": "test_folder/alpha_model.stl"},
                        {"file_name": "beta_model.stl", "rel_path": "test_folder/beta_model.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 1,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "file_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?sort_by=file_name&sort_order=asc")
            assert response.status_code == 200

            data = json.loads(response.data)
            folders = data["folders"]

            # Verify files within folders are sorted by name (ascending)
            assert len(folders) == 1
            files = folders[0]["files"]
            assert len(files) == 2
            assert files[0]["file_name"] == "alpha_model.stl"
            assert files[1]["file_name"] == "beta_model.stl"

    def test_stl_files_api_sort_by_file_name_desc(self):
        """Test STL files API sorting by file name descending"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "test_folder",
                    "top_level_folder": "test_folder",
                    "files": [
                        {"file_name": "beta_model.stl", "rel_path": "test_folder/beta_model.stl"},
                        {"file_name": "alpha_model.stl", "rel_path": "test_folder/alpha_model.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 1,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "file_name",
                "sort_order": "desc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?sort_by=file_name&sort_order=desc")
            assert response.status_code == 200

            data = json.loads(response.data)
            folders = data["folders"]

            # Verify files within folders are sorted by name (descending)
            assert len(folders) == 1
            files = folders[0]["files"]
            assert len(files) == 2
            assert files[0]["file_name"] == "beta_model.stl"
            assert files[1]["file_name"] == "alpha_model.stl"

    def test_stl_files_api_sort_by_created_at_asc(self):
        """Test STL files API sorting by created_at ascending"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "older_folder",
                    "top_level_folder": "older_folder",
                    "files": [
                        {"file_name": "old_model.stl", "rel_path": "older_folder/old_model.stl"},
                    ],
                },
                {
                    "folder_name": "newer_folder",
                    "top_level_folder": "newer_folder",
                    "files": [
                        {"file_name": "new_model.stl", "rel_path": "newer_folder/new_model.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 2,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "created_at",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?sort_by=created_at&sort_order=asc")
            assert response.status_code == 200

    def test_stl_files_api_sort_by_created_at_desc(self):
        """Test STL files API sorting by created_at descending"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "newer_folder",
                    "top_level_folder": "newer_folder",
                    "files": [
                        {"file_name": "new_model.stl", "rel_path": "newer_folder/new_model.stl"},
                    ],
                },
                {
                    "folder_name": "older_folder",
                    "top_level_folder": "older_folder",
                    "files": [
                        {"file_name": "old_model.stl", "rel_path": "older_folder/old_model.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 2,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "created_at",
                "sort_order": "desc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?sort_by=created_at&sort_order=desc")
            assert response.status_code == 200

    # STL Files API Filtering Tests

    def test_stl_files_api_filter_by_folder_name(self):
        """Test STL files API filtering by folder name"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "project_a",
                    "top_level_folder": "project_a",
                    "files": [
                        {"file_name": "part_a1.stl", "rel_path": "project_a/part_a1.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 1,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "project_a",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?filter=project_a")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["text"] == "project_a"

    def test_stl_files_api_filter_by_file_name(self):
        """Test STL files API filtering by file name"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "project_a",
                    "top_level_folder": "project_a",
                    "files": [
                        {"file_name": "part_a1.stl", "rel_path": "project_a/part_a1.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 1,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "part_a1",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?filter=part_a1")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["text"] == "part_a1"

    def test_stl_files_api_filter_type_today(self):
        """Test STL files API filtering by today's files"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "recent_folder",
                    "top_level_folder": "recent_folder",
                    "files": [
                        {
                            "file_name": "recent_model.stl",
                            "rel_path": "recent_folder/recent_model.stl",
                        },
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 1,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "today",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?filter_type=today")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["type"] == "today"

    def test_stl_files_api_filter_type_week(self):
        """Test STL files API filtering by week's files"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "weekly_folder",
                    "top_level_folder": "weekly_folder",
                    "files": [
                        {
                            "file_name": "weekly_model.stl",
                            "rel_path": "weekly_folder/weekly_model.stl",
                        },
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 1,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "week",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?filter_type=week")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["type"] == "week"

    # G-code Files API Sorting Tests

    def test_gcode_files_api_sort_by_file_name_asc(self):
        """Test G-code files API sorting by file name ascending"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "a_file.gcode",
                    "rel_path": "a_file.gcode",
                    "folder_name": "project_b",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
                {
                    "file_name": "z_file.gcode",
                    "rel_path": "z_file.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "file_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?sort_by=file_name&sort_order=asc")
            assert response.status_code == 200

            data = json.loads(response.data)
            files = data["files"]

            # Verify files are sorted by name (ascending)
            assert len(files) == 2
            assert files[0]["file_name"] == "a_file.gcode"
            assert files[1]["file_name"] == "z_file.gcode"

    def test_gcode_files_api_sort_by_file_name_desc(self):
        """Test G-code files API sorting by file name descending"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "z_file.gcode",
                    "rel_path": "z_file.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
                {
                    "file_name": "a_file.gcode",
                    "rel_path": "a_file.gcode",
                    "folder_name": "project_b",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "file_name",
                "sort_order": "desc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?sort_by=file_name&sort_order=desc")
            assert response.status_code == 200

            data = json.loads(response.data)
            files = data["files"]

            # Verify files are sorted by name (descending)
            assert len(files) == 2
            assert files[0]["file_name"] == "z_file.gcode"
            assert files[1]["file_name"] == "a_file.gcode"

    def test_gcode_files_api_sort_by_folder_name_asc(self):
        """Test G-code files API sorting by folder name ascending"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "test1.gcode",
                    "rel_path": "test1.gcode",
                    "folder_name": "alpha_project",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
                {
                    "file_name": "test2.gcode",
                    "rel_path": "test2.gcode",
                    "folder_name": "beta_project",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?sort_by=folder_name&sort_order=asc")
            assert response.status_code == 200

    def test_gcode_files_api_sort_by_folder_name_desc(self):
        """Test G-code files API sorting by folder name descending"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "test1.gcode",
                    "rel_path": "test1.gcode",
                    "folder_name": "beta_project",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
                {
                    "file_name": "test2.gcode",
                    "rel_path": "test2.gcode",
                    "folder_name": "alpha_project",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "desc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?sort_by=folder_name&sort_order=desc")
            assert response.status_code == 200

    def test_gcode_files_api_sort_by_print_count(self):
        """Test G-code files API sorting by print count"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "high_count.gcode",
                    "rel_path": "high_count.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": {
                        "print_count": 5,
                        "successful_prints": 5,
                        "canceled_prints": 0,
                        "avg_duration": 3600,
                        "total_print_time": 18000,
                        "total_filament_used": 25000,
                        "last_print_date": "2023-01-02T12:00:00",
                        "success_rate": 1.0,
                        "job_id": "job_high",
                        "last_status": "completed",
                    },
                },
                {
                    "file_name": "low_count.gcode",
                    "rel_path": "low_count.gcode",
                    "folder_name": "project_b",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": {
                        "print_count": 2,
                        "successful_prints": 2,
                        "canceled_prints": 0,
                        "avg_duration": 3600,
                        "total_print_time": 7200,
                        "total_filament_used": 10000,
                        "last_print_date": "2023-01-01T12:00:00",
                        "success_rate": 1.0,
                        "job_id": "job_low",
                        "last_status": "completed",
                    },
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "print_count",
                "sort_order": "desc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?sort_by=print_count&sort_order=desc")
            assert response.status_code == 200

            data = json.loads(response.data)
            files = data["files"]

            # Verify files are sorted by print count (descending)
            assert len(files) == 2
            assert files[0]["stats"]["print_count"] == 5
            assert files[1]["stats"]["print_count"] == 2

    def test_gcode_files_api_sort_by_last_print_date(self):
        """Test G-code files API sorting by last print date"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "recent.gcode",
                    "rel_path": "recent.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": {
                        "print_count": 1,
                        "successful_prints": 1,
                        "canceled_prints": 0,
                        "avg_duration": 3600,
                        "total_print_time": 3600,
                        "total_filament_used": 10000,
                        "last_print_date": "2023-01-02T12:00:00",
                        "success_rate": 1.0,
                        "job_id": "job_recent",
                        "last_status": "completed",
                    },
                },
                {
                    "file_name": "older.gcode",
                    "rel_path": "older.gcode",
                    "folder_name": "project_b",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": {
                        "print_count": 1,
                        "successful_prints": 1,
                        "canceled_prints": 0,
                        "avg_duration": 3600,
                        "total_print_time": 3600,
                        "total_filament_used": 10000,
                        "last_print_date": "2023-01-01T12:00:00",
                        "success_rate": 1.0,
                        "job_id": "job_older",
                        "last_status": "completed",
                    },
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 2,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "last_print_date",
                "sort_order": "desc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?sort_by=last_print_date&sort_order=desc")
            assert response.status_code == 200

    # G-code Files API Filtering Tests

    def test_gcode_files_api_filter_by_file_name(self):
        """Test G-code files API filtering by file name"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "part_a1.gcode",
                    "rel_path": "part_a1.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "part_a1",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?filter=part_a1")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Check that returned files match the filter
            assert len(data["files"]) == 1
            assert "part_a1" in data["files"][0]["file_name"].lower()

            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["text"] == "part_a1"

    def test_gcode_files_api_filter_by_folder_name(self):
        """Test G-code files API filtering by folder name"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "test.gcode",
                    "rel_path": "test.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "project_a",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?filter=project_a")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Check that returned files are from matching folders
            assert len(data["files"]) == 1
            assert "project_a" in data["files"][0]["folder_name"].lower()

            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["text"] == "project_a"

    def test_gcode_files_api_filter_type_successful(self):
        """Test G-code files API filtering by successful prints"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "successful.gcode",
                    "rel_path": "successful.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": {
                        "print_count": 3,
                        "successful_prints": 3,
                        "canceled_prints": 0,
                        "avg_duration": 3600,
                        "total_print_time": 10800,
                        "total_filament_used": 15000,
                        "last_print_date": "2023-01-01T12:00:00",
                        "success_rate": 1.0,
                        "job_id": "job_success",
                        "last_status": "completed",
                    },
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "successful",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?filter_type=successful")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["type"] == "successful"

    def test_gcode_files_api_filter_type_failed(self):
        """Test G-code files API filtering by failed prints"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "failed.gcode",
                    "rel_path": "failed.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": {
                        "print_count": 2,
                        "successful_prints": 0,
                        "canceled_prints": 2,
                        "avg_duration": 3600,
                        "total_print_time": 7200,
                        "total_filament_used": 10000,
                        "last_print_date": "2023-01-01T12:00:00",
                        "success_rate": 0.0,
                        "job_id": "job_failed",
                        "last_status": "cancelled",
                    },
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "failed",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?filter_type=failed")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["type"] == "failed"

    def test_gcode_files_api_filter_type_today(self):
        """Test G-code files API filtering by today's files"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "recent.gcode",
                    "rel_path": "recent.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "today",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?filter_type=today")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["type"] == "today"

    def test_gcode_files_api_filter_type_week(self):
        """Test G-code files API filtering by week's files"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "weekly.gcode",
                    "rel_path": "weekly.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "",
                "type": "week",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?filter_type=week")
            assert response.status_code == 200

            data = json.loads(response.data)
            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["type"] == "week"

    # Combined Sort and Filter Tests

    def test_stl_files_api_combined_sort_filter_paginate(self):
        """Test STL files API with combined sorting, filtering, and pagination"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "project_alpha",
                    "top_level_folder": "project_alpha",
                    "files": [
                        {"file_name": "model1.stl", "rel_path": "project_alpha/model1.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 10,
                "total_folders": 1,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "project",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get(
                "/api/stl_files?sort_by=folder_name&sort_order=asc&filter=project&per_page=10&page=1"
            )
            assert response.status_code == 200

            data = json.loads(response.data)
            assert "folders" in data
            assert "pagination" in data
            assert "filter" in data

            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["text"] == "project"
            assert filter_info["sort_by"] == "folder_name"
            assert filter_info["sort_order"] == "asc"

    def test_gcode_files_api_combined_sort_filter_paginate(self):
        """Test G-code files API with combined sorting, filtering, and pagination"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "part_alpha.gcode",
                    "rel_path": "part_alpha.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 10,
                "total_files": 1,
                "total_pages": 1,
            },
            "filter": {
                "text": "part",
                "type": "all",
                "sort_by": "file_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get(
                "/api/gcode_files?sort_by=file_name&sort_order=asc&filter=part&per_page=10&page=1"
            )
            assert response.status_code == 200

            data = json.loads(response.data)
            assert "files" in data
            assert "pagination" in data
            assert "filter" in data

            # Verify filter was applied
            filter_info = data["filter"]
            assert filter_info["text"] == "part"
            assert filter_info["sort_by"] == "file_name"
            assert filter_info["sort_order"] == "asc"

    # Edge Cases and Error Conditions for Sort and Filter

    def test_stl_files_api_invalid_sort_by(self):
        """Test STL files API with invalid sort field"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 0,
                "total_files": 0,
                "total_pages": 0,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",  # Should default to folder_name
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?sort_by=invalid_field")
            assert response.status_code == 200  # Should use default sorting

    def test_stl_files_api_invalid_sort_order(self):
        """Test STL files API with invalid sort order"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 0,
                "total_files": 0,
                "total_pages": 0,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",  # Should default to asc
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/stl_files?sort_order=invalid")
            assert response.status_code == 200  # Should use default sorting

    def test_gcode_files_api_invalid_sort_by(self):
        """Test G-code files API with invalid sort field"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 0,
                "total_pages": 0,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",  # Should default to folder_name
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?sort_by=invalid_field")
            assert response.status_code == 200  # Should use default sorting

    def test_gcode_files_api_invalid_sort_order(self):
        """Test G-code files API with invalid sort order"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 0,
                "total_pages": 0,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",  # Should default to asc
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get("/api/gcode_files?sort_order=invalid")
            assert response.status_code == 200  # Should use default sorting

    def test_empty_database_stl_files_sort_filter(self):
        """Test STL files API sort and filter with empty database"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 0,
                "total_files": 0,
                "total_pages": 0,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_stl_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get(
                "/api/stl_files?sort_by=folder_name&sort_order=asc&filter=test"
            )
            assert response.status_code == 200

            data = json.loads(response.data)
            assert data["folders"] == []
            assert data["pagination"]["total_folders"] == 0
            assert data["pagination"]["total_files"] == 0

    def test_empty_database_gcode_files_sort_filter(self):
        """Test G-code files API sort and filter with empty database"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_files": 0,
                "total_pages": 0,
            },
            "filter": {
                "text": "",
                "type": "all",
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_gcode_files_paginated",
            return_value=mock_paginated_data,
        ):
            response = self.client.get(
                "/api/gcode_files?sort_by=folder_name&sort_order=asc&filter=test"
            )
            assert response.status_code == 200

            data = json.loads(response.data)
            assert data["files"] == []
            assert data["pagination"]["total_files"] == 0
