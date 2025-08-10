"""
Comprehensive tests for pagination capabilities
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


class TestPagination:
    """Test cases for pagination functionality"""

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

    # STL Files API Pagination Tests

    def test_stl_files_api_default_pagination(self):
        """Test STL files API default pagination"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "test_folder_1",
                    "top_level_folder": "test_folder_1",
                    "files": [
                        {"file_name": "model1.stl", "rel_path": "test_folder_1/model1.stl"},
                        {"file_name": "model2.stl", "rel_path": "test_folder_1/model2.stl"},
                    ],
                },
                {
                    "folder_name": "test_folder_2",
                    "top_level_folder": "test_folder_2",
                    "files": [
                        {"file_name": "model3.stl", "rel_path": "test_folder_2/model3.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 15,
                "total_folders": 2,
                "total_files": 3,
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/stl_files")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert "folders" in data
            assert "pagination" in data
            assert "filter" in data
            
            # Check pagination defaults
            pagination = data["pagination"]
            assert pagination["page"] == 1
            assert pagination["per_page"] == 15
            assert pagination["total_folders"] == 2
            assert pagination["total_files"] == 3
            assert pagination["total_pages"] == 1

    def test_stl_files_api_custom_pagination(self):
        """Test STL files API custom pagination"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "test_folder_1",
                    "top_level_folder": "test_folder_1",
                    "files": [
                        {"file_name": "model1.stl", "rel_path": "test_folder_1/model1.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 2,
                "per_page": 5,
                "total_folders": 10,
                "total_files": 25,
                "total_pages": 2,
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/stl_files?page=2&per_page=5")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            pagination = data["pagination"]
            assert pagination["page"] == 2
            assert pagination["per_page"] == 5
            assert pagination["total_folders"] == 10
            assert pagination["total_pages"] == 2

    def test_stl_files_api_pagination_boundary_first_page(self):
        """Test STL files API pagination at first page boundary"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [
                {
                    "folder_name": "test_folder",
                    "top_level_folder": "test_folder",
                    "files": [
                        {"file_name": "model1.stl", "rel_path": "test_folder/model1.stl"},
                    ],
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 5,
                "total_folders": 1,
                "total_files": 1,
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/stl_files?page=1&per_page=5")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            pagination = data["pagination"]
            assert pagination["page"] == 1
            assert pagination["total_pages"] == 1

    def test_stl_files_api_pagination_boundary_beyond_last_page(self):
        """Test STL files API pagination beyond last page"""
        # Mock the database manager's get_stl_files_paginated method
        mock_paginated_data = {
            "folders": [],
            "pagination": {
                "page": 3,
                "per_page": 5,
                "total_folders": 10,
                "total_files": 25,
                "total_pages": 2,
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/stl_files?page=3&per_page=5")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            pagination = data["pagination"]
            assert pagination["page"] == 3
            assert pagination["total_pages"] == 2

    # G-code Files API Pagination Tests

    def test_gcode_files_api_default_pagination(self):
        """Test G-code files API default pagination"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "test1.gcode",
                    "rel_path": "test1.gcode",
                    "folder_name": "project_a",
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
                        "job_id": "job_1",
                        "last_status": "completed",
                    },
                },
                {
                    "file_name": "test2.gcode",
                    "rel_path": "test2.gcode",
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
                "sort_by": "folder_name",
                "sort_order": "asc",
            },
        }
        
        with patch.object(
            self.app.config["DB_MANAGER"], 
            "get_gcode_files_paginated", 
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/gcode_files")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert "files" in data
            assert "pagination" in data
            assert "filter" in data
            
            # Check pagination defaults
            pagination = data["pagination"]
            assert pagination["page"] == 1
            assert pagination["per_page"] == 15
            assert pagination["total_files"] == 2
            assert pagination["total_pages"] == 1

    def test_gcode_files_api_custom_pagination(self):
        """Test G-code files API custom pagination"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "test1.gcode",
                    "rel_path": "test1.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 2,
                "per_page": 5,
                "total_files": 15,
                "total_pages": 3,
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/gcode_files?page=2&per_page=5")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            pagination = data["pagination"]
            assert pagination["page"] == 2
            assert pagination["per_page"] == 5
            assert pagination["total_files"] == 15
            assert pagination["total_pages"] == 3

    def test_gcode_files_api_pagination_boundary_first_page(self):
        """Test G-code files API pagination at first page boundary"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [
                {
                    "file_name": "test1.gcode",
                    "rel_path": "test1.gcode",
                    "folder_name": "project_a",
                    "metadata": {},
                    "base_path": "GCODE_BASE_PATH",
                    "stats": None,
                },
            ],
            "pagination": {
                "page": 1,
                "per_page": 5,
                "total_files": 1,
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/gcode_files?page=1&per_page=5")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            pagination = data["pagination"]
            assert pagination["page"] == 1
            assert pagination["total_pages"] == 1

    def test_gcode_files_api_pagination_boundary_beyond_last_page(self):
        """Test G-code files API pagination beyond last page"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [],
            "pagination": {
                "page": 4,
                "per_page": 5,
                "total_files": 15,
                "total_pages": 3,
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/gcode_files?page=4&per_page=5")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            pagination = data["pagination"]
            assert pagination["page"] == 4
            assert pagination["total_pages"] == 3

    # Edge Cases and Error Conditions for Pagination

    def test_stl_files_api_invalid_page_zero(self):
        """Test STL files API with invalid page number (zero)"""
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/stl_files?page=0")
            assert response.status_code == 200  # Should default to page 1
            
            data = json.loads(response.data)
            assert data["pagination"]["page"] == 1

    def test_stl_files_api_invalid_page_negative(self):
        """Test STL files API with invalid page number (negative)"""
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/stl_files?page=-1")
            assert response.status_code == 200  # Should default to page 1
            
            data = json.loads(response.data)
            assert data["pagination"]["page"] == 1

    def test_gcode_files_api_invalid_per_page_zero(self):
        """Test G-code files API with invalid per_page number (zero)"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [],
            "pagination": {
                "page": 1,
                "per_page": 15,  # Should default to 15
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/gcode_files?per_page=0")
            assert response.status_code == 200  # Should use default per_page
            
            data = json.loads(response.data)
            assert data["pagination"]["per_page"] == 15

    def test_gcode_files_api_invalid_per_page_negative(self):
        """Test G-code files API with invalid per_page number (negative)"""
        # Mock the database manager's get_gcode_files_paginated method
        mock_paginated_data = {
            "files": [],
            "pagination": {
                "page": 1,
                "per_page": 15,  # Should default to 15
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/gcode_files?per_page=-5")
            assert response.status_code == 200  # Should use default per_page
            
            data = json.loads(response.data)
            assert data["pagination"]["per_page"] == 15

    def test_empty_database_stl_files_pagination(self):
        """Test STL files API pagination with empty database"""
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/stl_files")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data["folders"] == []
            assert data["pagination"]["total_folders"] == 0
            assert data["pagination"]["total_files"] == 0
            assert data["pagination"]["total_pages"] == 0

    def test_empty_database_gcode_files_pagination(self):
        """Test G-code files API pagination with empty database"""
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
            return_value=mock_paginated_data
        ):
            response = self.client.get("/api/gcode_files")
            assert response.status_code == 200
            
            data = json.loads(response.data)
            assert data["files"] == []
            assert data["pagination"]["total_files"] == 0
            assert data["pagination"]["total_pages"] == 0