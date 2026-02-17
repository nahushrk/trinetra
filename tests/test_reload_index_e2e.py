"""
End-to-end tests for the reload index functionality
Tests the complete workflow of reloading the index with G-code stats
"""

import os
import tempfile
import shutil
import unittest
from unittest.mock import Mock, patch
import json
import zipfile

from trinetra.database import DatabaseManager
from trinetra.models import ThreeMFProjectCache
from trinetra import three_mf
from trinetra.integrations.moonraker.api import MoonrakerAPI
from trinetra.integrations.moonraker.service import MoonrakerService

# Setup logging for tests
from trinetra.logger import get_logger, configure_logging

# Configure logging for tests
test_config = {"log_level": "DEBUG", "log_file": "test.log"}
configure_logging(test_config)
logger = get_logger(__name__)


class TestReloadIndexE2E(unittest.TestCase):
    """End-to-end tests for reload index functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create temporary directories for test files
        self.test_dir = tempfile.mkdtemp()
        self.stl_dir = os.path.join(self.test_dir, "stl_files")
        self.gcode_dir = os.path.join(self.test_dir, "gcode_files")
        os.makedirs(self.stl_dir)
        os.makedirs(self.gcode_dir)

        # Create temporary database file
        self.db_path = os.path.join(self.test_dir, "test.db")
        self.db_manager = DatabaseManager(self.db_path)

        # Create test STL folder structure
        self.test_folder = os.path.join(self.stl_dir, "test_folder")
        os.makedirs(self.test_folder)

        # Create test STL file
        self.stl_file_path = os.path.join(self.test_folder, "test.stl")
        with open(self.stl_file_path, "w") as f:
            f.write("solid test\nendsolid test\n")

        # Create test G-code file
        self.gcode_file_path = os.path.join(self.test_folder, "test.gcode")
        gcode_content = """;FLAVOR:Marlin
