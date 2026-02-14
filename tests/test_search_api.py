"""Integration tests for STL search API behavior and ranking paths."""

import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta

from app import create_app
from trinetra.models import Folder, STLFile


class TestSearchApi:
    """Validate critical /api/stl_files search behavior."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.stl_path = os.path.join(self.temp_dir, "stl_files")
        self.gcode_path = os.path.join(self.temp_dir, "gcode_files")
        os.makedirs(self.stl_path, exist_ok=True)
        os.makedirs(self.gcode_path, exist_ok=True)
        self.app = create_app(
            config_overrides={
                "base_path": self.stl_path,
                "gcode_path": self.gcode_path,
                "log_level": "INFO",
                "search_result_limit": 100,
                "mode": "DEV",
                "library": {
                    "history": {
                        "enabled": True,
                        "ttl_days": 180,
                        "cleanup_trigger": "refresh",
                    }
                },
            }
        )
        self.client = self.app.test_client()

    def teardown_method(self):
        if hasattr(self, "temp_dir") and os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def _write_stl(self, folder_name: str, file_name: str) -> None:
        folder_path = os.path.join(self.stl_path, folder_name)
        os.makedirs(folder_path, exist_ok=True)
        with open(os.path.join(folder_path, file_name), "w", encoding="utf-8") as stl_file:
            stl_file.write("solid test\nendsolid test\n")

    def _reload_index(self) -> None:
        response = self.client.post("/reload_index")
        assert response.status_code == 200

    def test_search_duplicate_filename_returns_multiple_folders(self):
        self._write_stl("alpha_folder", "common_part.stl")
        self._write_stl("beta_folder", "common_part.stl")
        self._reload_index()

        response = self.client.get("/api/stl_files?filter=common_part&per_page=10&page=1")
        assert response.status_code == 200
        payload = json.loads(response.data)
        folder_names = {folder["folder_name"] for folder in payload["folders"]}
        assert {"alpha_folder", "beta_folder"}.issubset(folder_names)

    def test_search_folder_name_match_includes_all_folder_files(self):
        self._write_stl("pegboard-kit", "hook_a.stl")
        self._write_stl("pegboard-kit", "hook_b.stl")
        self._reload_index()

        response = self.client.get("/api/stl_files?filter=pegboard kit&per_page=10&page=1")
        assert response.status_code == 200
        payload = json.loads(response.data)
        folder = next((item for item in payload["folders"] if item["folder_name"] == "pegboard-kit"), None)
        assert folder is not None
        file_names = {item["file_name"] for item in folder["files"]}
        assert file_names == {"hook_a.stl", "hook_b.stl"}

    def test_search_file_match_only_includes_matching_files(self):
        self._write_stl("mixed_models", "peg_hook.stl")
        self._write_stl("mixed_models", "random_cube.stl")
        self._reload_index()

        response = self.client.get("/api/stl_files?filter=peg_hook&per_page=10&page=1")
        assert response.status_code == 200
        payload = json.loads(response.data)
        folder = next((item for item in payload["folders"] if item["folder_name"] == "mixed_models"), None)
        assert folder is not None
        file_names = [item["file_name"] for item in folder["files"]]
        assert file_names == ["peg_hook.stl"]

    def test_search_fallback_path_works_when_fts_unavailable(self):
        self._write_stl("pegboard_fallback", "fallback_hook.stl")
        self._reload_index()
        self.app.config["DB_MANAGER"]._search_index_available = False

        response = self.client.get("/api/stl_files?filter=pegboard&per_page=10&page=1")
        assert response.status_code == 200
        payload = json.loads(response.data)
        folder_names = [folder["folder_name"] for folder in payload["folders"]]
        assert "pegboard_fallback" in folder_names

    def test_search_respects_filter_type_for_search_mode(self):
        self._write_stl("old_models", "peg_old.stl")
        self._write_stl("new_models", "peg_new.stl")
        self._reload_index()

        db_manager = self.app.config["DB_MANAGER"]
        with db_manager.get_session() as session:
            old_folder = session.query(Folder).filter(Folder.name == "old_models").first()
            old_file = (
                session.query(STLFile)
                .join(Folder, Folder.id == STLFile.folder_id)
                .filter(Folder.name == "old_models", STLFile.file_name == "peg_old.stl")
                .first()
            )
            assert old_folder is not None
            assert old_file is not None
            old_time = datetime.utcnow() - timedelta(days=30)
            old_folder.created_at = old_time
            old_file.created_at = old_time
            session.commit()

        response = self.client.get(
            "/api/stl_files?filter=peg&filter_type=today&per_page=10&page=1"
        )
        assert response.status_code == 200
        payload = json.loads(response.data)
        folder_names = [folder["folder_name"] for folder in payload["folders"]]
        assert "new_models" in folder_names
        assert "old_models" not in folder_names
