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
from trinetra.config import ConfigManager

import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Setup logging for tests
from trinetra.logger import get_logger

logger = get_logger(__name__)

# Import create_app function, not the app instance
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

        # Create base config for testing (this will be used as the base config in ConfigManager)
        self.base_config = {
            "base_path": self.stl_path,
            "gcode_path": self.gcode_path,
            "log_level": "INFO",
            "search_result_limit": 25,
            "moonraker_url": "http://localhost:7125",
            "mode": "DEV",
        }

        # Create app with ConfigManager using base config and empty override
        self.app = create_app(config_manager=ConfigManager.from_dict(self.base_config, {}))
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
        # Create a test folder
        test_folder = os.path.join(self.stl_path, "test_folder")
        os.makedirs(test_folder, exist_ok=True)

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

    @patch("trinetra.moonraker.get_moonraker_stats")
    def test_moonraker_stats_route_success(self, mock_get_stats):
        """Test successful Moonraker stats retrieval"""
        mock_get_stats.return_value = {"total_prints": 5, "successful_prints": 4}

        response = self.client.get("/moonraker_stats/test.gcode")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        assert "stats" in data

    @patch("trinetra.moonraker.get_moonraker_stats")
    def test_moonraker_stats_route_no_stats(self, mock_get_stats):
        """Test Moonraker stats route with no stats"""
        mock_get_stats.return_value = None

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
        # Patch the get_moonraker_printing_stats method on the app instance
        with patch.object(
            self.app,
            "get_moonraker_printing_stats",
            return_value={
                "total_prints": 10,
                "successful_prints": 8,
                "canceled_prints": 2,
                "avg_print_time_hours": 2.5,
                "total_filament_meters": 100,
                "print_days": 5,
            },
        ):
            with patch("trinetra.moonraker.get_moonraker_history", return_value={"jobs": []}):
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

    def test_config_manager_integration(self):
        """Test that ConfigManager is properly integrated into the app"""
        # Verify that the app has a config manager
        assert hasattr(self.app, "config")
        assert "CONFIG_MANAGER" in self.app.config

        config_manager = self.app.config["CONFIG_MANAGER"]
        assert config_manager is not None

        # Verify that the config manager has the expected base config
        base_config = config_manager.get_base_config()
        assert base_config["base_path"] == self.stl_path
        assert base_config["gcode_path"] == self.gcode_path
        assert base_config["log_level"] == "INFO"
        assert base_config["search_result_limit"] == 25
        assert base_config["moonraker_url"] == "http://localhost:7125"
        assert base_config["mode"] == "DEV"

        # Verify that override is empty (as expected for testing)
        override_config = config_manager.get_override_config()
        assert override_config == {}

        # Verify that merged config matches base config (no overrides)
        merged_config = config_manager.get_config()
        assert merged_config.base_path == self.stl_path
        assert merged_config.gcode_path == self.gcode_path
        assert merged_config.log_level == "INFO"
        assert merged_config.search_result_limit == 25
        assert merged_config.moonraker_url == "http://localhost:7125"
        assert merged_config.mode == "DEV"

    def test_api_get_config(self):
        """Test GET /api/config endpoint"""
        response = self.client.get("/api/config")
        assert response.status_code == 200

        data = json.loads(response.data)
        assert "base" in data
        assert "override" in data
        assert "merged" in data

        # Verify base config
        assert data["base"]["base_path"] == self.stl_path
        assert data["base"]["gcode_path"] == self.gcode_path
        assert data["base"]["log_level"] == "INFO"

        # Verify override is empty
        assert data["override"] == {}

        # Verify merged config
        assert data["merged"]["base_path"] == self.stl_path
        assert data["merged"]["gcode_path"] == self.gcode_path
        assert data["merged"]["log_level"] == "INFO"

    def test_api_update_config(self):
        """Test POST /api/config endpoint"""
        # Test updating config
        update_data = {"log_level": "DEBUG", "search_result_limit": 50}

        response = self.client.post("/api/config", json=update_data)
        assert response.status_code == 200

        data = json.loads(response.data)
        assert data["success"] is True

        # Verify override was updated
        assert data["override"]["log_level"] == "DEBUG"
        assert data["override"]["search_result_limit"] == 50

        # Verify merged config reflects changes
        assert data["merged"]["log_level"] == "DEBUG"
        assert data["merged"]["search_result_limit"] == 50

        # Verify base config unchanged
        assert data["merged"]["base_path"] == self.stl_path
        assert data["merged"]["gcode_path"] == self.gcode_path

    def test_api_update_config_invalid_data(self):
        """Test POST /api/config with invalid data"""
        response = self.client.post("/api/config", json="not_a_dict")
        assert response.status_code == 400

        data = json.loads(response.data)
        assert "error" in data

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
        test_base = os.path.join(self.temp_dir, "test_stl")
        os.makedirs(test_base, exist_ok=True)

        test_folder = os.path.join(test_base, "project1")
        os.makedirs(test_folder, exist_ok=True)

        # Create STL files
        stl_file1 = os.path.join(test_folder, "model1.stl")
        stl_file2 = os.path.join(test_folder, "model2.stl")

        with open(stl_file1, "w") as f:
            f.write("dummy stl content")
        with open(stl_file2, "w") as f:
            f.write("dummy stl content")

        result = self.app.get_stl_files(test_base)
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
        test_folder = os.path.join(self.stl_path, "test_project")
        os.makedirs(test_folder, exist_ok=True)

        # Create different file types
        stl_file = os.path.join(test_folder, "model.stl")
        image_file = os.path.join(test_folder, "image.png")
        pdf_file = os.path.join(test_folder, "document.pdf")
        gcode_file = os.path.join(test_folder, "model.gcode")

        for file_path in [stl_file, image_file, pdf_file, gcode_file]:
            with open(file_path, "w") as f:
                f.write("dummy content")

        stl_files, image_files, pdf_files, gcode_files = self.app.get_folder_contents(
            "test_project"
        )

        assert len(stl_files) == 1
        assert len(image_files) == 1
        assert len(pdf_files) == 1
        assert len(gcode_files) == 1

    def test_get_moonraker_printing_stats_function(self):
        """Test get_moonraker_printing_stats function"""
        with patch("trinetra.moonraker.get_moonraker_history", return_value=None):
            result = self.app.get_moonraker_printing_stats()
            assert result["total_prints"] == 0
            assert result["successful_prints"] == 0

        # Test with Moonraker URL but no history
        with patch("trinetra.moonraker.get_moonraker_history", return_value=None):
            result = self.app.get_moonraker_printing_stats()
            assert result["total_prints"] == 0

        # Test with valid history data
        mock_history = {
            "jobs": [
                {
                    "status": "completed",
                    "print_duration": 3600,
                    "filament_used": 1000,
                    "start_time": 1640995200,  # 2022-01-01
                }
            ]
        }

        with patch("trinetra.moonraker.get_moonraker_history", return_value=mock_history):
            result = self.app.get_moonraker_printing_stats()
            assert result["total_prints"] == 1
            assert result["successful_prints"] == 1
            assert result["print_days"] == 1
