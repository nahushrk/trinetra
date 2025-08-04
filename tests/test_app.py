"""
Comprehensive tests for Flask app routes and functionality
Covers all routes, error cases, and edge conditions
"""

import os
import tempfile
import shutil
import zipfile
import json
from unittest.mock import patch, MagicMock, mock_open
from io import BytesIO

import pytest
from flask import Flask
from werkzeug.datastructures import FileStorage

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


class TestAppRoutes:
    """Test cases for Flask app routes"""

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

    def test_index_route(self):
        """Test the index route"""
        response = self.client.get("/")
        assert response.status_code == 200
        # Check for HTML content instead of specific text
        assert b"<!DOCTYPE html>" in response.data

    def test_gcode_files_route(self):
        """Test the gcode files route"""
        response = self.client.get("/gcode_files")
        assert response.status_code == 200

    def test_folder_view_route(self):
        """Test the folder view route"""
        # Create a test folder
        test_folder = os.path.join(self.stl_path, "test_folder")
        os.makedirs(test_folder, exist_ok=True)

        response = self.client.get("/folder/test_folder")
        assert response.status_code == 200

    def test_serve_stl_route(self):
        """Test serving STL files"""
        # Create a test STL file
        stl_file = os.path.join(self.stl_path, "test.stl")
        with open(stl_file, "w") as f:
            f.write("dummy stl content")

        response = self.client.get("/stl/test.stl")
        assert response.status_code == 200
        assert response.mimetype == "application/octet-stream"

    def test_serve_stl_route_nonexistent(self):
        """Test serving nonexistent STL file"""
        response = self.client.get("/stl/nonexistent.stl")
        assert response.status_code == 404

    def test_serve_file_route(self):
        """Test serving general files"""
        # Create a test file
        test_file = os.path.join(self.stl_path, "test.txt")
        with open(test_file, "w") as f:
            f.write("test content")

        response = self.client.get("/file/test.txt")
        assert response.status_code == 200

    def test_serve_gcode_route_stl_base(self):
        """Test serving G-code from STL base path"""
        # Create a test G-code file in STL path
        gcode_file = os.path.join(self.stl_path, "test.gcode")
        with open(gcode_file, "w") as f:
            f.write(";FLAVOR:Marlin\nG28 ;Home\n")

        response = self.client.get("/gcode/STL_BASE_PATH/test.gcode")
        assert response.status_code == 200

    def test_serve_gcode_route_gcode_base(self):
        """Test serving G-code from GCODE base path"""
        # Create a test G-code file in GCODE path
        gcode_file = os.path.join(self.gcode_path, "test.gcode")
        with open(gcode_file, "w") as f:
            f.write(";FLAVOR:Marlin\nG28 ;Home\n")

        response = self.client.get("/gcode/GCODE_BASE_PATH/test.gcode")
        assert response.status_code == 200

    def test_serve_gcode_route_invalid_base(self):
        """Test serving G-code with invalid base path"""
        response = self.client.get("/gcode/INVALID_BASE/test.gcode")
        assert response.status_code == 404

    def test_upload_route_no_file(self):
        """Test upload route with no file"""
        response = self.client.post("/upload")
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"] == "No file part"

    def test_upload_route_no_files_selected(self):
        """Test upload route with no files selected"""
        # Create a file storage object but with empty filename
        data = {"file": (BytesIO(b""), "")}
        response = self.client.post("/upload", data=data)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"] == "Only ZIP files are allowed"

    def test_upload_route_invalid_file_type(self):
        """Test upload route with invalid file type"""
        data = {"file": (BytesIO(b"dummy content"), "test.txt")}
        response = self.client.post("/upload", data=data)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"] == "Only ZIP files are allowed"

    def test_upload_route_success(self):
        """Test successful file upload"""
        # Create a test ZIP file
        zip_data = BytesIO()
        with zipfile.ZipFile(zip_data, "w") as zipf:
            zipf.writestr("test.stl", "dummy stl content")
        zip_data.seek(0)

        data = {"file": (zip_data, "test.zip")}
        response = self.client.post("/upload", data=data)
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True

    def test_delete_folder_route_no_folder_name(self):
        """Test delete folder route with no folder name"""
        response = self.client.post("/delete_folder", json={})
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"] == "Folder name is required."

    def test_delete_folder_route_success(self):
        """Test successful folder deletion"""
        # Mock the database manager to return success
        with patch.object(self.app.config["DB_MANAGER"], "delete_folder", return_value=True):
            response = self.client.post("/delete_folder", json={"folder_name": "test_folder"})
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True

    def test_delete_folder_route_nonexistent(self):
        """Test delete folder route with nonexistent folder"""
        response = self.client.post("/delete_folder", json={"folder_name": "nonexistent"})
        assert response.status_code == 404
        data = json.loads(response.data)
        assert data["error"] == "Folder does not exist."

    def test_download_folder_route_no_folder_name(self):
        """Test download folder route with no folder name"""
        response = self.client.get("/download_folder")
        assert response.status_code == 400

    def test_download_folder_route_success(self):
        """Test successful folder download"""
        # Create a test folder with files
        test_folder = os.path.join(self.stl_path, "test_folder")
        os.makedirs(test_folder, exist_ok=True)

        # Create a test file
        test_file = os.path.join(test_folder, "test.txt")
        with open(test_file, "w") as f:
            f.write("test content")

        response = self.client.get("/download_folder?folder_name=test_folder")
        assert response.status_code == 200
        assert response.mimetype == "application/zip"

    def test_copy_path_route_success(self):
        """Test successful path copying"""
        # Create a test file
        test_file = os.path.join(self.stl_path, "test.txt")
        with open(test_file, "w") as f:
            f.write("test content")

        response = self.client.get("/copy_path/test.txt")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "path" in data

    def test_copy_path_route_nonexistent(self):
        """Test copy path route with nonexistent file"""
        response = self.client.get("/copy_path/nonexistent.txt")
        assert response.status_code == 404

    def test_copy_gcode_path_route_stl_base(self):
        """Test copy G-code path from STL base"""
        # Create a test G-code file in STL path
        gcode_file = os.path.join(self.stl_path, "test.gcode")
        with open(gcode_file, "w") as f:
            f.write(";FLAVOR:Marlin\nG28 ;Home\n")

        response = self.client.get("/copy_gcode_path/STL_BASE_PATH/test.gcode")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "path" in data

    def test_copy_gcode_path_route_gcode_base(self):
        """Test copy G-code path from GCODE base"""
        # Create a test G-code file in GCODE path
        gcode_file = os.path.join(self.gcode_path, "test.gcode")
        with open(gcode_file, "w") as f:
            f.write(";FLAVOR:Marlin\nG28 ;Home\n")

        response = self.client.get("/copy_gcode_path/GCODE_BASE_PATH/test.gcode")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "path" in data

    def test_copy_gcode_path_route_invalid_base(self):
        """Test copy G-code path with invalid base"""
        response = self.client.get("/copy_gcode_path/INVALID_BASE/test.gcode")
        assert response.status_code == 404

    def test_moonraker_stats_route_success(self):
        """Test successful Moonraker stats retrieval from database"""
        # Mock the database manager to return file with stats
        mock_gcode_files = [
            {
                "file_name": "test.gcode",
                "stats": {"total_prints": 5, "successful_prints": 4, "canceled_prints": 1},
            }
        ]

        with patch.object(
            self.app.config["DB_MANAGER"], "get_all_gcode_files", return_value=mock_gcode_files
        ):
            response = self.client.get("/moonraker_stats/test.gcode")
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is True
            assert "stats" in data

    def test_moonraker_stats_route_no_stats(self):
        """Test Moonraker stats route with no stats in database"""
        # Mock the database manager to return files without matching stats
        mock_gcode_files = [
            {
                "file_name": "other.gcode",
                "stats": {"total_prints": 1, "successful_prints": 1, "canceled_prints": 0},
            }
        ]

        with patch.object(
            self.app.config["DB_MANAGER"], "get_all_gcode_files", return_value=mock_gcode_files
        ):
            response = self.client.get("/moonraker_stats/test.gcode")
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["success"] is False

    @patch("trinetra.search.search_files_and_folders")
    def test_search_route(self, mock_search):
        """Test search route"""
        mock_search.return_value = [{"folder_name": "test", "files": []}]

        response = self.client.get("/search?q=test")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "stl_files" in data
        assert "metadata" in data

    @patch("trinetra.search.search_gcode_files")
    def test_search_gcode_route(self, mock_search):
        """Test search G-code route"""
        mock_search.return_value = [{"file_name": "test.gcode"}]

        response = self.client.get("/search_gcode?q=test")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "gcode_files" in data
        assert "metadata" in data

    def test_stats_route(self):
        # Mock the database manager methods
        mock_db_stats = {
            "total_folders": 5,
            "total_stl_files": 10,
            "total_gcode_files": 8,
            "total_image_files": 3,
            "total_pdf_files": 2,
            "folders_with_gcode": 4,
        }

        mock_printing_stats = {
            "total_prints": 10,
            "successful_prints": 8,
            "canceled_prints": 2,
            "avg_print_time_hours": 2.5,
            "total_filament_meters": 100,
            "print_days": 5,
        }

        mock_activity_calendar = {
            "2023-01-01": 2,
            "2023-01-02": 1,
        }

        with patch.object(self.app.config["DB_MANAGER"], "get_stats", return_value=mock_db_stats):
            with patch.object(
                self.app.config["DB_MANAGER"],
                "get_printing_stats",
                return_value=mock_printing_stats,
            ):
                with patch.object(
                    self.app.config["DB_MANAGER"],
                    "get_activity_calendar",
                    return_value=mock_activity_calendar,
                ):
                    response = self.client.get("/stats")
                    assert response.status_code == 200

    def test_api_add_to_queue_success(self):
        # Patch add_to_queue in the app module's namespace
        with patch("app.add_to_queue", return_value=True):
            response = self.client.post(
                "/api/add_to_queue", json={"filenames": ["test.gcode"], "reset": False}
            )
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["result"] == "ok"

    def test_api_add_to_queue_failure(self):
        # Patch add_to_queue in the app module's namespace
        with patch("app.add_to_queue", return_value=False):
            response = self.client.post(
                "/api/add_to_queue", json={"filenames": ["test.gcode"], "reset": False}
            )
            assert response.status_code == 502
            data = json.loads(response.data)
            assert "error" in data

    def test_api_add_to_queue_invalid_payload(self):
        """Test API add to queue with invalid payload"""
        response = self.client.post("/api/add_to_queue", json={"filenames": "not_a_list"})
        assert response.status_code == 400
        data = json.loads(response.data)
        assert "error" in data

    def test_safe_join_function(self):
        """Test safe_join function"""
        result = self.app.safe_join("/base", "folder", "file.txt")
        assert result == "/base/folder/file.txt"

        # Test path traversal attempt
        with pytest.raises(Exception, match="Attempted Path Traversal"):
            self.app.safe_join("/base", "../outside/file.txt")

    def test_load_config_function(self):
        """Test load_config function"""
        mock_config = {"base_path": "/test/path", "log_level": "INFO"}

        with patch("builtins.open", mock_open(read_data="base_path: /test/path\nlog_level: INFO")):
            with patch("yaml.safe_load", return_value=mock_config):
                result = self.app.load_config("test.yaml")
                assert result == mock_config

    def test_load_config_function_error(self):
        """Test load_config function with error"""
        with patch("builtins.open", side_effect=FileNotFoundError()):
            result = self.app.load_config("nonexistent.yaml")
            assert result == {}

    def test_allowed_file_function(self):
        """Test allowed_file function"""
        assert self.app.allowed_file("test.zip") is True
        assert self.app.allowed_file("test.ZIP") is True
        assert self.app.allowed_file("test.txt") is False
        assert self.app.allowed_file("test.stl") is False

    def test_safe_extract_function(self):
        """Test safe_extract function"""
        mock_zip = MagicMock()
        mock_zip.namelist.return_value = ["file1.txt", "file2.txt"]

        # Test normal extraction
        with patch("os.path.realpath") as mock_realpath:
            mock_realpath.side_effect = lambda x: x
            self.app.safe_extract(mock_zip, "/test/path")
            mock_zip.extractall.assert_called_once_with("/test/path")

    def test_safe_extract_function_path_traversal(self):
        """Test safe_extract function with path traversal attempt"""
        mock_zip = MagicMock()
        mock_zip.namelist.return_value = ["../../../outside/file.txt"]

        with patch("os.path.realpath") as mock_realpath:
            mock_realpath.side_effect = lambda x: x if "outside" not in x else "/outside/file.txt"

            with pytest.raises(Exception, match="Attempted Path Traversal in Zip File"):
                self.app.safe_extract(mock_zip, "/test/path")

    def test_get_stl_files_function(self):
        """Test get_stl_files function"""
        # Mock the database manager to return expected results
        mock_result = [
            {
                "folder_name": "project1",
                "top_level_folder": "project1",
                "files": [
                    {"file_name": "model1.stl", "rel_path": "project1/model1.stl"},
                    {"file_name": "model2.stl", "rel_path": "project1/model2.stl"},
                ],
            }
        ]

        with patch.object(self.app.config["DB_MANAGER"], "get_stl_files", return_value=mock_result):
            result = self.app.get_stl_files("dummy_path")
            assert len(result) == 1
            assert result[0]["folder_name"] == "project1"
            assert len(result[0]["files"]) == 2

    def test_extract_gcode_metadata_from_file_function(self):
        """Test extract_gcode_metadata_from_file function"""
        gcode_file = os.path.join(self.temp_dir, "test.gcode")
        with open(gcode_file, "w") as f:
            f.write(";FLAVOR:Marlin\nM117 Time Left 3h59m15s\n;TIME:14355\nG28 ;Home\n")

        result = self.app.extract_gcode_metadata_from_file(gcode_file)
        assert "Time" in result
        assert result["Time"] == "3h 59m 15s"

    def test_get_folder_contents_function(self):
        """Test get_folder_contents function"""
        # Mock the database manager to return expected results
        mock_stl_files = [
            {
                "file_name": "model.stl",
                "path": "STL_BASE_PATH",
                "rel_path": "test_project/model.stl",
            }
        ]
        mock_image_files = [
            {
                "file_name": "image.png",
                "path": "STL_BASE_PATH",
                "rel_path": "test_project/image.png",
                "ext": ".png",
            }
        ]
        mock_pdf_files = [
            {
                "file_name": "document.pdf",
                "path": "STL_BASE_PATH",
                "rel_path": "test_project/document.pdf",
                "ext": ".pdf",
            }
        ]
        mock_gcode_files = [
            {
                "file_name": "model.gcode",
                "path": "STL_BASE_PATH",
                "rel_path": "test_project/model.gcode",
                "metadata": {},
            }
        ]

        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_folder_contents",
            return_value=(mock_stl_files, mock_image_files, mock_pdf_files, mock_gcode_files),
        ):
            stl_files, image_files, pdf_files, gcode_files = self.app.get_folder_contents(
                "test_project"
            )

            assert len(stl_files) == 1
            assert len(image_files) == 1
            assert len(pdf_files) == 1
            assert len(gcode_files) == 1

    def test_get_moonraker_printing_stats_function(self):
        """Test get_moonraker_printing_stats function"""
        # Test with no stats in database
        with patch.object(
            self.app.config["DB_MANAGER"],
            "get_printing_stats",
            return_value={
                "total_prints": 0,
                "successful_prints": 0,
                "canceled_prints": 0,
                "avg_print_time_hours": 0,
                "total_filament_meters": 0,
                "print_days": 0,
            },
        ):
            result = self.app.get_moonraker_printing_stats()
            assert result["total_prints"] == 0
            assert result["successful_prints"] == 0

        # Test with valid stats data
        mock_stats = {
            "total_prints": 10,
            "successful_prints": 8,
            "canceled_prints": 2,
            "avg_print_time_hours": 2.5,
            "total_filament_meters": 100,
            "print_days": 5,
        }

        with patch.object(
            self.app.config["DB_MANAGER"], "get_printing_stats", return_value=mock_stats
        ):
            result = self.app.get_moonraker_printing_stats()
            assert result["total_prints"] == 10
            assert result["successful_prints"] == 8
            assert result["print_days"] == 5
