"""
Comprehensive tests for Flask app routes and functionality
Covers all routes, error cases, and edge conditions
"""

import os
import tempfile
import shutil
import zipfile
import json
import yaml
from unittest.mock import patch, MagicMock, mock_open, Mock
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
            "library": {
                "history": {
                    "enabled": True,
                    "ttl_days": 180,
                    "cleanup_trigger": "refresh",
                }
            },
        }
        self.app = create_app(config_overrides=self.config)
        self.client = self.app.test_client()

    def teardown_method(self):
        """Clean up temporary directories"""
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_single_root_base_path_derives_paths(self):
        """When only base_path is configured, derive models/gcodes/system paths under it."""
        single_root = os.path.join(self.temp_dir, "single-root")
        app = create_app(
            config_overrides={
                "base_path": single_root,
                "log_level": "INFO",
                "search_result_limit": 25,
                "mode": "DEV",
            }
        )

        assert app.config["STL_FILES_PATH"] == os.path.join(os.path.abspath(single_root), "models")
        assert app.config["GCODE_FILES_PATH"] == os.path.join(
            os.path.abspath(single_root), "gcodes"
        )
        assert app.config["DATABASE_PATH"] == os.path.join(
            os.path.abspath(single_root), "system", "trinetra.db"
        )
        assert os.path.isdir(app.config["STL_FILES_PATH"])
        assert os.path.isdir(app.config["GCODE_FILES_PATH"])
        assert os.path.isdir(os.path.dirname(app.config["DATABASE_PATH"]))

    def test_index_route(self):
        """Test the index route"""
        db_manager = self.app.config["DB_MANAGER"]
        with patch.object(db_manager, "get_stl_files_paginated") as mocked_paginated:
            response = self.client.get("/")
        assert response.status_code == 200
        # Check for HTML content instead of specific text
        assert b"<!DOCTYPE html>" in response.data
        mocked_paginated.assert_not_called()

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

    def test_serve_3mf_plate_route(self):
        """Test serving a generated STL for a plate inside a 3MF project."""
        model_xml = """<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model">
      <mesh>
        <vertices>
          <vertex x="0" y="0" z="0"/>
          <vertex x="10" y="0" z="0"/>
          <vertex x="0" y="10" z="0"/>
        </vertices>
        <triangles>
          <triangle v1="0" v2="1" v3="2"/>
        </triangles>
      </mesh>
    </object>
  </resources>
  <build>
    <item objectid="1"/>
  </build>
</model>
"""

        three_mf_file = os.path.join(self.stl_path, "simple.3mf")
        with zipfile.ZipFile(three_mf_file, "w") as archive:
            archive.writestr("3D/3dmodel.model", model_xml)

        response = self.client.get("/3mf_plate?file=simple.3mf&plate=1")
        assert response.status_code == 200
        assert response.mimetype == "model/stl"
        # Binary STL header (80 bytes + 4-byte face count)
        assert len(response.data) > 84

    def test_api_stl_files_includes_three_mf_projects(self):
        """Home API should include 3MF project previews for virtual/root projects."""
        model_xml = """<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model">
      <mesh>
        <vertices>
          <vertex x="0" y="0" z="0"/>
          <vertex x="10" y="0" z="0"/>
          <vertex x="0" y="10" z="0"/>
        </vertices>
        <triangles>
          <triangle v1="0" v2="1" v3="2"/>
        </triangles>
      </mesh>
    </object>
  </resources>
  <build>
    <item objectid="1"/>
  </build>
</model>
"""
        root_three_mf = os.path.join(self.stl_path, "home_preview.3mf")
        with zipfile.ZipFile(root_three_mf, "w") as archive:
            archive.writestr("3D/3dmodel.model", model_xml)

        self.client.post("/reload_index")
        response = self.client.get("/api/stl_files")
        assert response.status_code == 200
        data = json.loads(response.data)
        folders = data.get("folders", [])

        target_folder = None
        for folder in folders:
            if folder.get("folder_name") == "home_preview":
                target_folder = folder
                break

        assert target_folder is not None
        assert "three_mf_projects" in target_folder
        assert len(target_folder["three_mf_projects"]) == 1

    def test_api_stl_files_fuzzy_search_matches_separator_variants(self):
        folder_path = os.path.join(self.stl_path, "pegboard-hooks-us-model_files")
        os.makedirs(folder_path, exist_ok=True)
        with open(os.path.join(folder_path, "F45 Long hook 3IN.STL"), "w", encoding="utf-8") as f:
            f.write("solid test\nendsolid test\n")

        self.client.post("/reload_index")
        response = self.client.get(
            "/api/stl_files?filter=pegboard hooks&per_page=10&page=1&sort_by=folder_name&sort_order=asc"
        )
        assert response.status_code == 200
        payload = json.loads(response.data)
        folder_names = [folder["folder_name"] for folder in payload["folders"]]
        assert "pegboard-hooks-us-model_files" in folder_names

    def test_api_stl_files_fuzzy_search_handles_typo(self):
        folder_path = os.path.join(self.stl_path, "pegboard-hooks-us-model_files")
        os.makedirs(folder_path, exist_ok=True)
        with open(os.path.join(folder_path, "F45 Long hook 2IN.STL"), "w", encoding="utf-8") as f:
            f.write("solid test\nendsolid test\n")

        self.client.post("/reload_index")
        response = self.client.get("/api/stl_files?filter=pegbord&per_page=10&page=1")
        assert response.status_code == 200
        payload = json.loads(response.data)
        folder_names = [folder["folder_name"] for folder in payload["folders"]]
        assert "pegboard-hooks-us-model_files" in folder_names

    def test_api_stl_files_search_pagination_stays_consistent(self):
        for idx in range(7):
            folder_path = os.path.join(self.stl_path, f"pegboard_set_{idx}")
            os.makedirs(folder_path, exist_ok=True)
            with open(os.path.join(folder_path, f"hook_{idx}.stl"), "w", encoding="utf-8") as f:
                f.write("solid test\nendsolid test\n")

        self.client.post("/reload_index")

        page_1_response = self.client.get("/api/stl_files?filter=pegboard&per_page=3&page=1")
        page_2_response = self.client.get("/api/stl_files?filter=pegboard&per_page=3&page=2")

        assert page_1_response.status_code == 200
        assert page_2_response.status_code == 200

        page_1_payload = json.loads(page_1_response.data)
        page_2_payload = json.loads(page_2_response.data)

        assert page_1_payload["pagination"]["total_folders"] == 7
        assert page_1_payload["pagination"]["total_pages"] == 3
        assert len(page_1_payload["folders"]) == 3
        assert len(page_2_payload["folders"]) == 3

        page_1_names = {folder["folder_name"] for folder in page_1_payload["folders"]}
        page_2_names = {folder["folder_name"] for folder in page_2_payload["folders"]}
        assert page_1_names.isdisjoint(page_2_names)

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
        assert data["error"] == "No files selected"

    def test_upload_route_invalid_file_type(self):
        """Test upload route with invalid file type"""
        data = {"file": (BytesIO(b"dummy content"), "test.txt")}
        response = self.client.post("/upload", data=data)
        assert response.status_code == 400
        data = json.loads(response.data)
        assert data["error"] == "Only ZIP, STL, 3MF, and GCODE files are allowed"

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

    def test_upload_route_success_3mf(self):
        """Test successful direct 3MF file upload."""
        data = {"file": (BytesIO(b"dummy 3mf bytes"), "single_model.3mf")}
        response = self.client.post("/upload", data=data)
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload["results"][0]["status"] == "success"
        assert os.path.exists(os.path.join(self.stl_path, "single_model.3mf"))

    def test_upload_route_success_gcode(self):
        """Test successful direct G-code file upload."""
        gcode_bytes = BytesIO(b";FLAVOR:Marlin\nG28 ;Home\n")
        data = {"file": (gcode_bytes, "single_job.gcode")}
        response = self.client.post("/upload", data=data)
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload["results"][0]["status"] == "success"
        assert os.path.exists(os.path.join(self.gcode_path, "single_job.gcode"))

    def test_upload_route_success_stl_creates_folder(self):
        """Direct STL upload should be placed under a folder named after the file base."""
        stl_bytes = BytesIO(b"solid test\nendsolid test\n")
        data = {"file": (stl_bytes, "widget_top.stl")}
        response = self.client.post("/upload", data=data)
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload["results"][0]["status"] == "success"
        assert payload["results"][0]["folder_name"] == "widget_top"
        assert os.path.exists(os.path.join(self.stl_path, "widget_top", "widget_top.stl"))

    def test_upload_route_skips_conflicting_items_but_continues_batch(self):
        """Conflicting names should be skipped individually without failing the whole batch."""
        existing = os.path.join(self.stl_path, "existing_model.3mf")
        with open(existing, "wb") as f:
            f.write(b"existing")

        data = {
            "file": [
                (BytesIO(b"new bytes"), "existing_model.3mf"),
                (BytesIO(b";FLAVOR:Marlin\nG28 ;Home\n"), "new_job.gcode"),
            ]
        }
        response = self.client.post("/upload", data=data)
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert len(payload["results"]) == 2
        assert payload["results"][0]["status"] == "skipped"
        assert payload["results"][1]["status"] == "success"
        assert os.path.exists(os.path.join(self.gcode_path, "new_job.gcode"))

    def test_upload_route_conflict_check_for_3mf(self):
        """Conflict check should detect existing 3MF file names."""
        existing = os.path.join(self.stl_path, "existing_model.3mf")
        with open(existing, "wb") as f:
            f.write(b"dummy")

        data = {
            "file": (BytesIO(b"new dummy"), "existing_model.3mf"),
            "conflict_action": "check",
        }
        response = self.client.post("/upload", data=data)
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload.get("ask_user") is True
        assert "existing_model.3mf" in payload.get("conflicts", [])

    def test_upload_route_triggers_single_reload_after_mixed_batch(self):
        """A mixed upload batch should trigger one DB reload after all processing."""
        zip_data = BytesIO()
        with zipfile.ZipFile(zip_data, "w") as zipf:
            zipf.writestr("inside.stl", "solid test\nendsolid test\n")
        zip_data.seek(0)

        data = {
            "file": [
                (zip_data, "mixed_pack.zip"),
                (BytesIO(b"dummy 3mf"), "mixed_model.3mf"),
                (BytesIO(b";FLAVOR:Marlin\nG28 ;Home\n"), "mixed_job.gcode"),
            ]
        }

        with patch.object(
            self.app.config["DB_MANAGER"],
            "reload_index",
            return_value={"folders": 1, "stl_files": 1, "gcode_files": 1},
        ) as mock_reload:
            response = self.client.post("/upload", data=data)

        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload.get("index_refresh", {}).get("success") is True
        mock_reload.assert_called_once()

    def test_upload_route_refresh_index_false_skips_reload(self):
        """When refresh_index is false, upload should not trigger reload_index."""
        data = {
            "file": (BytesIO(b"dummy 3mf bytes"), "no_refresh.3mf"),
            "refresh_index": "false",
        }
        with patch.object(self.app.config["DB_MANAGER"], "reload_index") as mock_reload:
            response = self.client.post("/upload", data=data)

        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload.get("index_refresh", {}).get("success") is True
        assert payload.get("index_refresh", {}).get("skipped") is True
        mock_reload.assert_not_called()

    def test_upload_route_reload_failure_does_not_fail_upload(self):
        """Upload result should still return success even if post-upload reload fails."""
        data = {"file": (BytesIO(b"dummy 3mf bytes"), "reload_fail.3mf")}
        with patch.object(
            self.app.config["DB_MANAGER"], "reload_index", side_effect=RuntimeError("reload failed")
        ) as mock_reload:
            response = self.client.post("/upload", data=data)

        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload.get("index_refresh", {}).get("success") is False
        assert "reload failed" in payload.get("index_refresh", {}).get("error", "")
        mock_reload.assert_called_once()

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

    def test_reload_index_stats_mode_skips_filesystem_reindex(self):
        with patch.object(self.app.config["DB_MANAGER"], "reload_index") as mock_reload:
            response = self.client.post("/reload_index?mode=stats")
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        mock_reload.assert_not_called()

    def test_reload_index_files_mode_skips_integration_stats(self):
        with patch.object(self.app.config["DB_MANAGER"], "reload_index", return_value={}) as mock_reload:
            with patch.object(
                self.app.config["DB_MANAGER"], "reload_moonraker_only"
            ) as mock_moonraker_reload:
                response = self.client.post("/reload_index?mode=files")

        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        mock_reload.assert_called_once_with(
            self.app.config["STL_FILES_PATH"], self.app.config["GCODE_FILES_PATH"]
        )
        mock_moonraker_reload.assert_not_called()

    def test_reload_index_failure_preserves_existing_catalog_data(self):
        """A failed reload should not wipe already indexed rows."""
        folder_path = os.path.join(self.stl_path, "persist_me")
        os.makedirs(folder_path, exist_ok=True)
        with open(os.path.join(folder_path, "fixture.stl"), "w", encoding="utf-8") as f:
            f.write("solid fixture\nendsolid fixture\n")

        initial_reload = self.client.post("/reload_index?mode=files")
        assert initial_reload.status_code == 200

        before = self.client.get("/api/stl_files")
        assert before.status_code == 200
        before_payload = json.loads(before.data)
        before_names = {folder["folder_name"] for folder in before_payload.get("folders", [])}
        assert "persist_me" in before_names

        with patch.object(
            self.app.config["DB_MANAGER"],
            "_process_stl_base_path",
            side_effect=RuntimeError("forced reload failure"),
        ):
            failed_reload = self.client.post("/reload_index?mode=files")

        assert failed_reload.status_code == 500
        failed_payload = json.loads(failed_reload.data)
        assert failed_payload["success"] is False

        after = self.client.get("/api/stl_files")
        assert after.status_code == 200
        after_payload = json.loads(after.data)
        after_names = {folder["folder_name"] for folder in after_payload.get("folders", [])}
        assert "persist_me" in after_names

    def test_reload_index_rejects_invalid_mode(self):
        response = self.client.post("/reload_index?mode=invalid")
        assert response.status_code == 400
        payload = json.loads(response.data)
        assert payload["success"] is False

    def test_settings_route(self):
        """Settings page should render successfully."""
        response = self.client.get("/settings")
        assert response.status_code == 200
        assert b"Settings" in response.data
        assert b"Library History" in response.data
        assert b"Integrations" in response.data

    def test_api_settings_printer_volume_get(self):
        """Settings API should return current/default printer volume."""
        response = self.client.get("/api/settings/printer_volume")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        assert "printer_volume" in data
        assert "x" in data["printer_volume"]
        assert "y" in data["printer_volume"]
        assert "z" in data["printer_volume"]

    def test_api_settings_printer_volume_post_updates_config_file(self):
        """Settings updates should persist in the config file used to start the app."""
        temp_config_path = os.path.join(self.temp_dir, "settings_config.yaml")
        temp_base_path = os.path.join(self.temp_dir, "settings_data")
        with open(temp_config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "base_path": temp_base_path,
                    "moonraker_url": "",
                    "log_level": "INFO",
                    "mode": "DEV",
                    "search_result_limit": 25,
                },
                f,
                sort_keys=False,
            )

        settings_app = create_app(config_file=temp_config_path)
        settings_client = settings_app.test_client()

        response = settings_client.post(
            "/api/settings/printer_volume", json={"preset_id": "bambu_x1_p1"}
        )
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload["printer_volume"]["x"] == 256.0
        assert payload["printer_volume"]["y"] == 256.0
        assert payload["printer_volume"]["z"] == 256.0

        with open(temp_config_path, "r", encoding="utf-8") as f:
            saved_config = yaml.safe_load(f) or {}
        assert saved_config["printer_profile"] == "bambu_x1_p1"
        assert saved_config["printer_volume"]["x"] == 256.0
        assert saved_config["printer_volume"]["y"] == 256.0
        assert saved_config["printer_volume"]["z"] == 256.0

    def test_api_settings_printer_volume_post_invalid_values(self):
        """Settings API should reject invalid manual volume values."""
        response = self.client.post(
            "/api/settings/printer_volume",
            json={"x": -1, "y": 220, "z": 220},
        )
        assert response.status_code == 400
        payload = json.loads(response.data)
        assert payload["success"] is False

    def test_api_settings_library_history_get_defaults(self):
        response = self.client.get("/api/settings/library/history")
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload["history"]["enabled"] is True
        assert payload["history"]["ttl_days"] == 180

    def test_api_settings_library_history_post_updates_config(self):
        temp_config_path = os.path.join(self.temp_dir, "library_config.yaml")
        temp_base_path = os.path.join(self.temp_dir, "library_data")
        with open(temp_config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "base_path": temp_base_path,
                    "log_level": "INFO",
                    "mode": "DEV",
                    "search_result_limit": 25,
                },
                f,
                sort_keys=False,
            )

        library_app = create_app(config_file=temp_config_path)
        library_client = library_app.test_client()

        response = library_client.post(
            "/api/settings/library/history",
            json={"enabled": True, "ttl_days": 90, "cleanup_trigger": "refresh"},
        )
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload["history"]["ttl_days"] == 90

        with open(temp_config_path, "r", encoding="utf-8") as f:
            saved_config = yaml.safe_load(f) or {}
        assert saved_config["library"]["history"]["enabled"] is True
        assert saved_config["library"]["history"]["ttl_days"] == 90
        assert saved_config["library"]["history"]["cleanup_trigger"] == "refresh"

    def test_api_settings_bambu_get_default_disabled(self):
        temp_config_path = os.path.join(self.temp_dir, "bambu_default_config.yaml")
        temp_base_path = os.path.join(self.temp_dir, "bambu_default_data")
        with open(temp_config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "base_path": temp_base_path,
                    "log_level": "INFO",
                    "mode": "DEV",
                    "search_result_limit": 25,
                },
                f,
                sort_keys=False,
            )

        default_app = create_app(config_file=temp_config_path)
        default_client = default_app.test_client()

        response = default_client.get("/api/settings/integrations/bambu")
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        integration = payload["integration"]
        assert integration["id"] == "bambu"
        assert integration["enabled"] is False

    def test_api_settings_bambu_post_updates_config(self):
        temp_config_path = os.path.join(self.temp_dir, "bambu_integration_config.yaml")
        temp_base_path = os.path.join(self.temp_dir, "bambu_integration_data")
        with open(temp_config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "base_path": temp_base_path,
                    "moonraker_url": "",
                    "log_level": "INFO",
                    "mode": "DEV",
                    "search_result_limit": 25,
                },
                f,
                sort_keys=False,
            )

        integration_app = create_app(config_file=temp_config_path)
        integration_client = integration_app.test_client()

        response = integration_client.post(
            "/api/settings/integrations/bambu",
            json={
                "enabled": True,
                "mode": "cloud",
                "region": "global",
                "access_token": "read-token",
                "refresh_token": "refresh-token",
            },
        )
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload["integration"]["enabled"] is True
        assert payload["integration"]["settings"]["mode"] == "cloud"

        with open(temp_config_path, "r", encoding="utf-8") as f:
            saved_config = yaml.safe_load(f) or {}
        assert saved_config["integrations"]["bambu"]["enabled"] is True
        assert saved_config["integrations"]["bambu"]["mode"] == "cloud"
        assert saved_config["integrations"]["bambu"]["cloud"]["access_token"] == "read-token"
        assert saved_config["integrations"]["bambu"]["cloud"]["refresh_token"] == "refresh-token"

    def test_api_settings_moonraker_get_default_disabled(self):
        response = self.client.get("/api/settings/integrations/moonraker")
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        integration = payload["integration"]
        assert integration["id"] == "moonraker"
        assert integration["enabled"] is False

    def test_api_settings_moonraker_post_updates_config(self):
        temp_config_path = os.path.join(self.temp_dir, "integration_config.yaml")
        temp_base_path = os.path.join(self.temp_dir, "integration_data")
        with open(temp_config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                {
                    "base_path": temp_base_path,
                    "moonraker_url": "",
                    "log_level": "INFO",
                    "mode": "DEV",
                    "search_result_limit": 25,
                },
                f,
                sort_keys=False,
            )

        integration_app = create_app(config_file=temp_config_path)
        integration_client = integration_app.test_client()

        response = integration_client.post(
            "/api/settings/integrations/moonraker",
            json={"enabled": True, "base_url": "http://localhost:7125"},
        )
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload["success"] is True
        assert payload["integration"]["enabled"] is True
        assert payload["integration"]["settings"]["base_url"] == "http://localhost:7125"

        with open(temp_config_path, "r", encoding="utf-8") as f:
            saved_config = yaml.safe_load(f) or {}
        assert saved_config["moonraker_url"] == "http://localhost:7125"
        assert saved_config["integrations"]["moonraker"]["enabled"] is True
        assert saved_config["integrations"]["moonraker"]["base_url"] == "http://localhost:7125"

    def test_api_add_to_queue_success(self):
        mock_integration = Mock()
        mock_integration.is_enabled.return_value = True
        mock_integration.is_configured.return_value = True
        mock_integration.queue_jobs.return_value = True

        with patch("app.get_printer_integration", return_value=mock_integration):
            response = self.client.post(
                "/api/add_to_queue", json={"filenames": ["test.gcode"], "reset": False}
            )
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data["result"] == "ok"

    def test_api_add_to_queue_failure(self):
        mock_integration = Mock()
        mock_integration.is_enabled.return_value = True
        mock_integration.is_configured.return_value = True
        mock_integration.queue_jobs.return_value = False

        with patch("app.get_printer_integration", return_value=mock_integration):
            response = self.client.post(
                "/api/add_to_queue", json={"filenames": ["test.gcode"], "reset": False}
            )
            assert response.status_code == 502
            data = json.loads(response.data)
            assert "error" in data

    def test_api_add_to_queue_disabled_integration(self):
        mock_integration = Mock()
        mock_integration.is_enabled.return_value = False
        mock_integration.is_configured.return_value = True

        with patch("app.get_printer_integration", return_value=mock_integration):
            response = self.client.post(
                "/api/add_to_queue", json={"filenames": ["test.gcode"], "reset": False}
            )
            assert response.status_code == 400
            data = json.loads(response.data)
            assert "disabled" in data["error"].lower()

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
        assert self.app.allowed_file("test.stl") is True
        assert self.app.allowed_file("test.3mf") is True
        assert self.app.allowed_file("test.gcode") is True
        assert self.app.allowed_file("test.txt") is False

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