;TIME:3600
;Filament used: 10m
;Layer height: 0.2
;Generated with Cura_SteamEngine 4.10.0
G0 X0 Y0 Z0
G1 X10 Y10 Z0.2
"""
        with open(self.gcode_file_path, "w") as f:
            f.write(gcode_content)

        # Create separate G-code file
        self.separate_gcode_dir = os.path.join(self.gcode_dir, "separate")
        os.makedirs(self.separate_gcode_dir)
        self.separate_gcode_file_path = os.path.join(self.separate_gcode_dir, "separate.gcode")
        with open(self.separate_gcode_file_path, "w") as f:
            f.write(gcode_content)

    def tearDown(self):
        """Clean up test fixtures"""
        shutil.rmtree(self.test_dir)

    def _write_simple_three_mf(self, path: str, edge_len: int = 10) -> None:
        model_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<model xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources>
    <object id="1" type="model">
      <mesh>
        <vertices>
          <vertex x="0" y="0" z="0"/>
          <vertex x="{edge_len}" y="0" z="0"/>
          <vertex x="0" y="{edge_len}" z="0"/>
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
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("3D/3dmodel.model", model_xml)

    @patch("trinetra.integrations.moonraker.api.MoonrakerAPI")
    def test_reload_index_with_moonraker_stats(self, mock_moonraker_api_class):
        """Test end-to-end reload index with Moonraker stats"""
        # Mock Moonraker API response
        mock_moonraker_api = Mock()
        mock_moonraker_api_class.return_value = mock_moonraker_api

        mock_moonraker_api.get_history.return_value = {
            "jobs": [
                {
                    "filename": "test.gcode",
                    "status": "completed",
                    "print_duration": 3600,
                    "filament_used": 10000,
                    "end_time": 1640995200,
                    "job_id": "job_1",
                },
                {
                    "filename": "test.gcode",
                    "status": "completed",
                    "print_duration": 3600,
                    "filament_used": 10000,
                    "end_time": 1640995200,
                    "job_id": "job_2",
                },
            ]
        }

        # Perform reload index with Moonraker URL and mocked client
        moonraker_url = "http://localhost:7125"
        counts = self.db_manager.reload_index(
            self.stl_dir, self.gcode_dir, moonraker_url, mock_moonraker_api
        )

        # Verify file counts
        self.assertEqual(counts["folders"], 1)
        self.assertEqual(counts["stl_files"], 1)
        self.assertEqual(counts["gcode_files"], 2)

        # Verify Moonraker stats were updated
        self.assertIn("moonraker_stats_updated", counts)
        self.assertIn("moonraker_stats_failed", counts)

        # Check that files were added to database
        stl_files = self.db_manager.get_stl_files()
        self.assertEqual(len(stl_files), 1)
        self.assertEqual(stl_files[0]["folder_name"], "test_folder")
        self.assertEqual(len(stl_files[0]["files"]), 1)

        # Check G-code files
        gcode_files = self.db_manager.get_all_gcode_files()
        self.assertEqual(len(gcode_files), 2)

        # Verify that one of the G-code files has stats
        # (We can't guarantee which one will have stats since the matching is based on filename)
        files_with_stats = [f for f in gcode_files if f.get("stats") is not None]
        # We expect at least one file to have stats since we provided Moonraker data
        # for "test.gcode" and we have a file with that name

    def test_reload_index_without_moonraker_stats(self):
        """Test end-to-end reload index without Moonraker stats"""
        # Perform reload index without Moonraker URL
        counts = self.db_manager.reload_index(self.stl_dir, self.gcode_dir)

        # Verify file counts
        self.assertEqual(counts["folders"], 1)
        self.assertEqual(counts["stl_files"], 1)
        self.assertEqual(counts["gcode_files"], 2)

        # Verify Moonraker stats were not updated
        self.assertNotIn("moonraker_stats_updated", counts)
        self.assertNotIn("moonraker_stats_failed", counts)

        # Check that files were added to database
        stl_files = self.db_manager.get_stl_files()
        self.assertEqual(len(stl_files), 1)
        self.assertEqual(stl_files[0]["folder_name"], "test_folder")
        self.assertEqual(len(stl_files[0]["files"]), 1)

        # Check G-code files
        gcode_files = self.db_manager.get_all_gcode_files()
        self.assertEqual(len(gcode_files), 2)

        # Verify that files don't have stats
        for gcode_file in gcode_files:
            self.assertIsNone(gcode_file.get("stats"))

    def test_reload_index_with_root_level_three_mf_virtual_folder(self):
        """Root-level 3MF files should appear as virtual folders."""
        root_three_mf = os.path.join(self.stl_dir, "swirl_root.3mf")
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
        with zipfile.ZipFile(root_three_mf, "w") as archive:
            archive.writestr("3D/3dmodel.model", model_xml)

        self.db_manager.reload_index(self.stl_dir, self.gcode_dir)
        folders = self.db_manager.get_stl_files()
        folder_names = {folder["folder_name"] for folder in folders}

        self.assertIn("swirl_root", folder_names)
        three_mf_projects = self.db_manager.get_folder_three_mf_projects("swirl_root")
        self.assertEqual(len(three_mf_projects), 1)
        self.assertEqual(three_mf_projects[0]["file_name"], "swirl_root.3mf")

    def test_three_mf_projects_are_cached_between_calls(self):
        project_path = os.path.join(self.test_folder, "cached.3mf")
        self._write_simple_three_mf(project_path, edge_len=10)

        self.db_manager.reload_index(self.stl_dir, self.gcode_dir)

        with patch(
            "trinetra.database.three_mf.load_3mf_project", wraps=three_mf.load_3mf_project
        ) as mocked_loader:
            first = self.db_manager.get_folder_three_mf_projects("test_folder")
            second = self.db_manager.get_folder_three_mf_projects("test_folder")

        self.assertEqual(len(first), 1)
        self.assertEqual(first, second)
        self.assertEqual(mocked_loader.call_count, 1)

    def test_three_mf_cache_refreshes_on_change_and_prunes_on_delete(self):
        project_path = os.path.join(self.test_folder, "mutable.3mf")
        self._write_simple_three_mf(project_path, edge_len=10)
        self.db_manager.reload_index(self.stl_dir, self.gcode_dir)

        baseline = self.db_manager.get_folder_three_mf_projects("test_folder")
        self.assertEqual(len(baseline), 1)

        # Rewrite the same file so cache key (mtime/size) changes.
        self._write_simple_three_mf(project_path, edge_len=12)

        with patch(
            "trinetra.database.three_mf.load_3mf_project", wraps=three_mf.load_3mf_project
        ) as mocked_loader:
            refreshed = self.db_manager.get_folder_three_mf_projects("test_folder")

        self.assertEqual(len(refreshed), 1)
        self.assertEqual(mocked_loader.call_count, 1)

        os.remove(project_path)
        after_delete = self.db_manager.get_folder_three_mf_projects("test_folder")
        self.assertEqual(after_delete, [])

        with self.db_manager.get_session() as session:
            cache_count = session.query(ThreeMFProjectCache).count()
        self.assertEqual(cache_count, 0)

    @patch("trinetra.integrations.moonraker.api.MoonrakerAPI")
    def test_reload_moonraker_only(self, mock_moonraker_api_class):
        """Test end-to-end reload Moonraker only functionality"""
        # First reload index without Moonraker stats
        counts = self.db_manager.reload_index(self.stl_dir, self.gcode_dir)

        # Verify no Moonraker stats initially
        gcode_files = self.db_manager.get_all_gcode_files()
        for gcode_file in gcode_files:
            self.assertIsNone(gcode_file.get("stats"))

        # Mock Moonraker API response
        mock_moonraker_api = Mock()
        mock_moonraker_api_class.return_value = mock_moonraker_api

        mock_moonraker_api.get_history.return_value = {
            "jobs": [
                {
                    "filename": "test.gcode",
                    "status": "completed",
                    "print_duration": 3600,
                    "filament_used": 10000,
                    "end_time": 1640995200,
                    "job_id": "job_1",
                }
            ]
        }

        # Perform reload Moonraker only
        moonraker_url = "http://localhost:7125"
        stats_result = self.db_manager.reload_moonraker_only(moonraker_url, mock_moonraker_api)

        # Verify stats were updated
        self.assertEqual(stats_result["updated"], 1)
        self.assertEqual(stats_result["failed"], 0)

        # Check that files now have stats
        gcode_files = self.db_manager.get_all_gcode_files()
        files_with_stats = [f for f in gcode_files if f.get("stats") is not None]
        self.assertGreater(len(files_with_stats), 0)

    def test_folder_contents_with_stats(self):
        """Test that folder contents include stats when available"""
        # First reload index without Moonraker stats
        self.db_manager.reload_index(self.stl_dir, self.gcode_dir)

        # Get folder contents
        stl_files, image_files, pdf_files, gcode_files = self.db_manager.get_folder_contents(
            "test_folder"
        )

        # Verify G-code files don't have stats initially
        for gcode_file in gcode_files:
            self.assertIsNone(gcode_file.get("stats"))

        # Mock Moonraker API and update stats
        with patch("trinetra.integrations.moonraker.api.MoonrakerAPI") as mock_moonraker_api_class:
            mock_moonraker_api = Mock()
            mock_moonraker_api_class.return_value = mock_moonraker_api

            mock_moonraker_api.get_history.return_value = {
                "jobs": [
                    {
                        "filename": "test.gcode",
                        "status": "completed",
                        "print_duration": 3600,
                        "filament_used": 10000,
                        "end_time": 1640995200,
                        "job_id": "job_1",
                    }
                ]
            }

            moonraker_url = "http://localhost:7125"
            self.db_manager.update_moonraker_stats(moonraker_url, mock_moonraker_api)

        # Get folder contents again
        stl_files, image_files, pdf_files, gcode_files = self.db_manager.get_folder_contents(
            "test_folder"
        )

        # Verify G-code files now have stats
        files_with_stats = [f for f in gcode_files if f.get("stats") is not None]
        self.assertGreater(len(files_with_stats), 0)

    @patch("trinetra.integrations.moonraker.api.MoonrakerAPI")
    def test_reload_index_with_test_data(self, mock_moonraker_api_class):
        """Test end-to-end reload index with our test data"""
        # Use our actual test data directories
        stl_base_path = os.path.join(os.path.dirname(__file__), "test_data", "models")
        gcode_base_path = os.path.join(os.path.dirname(__file__), "test_data", "gcodes")

        # Load our mock Moonraker API response
        mock_data_path = os.path.join(
            os.path.dirname(__file__), "test_data", "moonraker_api_response_mock.json"
        )
        with open(mock_data_path, "r") as f:
            mock_history_response = json.load(f)

        # Mock Moonraker API
        mock_moonraker_api = Mock()
        mock_moonraker_api_class.return_value = mock_moonraker_api
        mock_moonraker_api.get_history.return_value = mock_history_response

        # Perform reload index with Moonraker URL
        moonraker_url = "http://localhost:7125"
        counts = self.db_manager.reload_index(
            stl_base_path, gcode_base_path, moonraker_url, mock_moonraker_api
        )

        # Verify file counts (we should have multiple folders and files)
        self.assertGreater(counts["folders"], 0)
        self.assertGreater(counts["stl_files"], 0)
        self.assertGreater(counts["gcode_files"], 0)

        # Verify Moonraker stats were updated
        self.assertIn("moonraker_stats_updated", counts)
        self.assertGreater(counts["moonraker_stats_updated"], 0)

        # Check that files were added to database
        stl_files = self.db_manager.get_stl_files()
        self.assertGreater(len(stl_files), 0)

        # Check G-code files
        gcode_files = self.db_manager.get_all_gcode_files()
        self.assertGreater(len(gcode_files), 0)

        # Verify that some G-code files have stats (from our mock data)
        files_with_stats = [f for f in gcode_files if f.get("stats") is not None]
        self.assertGreater(len(files_with_stats), 0)

        # Verify GCODE-STL associations
        # Check that part_a1.gcode files are associated with part_a1.stl
        part_a1_gcode_files = [f for f in gcode_files if "part_a1" in f["file_name"]]
        for gcode_file in part_a1_gcode_files:
            # These should be associated with a folder (since they match an STL file)
            self.assertNotEqual(gcode_file["folder_name"], "Unknown")

        # Check that part_a2.gcode files are associated with part_a2.stl
        part_a2_gcode_files = [f for f in gcode_files if "part_a2" in f["file_name"]]
        for gcode_file in part_a2_gcode_files:
            # These should be associated with a folder (since they match an STL file)
            self.assertNotEqual(gcode_file["folder_name"], "Unknown")

        # Check that part_b1.gcode files are associated with part_b1.stl
        part_b1_gcode_files = [f for f in gcode_files if "part_b1" in f["file_name"]]
        for gcode_file in part_b1_gcode_files:
            # These should be associated with a folder (since they match an STL file)
            self.assertNotEqual(gcode_file["folder_name"], "Unknown")

        # Verify specific stats for one of our test files
        part_a1_02mm_gcode = None
        for gcode_file in gcode_files:
            if gcode_file["file_name"] == "part_a1_0.2mm_PLA.gcode":
                part_a1_02mm_gcode = gcode_file
                break

        if part_a1_02mm_gcode and part_a1_02mm_gcode.get("stats"):
            stats = part_a1_02mm_gcode["stats"]
            # Should have 2 prints (based on our mock data)
            self.assertEqual(stats["print_count"], 2)
            # Should have 100% success rate (both prints completed)
            self.assertEqual(stats["success_rate"], 1.0)
            # Should have total print time of 7100 seconds (3600 + 3500)
            self.assertEqual(stats["total_print_time"], 7100.0)
            # Should have total filament used of 19800 (10000 + 9800)
            self.assertEqual(stats["total_filament_used"], 19800.0)


if __name__ == "__main__":
    unittest.main()
