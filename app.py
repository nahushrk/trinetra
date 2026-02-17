import io
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timedelta

import yaml
from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    send_from_directory,
)
from flask_compress import Compress
from werkzeug.utils import secure_filename

from trinetra import gcode_handler, search
from trinetra import three_mf
from trinetra.database import DatabaseManager
from trinetra.config_paths import resolve_storage_paths
from trinetra.integrations.registry import get_printer_integration, list_printer_integrations

# Import logging configuration from trinetra package
from trinetra.logger import get_logger, configure_logging

# Global logger - will be configured after config is loaded
logger = None

DEFAULT_PRINTER_VOLUME = {"x": 220.0, "y": 220.0, "z": 270.0}
DEFAULT_LIBRARY_HISTORY_SETTINGS = {
    "enabled": True,
    "ttl_days": 180,
    "cleanup_trigger": "refresh",
}
DEFAULT_STL_SORT_BY = "created_at"
DEFAULT_STL_SORT_ORDER = "desc"
POPULAR_PRINTERS = [
    {"id": "bambu_a1_mini", "name": "Bambu Lab A1 mini", "x": 180, "y": 180, "z": 180},
    {"id": "bambu_a1", "name": "Bambu Lab A1", "x": 256, "y": 256, "z": 256},
    {"id": "bambu_x1_p1", "name": "Bambu Lab X1 / P1 Series", "x": 256, "y": 256, "z": 256},
    {"id": "prusa_mk4", "name": "Prusa MK4 / MK3S+", "x": 250, "y": 210, "z": 220},
    {"id": "ender3_v2", "name": "Creality Ender 3 V2", "x": 220, "y": 220, "z": 250},
]


def safe_join(base, *paths):
    """Safely join one or more path components to a base path to prevent directory traversal."""
    base_path = os.path.abspath(base)
    final_path = os.path.abspath(os.path.join(base, *paths))
    if not final_path.startswith(base_path + os.sep):
        raise Exception("Attempted Path Traversal")
    return final_path


def load_config(yaml_file=None):
    """Loads configuration from a YAML file."""
    if not yaml_file:
        yaml_file = os.getenv("CONFIG_FILE", "config_dev.yaml")  # Default config file name

    try:
        with open(yaml_file) as file:
            config = yaml.safe_load(file)
            return config or {}
    except Exception as e:
        # Use basic logging here since logger might not be configured yet
        print(f"Error loading configuration file: {e}")
        return {}


def create_app(config_file=None, config_overrides=None):
    active_config_file = config_file or os.getenv("CONFIG_FILE", "config_dev.yaml")
    config = load_config(active_config_file)
    if config_overrides:
        config.update(config_overrides)

    # Configure logging first using config
    configure_logging(config)

    # Now get logger after configuration
    global logger
    logger = get_logger(__name__)

    app = Flask(__name__)
    Compress(app)

    # Set up config in app.config
    for k, v in config.items():
        app.config[k.upper()] = v
    app.config["CONFIG_FILE_PATH"] = os.path.abspath(active_config_file)

    # Set Flask app logger level from config
    log_level = config.get("log_level")
    if log_level:
        app.logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    logger.info(f"Config: {config}")

    # Set up storage paths (legacy two-path mode and single-root mode are both supported)
    stl_files_path, gcode_files_path, db_path = resolve_storage_paths(config)
    os.makedirs(stl_files_path, exist_ok=True)
    os.makedirs(gcode_files_path, exist_ok=True)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    app.config["STL_FILES_PATH"] = stl_files_path
    app.config["GCODE_FILES_PATH"] = gcode_files_path

    # Initialize database manager
    app.config["DATABASE_PATH"] = db_path
    db_manager = DatabaseManager(db_path)
    db_manager.stl_base_path = stl_files_path
    db_manager.gcode_base_path = gcode_files_path
    app.config["DB_MANAGER"] = db_manager

    def _coerce_positive_float(value):
        try:
            parsed = float(value)
            if parsed <= 0:
                return None
            return parsed
        except (TypeError, ValueError):
            return None

    def _coerce_non_negative_int(value):
        try:
            parsed = int(value)
            if parsed < 0:
                return None
            return parsed
        except (TypeError, ValueError):
            return None

    def get_current_printer_volume():
        raw = app.config.get("PRINTER_VOLUME", {})
        if not isinstance(raw, dict):
            raw = {}

        x = _coerce_positive_float(raw.get("x"))
        y = _coerce_positive_float(raw.get("y"))
        z = _coerce_positive_float(raw.get("z"))
        return {
            "x": x if x is not None else DEFAULT_PRINTER_VOLUME["x"],
            "y": y if y is not None else DEFAULT_PRINTER_VOLUME["y"],
            "z": z if z is not None else DEFAULT_PRINTER_VOLUME["z"],
        }

    def write_config_updates(updates: dict):
        config_path = app.config.get("CONFIG_FILE_PATH")
        if not config_path:
            raise ValueError("Config file path is not set")

        current_config = load_config(config_path)
        current_config.update(updates)

        with open(config_path, "w", encoding="utf-8") as file:
            yaml.safe_dump(current_config, file, sort_keys=False)

        for key, value in updates.items():
            app.config[key.upper()] = value

    def get_library_history_settings() -> dict:
        raw_library = app.config.get("LIBRARY", {})
        if not isinstance(raw_library, dict):
            raw_library = {}
        raw_history = raw_library.get("history", {})
        if not isinstance(raw_history, dict):
            raw_history = {}

        enabled = bool(raw_history.get("enabled", DEFAULT_LIBRARY_HISTORY_SETTINGS["enabled"]))
        ttl_days = _coerce_non_negative_int(raw_history.get("ttl_days"))
        if ttl_days is None:
            ttl_days = DEFAULT_LIBRARY_HISTORY_SETTINGS["ttl_days"]
        cleanup_trigger = str(
            raw_history.get("cleanup_trigger", DEFAULT_LIBRARY_HISTORY_SETTINGS["cleanup_trigger"])
        ).strip().lower() or DEFAULT_LIBRARY_HISTORY_SETTINGS["cleanup_trigger"]

        return {
            "enabled": enabled,
            "ttl_days": ttl_days,
            "cleanup_trigger": cleanup_trigger,
        }

    def get_runtime_integration_config() -> dict:
        integrations = app.config.get("INTEGRATIONS", {})
        if not isinstance(integrations, dict):
            integrations = {}
        return {
            "integrations": integrations,
            "moonraker_url": app.config.get("MOONRAKER_URL", ""),
            "library": {"history": get_library_history_settings()},
        }

    def get_moonraker_integration_state() -> dict:
        integration = get_printer_integration("moonraker")
        if integration is None:
            return {
                "id": "moonraker",
                "name": "Moonraker",
                "description": "Unavailable",
                "enabled": False,
                "configured": False,
                "settings": {"base_url": ""},
            }
        return integration.get_ui_state(get_runtime_integration_config())

    def get_enabled_moonraker_url() -> str | None:
        state = get_moonraker_integration_state()
        if not state.get("enabled"):
            return None
        base_url = (state.get("settings") or {}).get("base_url", "")
        if not base_url:
            return None
        return str(base_url)

    def get_enabled_moonraker_client():
        integration = get_printer_integration("moonraker")
        if integration is None:
            return None
        return integration.create_client(get_runtime_integration_config())

    def get_bambu_integration_state() -> dict:
        integration = get_printer_integration("bambu")
        if integration is None:
            return {
                "id": "bambu",
                "name": "Bambu Lab",
                "description": "Unavailable",
                "enabled": False,
                "configured": False,
                "settings": {"mode": "cloud", "access_token": "", "refresh_token": "", "region": "global"},
            }
        return integration.get_ui_state(get_runtime_integration_config())

    def sync_bambu_history(*, cleanup_expired: bool) -> dict:
        runtime_config = get_runtime_integration_config()
        history_settings = get_library_history_settings()
        if not history_settings.get("enabled"):
            return {"skipped": 1, "reason": "history disabled"}

        integration = get_printer_integration("bambu")
        if integration is None or not integration.is_enabled(runtime_config):
            return {"skipped": 1, "reason": "bambu disabled"}
        if not integration.is_configured(runtime_config):
            return {"skipped": 1, "reason": "bambu not configured"}

        fetch_history_events = getattr(integration, "fetch_history_events", None)
        if not callable(fetch_history_events):
            return {"skipped": 1, "reason": "integration does not expose history fetch"}

        events = fetch_history_events(runtime_config, limit=500)
        settings = integration.get_settings(runtime_config)
        mode = getattr(settings, "mode", "cloud")
        ttl_days = history_settings.get("ttl_days")
        return db_manager.sync_print_history_events(
            "bambu",
            events,
            integration_mode=mode,
            ttl_days=ttl_days,
            cleanup_expired=cleanup_expired and history_settings.get("cleanup_trigger") == "refresh",
        )

    @app.context_processor
    def inject_global_settings():
        return {
            "trinetra_settings": {
                "printer_volume": get_current_printer_volume(),
                "library_history": get_library_history_settings(),
                "integrations": list_printer_integrations(get_runtime_integration_config()),
            }
        }

    def get_stl_files(base_path):
        """Get STL files from database instead of filesystem."""
        return db_manager.get_stl_files()

    def fix_duplicated_folders(base_path):
        """Fix existing folders that have duplicated structure like folder/folder/"""
        fixed_count = 0
        for root, dirs, files in os.walk(base_path):
            # Check if this is a duplicated folder structure
            rel_path = os.path.relpath(root, base_path)
            path_parts = rel_path.split(os.sep)

            # If we have a path like "folder/folder", fix it
            if len(path_parts) >= 2 and path_parts[0] == path_parts[1]:
                # This is a duplicated folder structure
                parent_folder = os.path.join(base_path, path_parts[0])
                duplicated_folder = root

                # Check if the parent folder is empty or only contains the duplicated folder
                parent_contents = os.listdir(parent_folder)
                if len(parent_contents) == 1 and os.path.isdir(duplicated_folder):
                    # Move all contents from duplicated_folder to parent_folder
                    for item in os.listdir(duplicated_folder):
                        source_path = os.path.join(duplicated_folder, item)
                        dest_path = os.path.join(parent_folder, item)
                        import shutil

                        shutil.move(source_path, dest_path)

                    # Remove the empty duplicated folder
                    import shutil

                    shutil.rmtree(duplicated_folder)
                    fixed_count += 1
                    app.logger.info(f"Fixed duplicated folder structure: {rel_path}")

        return fixed_count

    def extract_gcode_metadata_from_file(file_path):
        metadata = {}
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as file:
                metadata = gcode_handler.extract_gcode_metadata(file)
        except Exception as e:
            app.logger.error(f"Error reading G-code file {file_path}: {e}")
        return metadata

    def get_folder_contents(folder_name):
        """Get folder contents from database instead of filesystem."""
        return db_manager.get_folder_contents(folder_name)

    def get_folder_three_mf_projects(folder_name):
        """Get parsed 3MF project data for folder."""
        return db_manager.get_folder_three_mf_projects(folder_name)

    # --- All routes below, using app.config for paths ---
    @app.route("/")
    def index():
        # Render shell only; initial data loads through /api/stl_files on client startup.
        return render_template("index.html")

    @app.route("/gcode_files")
    def gcode_files_view():
        """Display all G-code files across all folders with links to their parent folders."""
        # Check if pagination is requested
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 15, type=int)
        sort_by = request.args.get("sort_by", "folder_name")
        sort_order = request.args.get("sort_order", "asc")
        filter_text = request.args.get("filter", "")
        filter_type = request.args.get("filter_type", "all")

        # Get paginated data
        paginated_data = db_manager.get_gcode_files_paginated(
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
            filter_text=filter_text,
            filter_type=filter_type,
        )

        return render_template("gcode_files.html", gcode_files=paginated_data)

    @app.route("/folder/<path:folder_name>")
    def folder_view(folder_name):
        folder_name = folder_name.split("/")[0]
        stl_files, image_files, pdf_files, gcode_files = get_folder_contents(folder_name)
        three_mf_projects = get_folder_three_mf_projects(folder_name)
        return render_template(
            "folder_view.html",
            folder_name=folder_name,
            stl_files=stl_files,
            image_files=image_files,
            pdf_files=pdf_files,
            gcode_files=gcode_files,
            three_mf_projects=three_mf_projects,
        )

    @app.route("/3mf_plate")
    def serve_3mf_plate():
        filename = request.args.get("file", "")
        plate_index = request.args.get("plate", type=int)

        if not filename or plate_index is None:
            return "Missing required parameters", 400
        if not filename.lower().endswith(".3mf"):
            return "Invalid file type", 400

        try:
            abs_path = safe_join(app.config["STL_FILES_PATH"], filename)
            if not os.path.isfile(abs_path):
                return "File not found", 404

            parsed = three_mf.load_3mf_project(abs_path)
            triangles = three_mf.get_plate_triangles(parsed, plate_index)
            if not triangles:
                return "Plate not found or empty", 404

            stl_bytes = three_mf.build_plate_stl_bytes(
                parsed,
                plate_index,
                header_text=f"{os.path.basename(filename)} plate {plate_index}",
            )
            return send_file(
                io.BytesIO(stl_bytes),
                mimetype="model/stl",
                as_attachment=False,
                download_name=f"{os.path.splitext(os.path.basename(filename))[0]}_plate_{plate_index}.stl",
            )
        except Exception as e:
            app.logger.error(f"Error serving 3MF plate for {filename}: {e}")
            return "Failed to parse 3MF project", 500

    @app.route("/stl/<path:filename>")
    def serve_stl(filename):
        try:
            return send_from_directory(
                app.config["STL_FILES_PATH"], filename, mimetype="application/octet-stream"
            )
        except Exception as e:
            app.logger.error(f"Error serving STL file {filename}: {e}")
            return "File not found", 404

    @app.route("/file/<path:filename>")
    def serve_file(filename):
        try:
            return send_from_directory(app.config["STL_FILES_PATH"], filename)
        except Exception as e:
            app.logger.error(f"Error serving file {filename}: {e}")
            return "File not found", 404

    @app.route("/gcode/<base_path>/<path:filename>")
    def serve_gcode(base_path, filename):
        if base_path == "STL_BASE_PATH":
            _base_path = app.config["STL_FILES_PATH"]
        elif base_path == "GCODE_BASE_PATH":
            _base_path = app.config["GCODE_FILES_PATH"]
        else:
            return "File not found", 404

        try:
            return send_from_directory(_base_path, filename)
        except Exception as e:
            app.logger.error(f"Error serving G-code file {filename}: {e}")
            return "File not found", 404

    @app.route("/upload", methods=["POST"])
    def upload():
        allowed_extensions = {".zip", ".3mf", ".gcode", ".stl"}

        def get_extension(filename: str) -> str:
            return os.path.splitext(filename)[1].lower()

        def upload_target_for(filename: str) -> tuple[str, str]:
            ext = get_extension(filename)
            if ext == ".zip":
                folder_name = os.path.splitext(filename)[0]
                return "zip", os.path.join(app.config["STL_FILES_PATH"], folder_name)
            if ext == ".stl":
                folder_name = os.path.splitext(filename)[0]
                return "stl", os.path.join(app.config["STL_FILES_PATH"], folder_name)
            if ext == ".3mf":
                return "3mf", os.path.join(app.config["STL_FILES_PATH"], filename)
            if ext == ".gcode":
                return "gcode", os.path.join(app.config["GCODE_FILES_PATH"], filename)
            return "unknown", ""

        def parse_bool_form(key: str, default: bool = True) -> bool:
            raw_value = str(request.form.get(key, str(default))).strip().lower()
            return raw_value not in {"0", "false", "no", "off"}

        conflict_action = str(request.form.get("conflict_action", "skip")).strip().lower()
        if conflict_action not in {"check", "skip", "overwrite"}:
            conflict_action = "skip"
        refresh_index = parse_bool_form("refresh_index", True)
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400
        raw_files = request.files.getlist("file")
        if not raw_files:
            return jsonify({"error": "No files selected"}), 400

        files = []
        for file in raw_files:
            filename = secure_filename(file.filename or "")
            if not filename:
                continue
            ext = get_extension(filename)
            if ext not in allowed_extensions:
                return jsonify({"error": "Only ZIP, STL, 3MF, and GCODE files are allowed"}), 400
            files.append((file, filename))
        if not files:
            return jsonify({"error": "No files selected"}), 400

        # Step 1: Check for conflicts if conflict_action is missing or 'check'
        if conflict_action == "check":
            conflicts = []
            for _, filename in files:
                upload_kind, target_path = upload_target_for(filename)
                if target_path and os.path.exists(target_path):
                    if upload_kind in {"zip", "stl"}:
                        conflicts.append(os.path.splitext(filename)[0])
                    else:
                        conflicts.append(filename)
            if conflicts:
                return jsonify({"ask_user": True, "conflicts": conflicts}), 200
            # If no conflicts, proceed as normal (fall through)

        # Step 2: Actually process files (skip/overwrite)
        results = []
        for file, filename in files:
            ext = get_extension(filename)
            upload_kind, target_path = upload_target_for(filename)
            item_name = (
                os.path.splitext(filename)[0] if upload_kind in {"zip", "stl"} else filename
            )
            item_exists = target_path and os.path.exists(target_path)

            # Skip existing items by default. Overwrite only when explicitly requested.
            if conflict_action != "overwrite" and item_exists:
                results.append(
                    {
                        "filename": filename,
                        "folder_name": item_name,
                        "status": "skipped",
                        "folder_existed": True,
                        "error": "Item already exists, skipped.",
                    }
                )
                continue
            if upload_kind == "zip":
                # Save the zip file temporarily
                temp_zip_path = os.path.join(app.config["STL_FILES_PATH"], filename)
                file.save(temp_zip_path)
                folder_name = os.path.splitext(filename)[0]
                extract_to = os.path.join(app.config["STL_FILES_PATH"], folder_name)
                folder_exists = os.path.exists(extract_to)
                try:
                    with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                        if folder_exists:
                            if os.path.isdir(extract_to):
                                shutil.rmtree(extract_to)
                            else:
                                os.remove(extract_to)
                        os.makedirs(extract_to, exist_ok=True)

                        # Extract to a temporary location first to handle folder duplication
                        with tempfile.TemporaryDirectory() as temp_dir:
                            safe_extract(zip_ref, temp_dir)

                            # Check if the extracted content has a folder with the same name as the zip
                            temp_contents = os.listdir(temp_dir)
                            if (
                                len(temp_contents) == 1
                                and os.path.isdir(os.path.join(temp_dir, temp_contents[0]))
                                and temp_contents[0] == folder_name
                            ):
                                # The zip contains a folder with the same name as the zip file
                                # Move contents from temp_dir/folder_name to extract_to
                                source_folder = os.path.join(temp_dir, folder_name)
                                for item in os.listdir(source_folder):
                                    source_path = os.path.join(source_folder, item)
                                    dest_path = os.path.join(extract_to, item)
                                    shutil.move(source_path, dest_path)
                            else:
                                # Normal case: move all contents from temp_dir to extract_to
                                for item in os.listdir(temp_dir):
                                    source_path = os.path.join(temp_dir, item)
                                    dest_path = os.path.join(extract_to, item)
                                    shutil.move(source_path, dest_path)

                        # Remove __MACOSX folder if present
                        macosx_path = os.path.join(extract_to, "__MACOSX")
                        if os.path.exists(macosx_path):
                            shutil.rmtree(macosx_path, ignore_errors=True)
                    results.append(
                        {
                            "filename": filename,
                            "folder_name": folder_name,
                            "status": "success",
                            "folder_existed": folder_exists,
                        }
                    )
                except Exception as e:
                    app.logger.error(f"Error extracting zip file {filename}: {e}")
                    results.append(
                        {
                            "filename": filename,
                            "folder_name": folder_name,
                            "status": "error",
                            "error": str(e),
                        }
                    )
                finally:
                    if os.path.exists(temp_zip_path):
                        os.remove(temp_zip_path)
            elif upload_kind == "stl" and target_path:
                try:
                    file_dir = target_path
                    file_path = os.path.join(file_dir, filename)
                    folder_exists = os.path.exists(file_dir)
                    if folder_exists and conflict_action == "overwrite":
                        if os.path.isdir(file_dir):
                            shutil.rmtree(file_dir)
                        else:
                            os.remove(file_dir)
                    os.makedirs(file_dir, exist_ok=True)
                    file.save(file_path)
                    results.append(
                        {
                            "filename": filename,
                            "folder_name": item_name,
                            "status": "success",
                            "folder_existed": bool(folder_exists),
                        }
                    )
                except Exception as e:
                    app.logger.error(f"Error saving STL file {filename}: {e}")
                    results.append(
                        {
                            "filename": filename,
                            "folder_name": item_name,
                            "status": "error",
                            "error": str(e),
                        }
                    )
            elif upload_kind in {"3mf", "gcode"} and target_path:
                try:
                    target_dir = os.path.dirname(target_path)
                    os.makedirs(target_dir, exist_ok=True)
                    file.save(target_path)
                    results.append(
                        {
                            "filename": filename,
                            "folder_name": item_name,
                            "status": "success",
                            "folder_existed": bool(item_exists),
                        }
                    )
                except Exception as e:
                    app.logger.error(f"Error saving file {filename}: {e}")
                    results.append(
                        {
                            "filename": filename,
                            "folder_name": item_name,
                            "status": "error",
                            "error": str(e),
                        }
                    )
            else:
                results.append(
                    {
                        "filename": filename,
                        "folder_name": item_name,
                        "status": "error",
                        "error": f"Unsupported file type: {ext}",
                    }
                )
        # Refresh DB index once after all upload processing is complete (optional).
        index_refresh = {"success": False}
        if refresh_index:
            try:
                moonraker_url = get_enabled_moonraker_url()
                moonraker_client = get_enabled_moonraker_client()
                counts = db_manager.reload_index(
                    app.config["STL_FILES_PATH"],
                    app.config["GCODE_FILES_PATH"],
                    moonraker_url,
                    moonraker_client,
                )
                bambu_sync = sync_bambu_history(cleanup_expired=True)
                counts["bambu_history_synced"] = bambu_sync
                index_refresh = {"success": True, "counts": counts}
            except Exception as e:
                app.logger.error(f"Error refreshing index after upload: {e}")
                index_refresh = {"success": False, "error": str(e)}
        else:
            index_refresh = {"success": True, "skipped": True}

        return jsonify({"success": True, "results": results, "index_refresh": index_refresh}), 200

    def allowed_file(filename):
        return filename.lower().endswith((".zip", ".stl", ".3mf", ".gcode"))

    def safe_extract(zip_file, path):
        """Safely extract zip files to prevent zip slip vulnerabilities."""
        for member in zip_file.namelist():
            member_path = os.path.realpath(os.path.join(path, member))
            if not member_path.startswith(os.path.realpath(path) + os.sep):
                raise Exception("Attempted Path Traversal in Zip File")
        zip_file.extractall(path)

    @app.route("/delete_folder", methods=["POST"])
    def delete_folder():
        data = request.get_json()
        folder_name = data.get("folder_name")

        if not folder_name:
            return jsonify({"success": False, "error": "Folder name is required."}), 400

        try:
            success = db_manager.delete_folder(folder_name)
            if success:
                return jsonify({"success": True}), 200
            else:
                return jsonify({"success": False, "error": "Folder does not exist."}), 404
        except Exception as e:
            app.logger.error(f"Error deleting folder: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/download_folder", methods=["GET"])
    def download_folder():
        folder_name = request.args.get("folder_name")

        if not folder_name:
            return "Folder name is required.", 400

        try:
            folder_path = safe_join(app.config["STL_FILES_PATH"], folder_name)
        except Exception as e:
            return "Invalid folder path.", 400

        if not os.path.isdir(folder_path):
            return "Folder does not exist.", 404

        memory_file = io.BytesIO()

        try:
            with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(folder_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, folder_path)
                        zipf.write(file_path, arcname)
            memory_file.seek(0)
            return send_file(
                memory_file,
                download_name=f"{os.path.basename(folder_name)}.zip",
                as_attachment=True,
            )
        except Exception as e:
            app.logger.error(f"Error zipping folder: {e}")
            return f"Error zipping folder: {e!s}", 500

    @app.route("/copy_path/<path:filename>", methods=["GET"])
    def copy_path(filename):
        try:
            abs_path = safe_join(app.config["STL_FILES_PATH"], filename)
            if os.path.isfile(abs_path):
                return jsonify({"path": abs_path})
            else:
                return jsonify({"path": ""}), 404
        except Exception as e:
            app.logger.error(f"Error copying path: {e}")
            return jsonify({"path": ""}), 404

    @app.route("/copy_gcode_path/<base_path>/<path:filename>", methods=["GET"])
    def copy_gcode_path(base_path, filename):
        if base_path == "STL_BASE_PATH":
            _base_path = app.config["STL_FILES_PATH"]
        elif base_path == "GCODE_BASE_PATH":
            _base_path = app.config["GCODE_FILES_PATH"]
        else:
            return jsonify({"path": ""}), 404

        try:
            abs_path = safe_join(_base_path, filename)
            if os.path.isfile(abs_path):
                return jsonify({"path": abs_path})
            else:
                return jsonify({"path": ""}), 404
        except Exception as e:
            app.logger.error(f"Error copying G-code path: {e}")
            return jsonify({"path": ""}), 404

    @app.route("/moonraker_stats/<path:filename>", methods=["GET"])
    def get_moonraker_stats(filename):
        """Get Moonraker print statistics for a G-code file from database."""
        try:
            # Get file stats from database
            all_gcode_files = db_manager.get_all_gcode_files()

            # Find the file with matching name
            file_stats = None
            for gcode_file in all_gcode_files:
                if gcode_file["file_name"] == filename:
                    file_stats = gcode_file["stats"]
                    break

            if file_stats:
                return jsonify({"success": True, "stats": file_stats})
            else:
                return jsonify(
                    {"success": False, "message": "No print history found for this file"}
                )
        except Exception as e:
            app.logger.error(f"Error getting stats for {filename}: {e}")
            return jsonify({"success": False, "message": "Failed to get print statistics"}), 500

    @app.route("/search", methods=["GET"])
    def search_route():
        query_text = request.args.get("q", "").strip()
        search_limit = app.config.get("SEARCH_RESULT_LIMIT", 25)

        filtered_folders = db_manager.search_stl_files(query_text, search_limit)

        total_matches = sum(len(folder["files"]) for folder in filtered_folders)
        metadata = {"matches": total_matches}

        return jsonify({"stl_files": filtered_folders, "metadata": metadata})

    @app.route("/search_gcode", methods=["GET"])
    def search_gcode_route():
        query_text = request.args.get("q", "").strip()
        search_limit = app.config.get("SEARCH_RESULT_LIMIT", 25)

        filtered_gcode_files = db_manager.search_gcode_files(query_text, search_limit)
        metadata = {"matches": len(filtered_gcode_files)}
        return jsonify({"gcode_files": filtered_gcode_files, "metadata": metadata})

    @app.route("/api/stl_files")
    def api_stl_files():
        """API endpoint for paginated STL files."""
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 15, type=int)
        sort_by = request.args.get("sort_by", DEFAULT_STL_SORT_BY)
        sort_order = request.args.get("sort_order", DEFAULT_STL_SORT_ORDER)
        filter_text = request.args.get("filter", "")
        filter_type = request.args.get("filter_type", "all")

        paginated_data = db_manager.get_stl_files_paginated(
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
            filter_text=filter_text,
            filter_type=filter_type,
        )

        return jsonify(paginated_data)

    @app.route("/api/gcode_files")
    def api_gcode_files():
        """API endpoint for paginated G-code files."""
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 15, type=int)
        sort_by = request.args.get("sort_by", "folder_name")
        sort_order = request.args.get("sort_order", "asc")
        filter_text = request.args.get("filter", "")
        filter_type = request.args.get("filter_type", "all")

        paginated_data = db_manager.get_gcode_files_paginated(
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
            filter_text=filter_text,
            filter_type=filter_type,
        )

        return jsonify(paginated_data)

    @app.route("/stats")
    def stats_view():
        """Display comprehensive statistics about files, folders, and printing activity."""
        try:
            # Get file and folder statistics from database
            db_stats = db_manager.get_stats()

            # Get printing statistics from database
            printing_stats = db_manager.get_printing_stats()

            # --- Activity Calendar Generation ---
            from datetime import datetime, timedelta
            import collections

            # Initialize activity calendar with 0 prints for each day
            activity_calendar = collections.OrderedDict()
            today = datetime.now().date()
            start_date = today - timedelta(days=364)
            for i in range(365):
                day = start_date + timedelta(days=i)
                activity_calendar[day.strftime("%Y-%m-%d")] = 0

            # Fill with data from database
            db_activity_data = db_manager.get_activity_calendar()
            for date_str, count in db_activity_data.items():
                if date_str in activity_calendar:
                    activity_calendar[date_str] = count
            # --- End Activity Calendar Generation ---

            stats = {
                **db_stats,
                "printing_stats": printing_stats,
                "activity_calendar": activity_calendar,
            }

            return render_template("stats.html", stats=stats)

        except Exception as e:
            app.logger.error(f"Error generating stats: {e}")
            return "Error generating statistics", 500

    @app.route("/settings")
    def settings_view():
        return render_template(
            "settings.html",
            printer_volume=get_current_printer_volume(),
            popular_printers=POPULAR_PRINTERS,
            library_history_settings=get_library_history_settings(),
            bambu_integration=get_bambu_integration_state(),
            moonraker_integration=get_moonraker_integration_state(),
        )

    @app.route("/api/settings/printer_volume", methods=["GET", "POST"])
    def api_settings_printer_volume():
        if request.method == "GET":
            return jsonify(
                {
                    "success": True,
                    "printer_volume": get_current_printer_volume(),
                    "default_printer_volume": DEFAULT_PRINTER_VOLUME,
                    "popular_printers": POPULAR_PRINTERS,
                }
            )

        payload = request.get_json(silent=True) or {}
        preset_id = payload.get("preset_id")
        selected_preset = None

        if preset_id:
            selected_preset = next(
                (printer for printer in POPULAR_PRINTERS if printer["id"] == preset_id), None
            )
            if not selected_preset:
                return jsonify({"success": False, "error": "Invalid printer preset"}), 400

        if selected_preset:
            volume = {
                "x": float(selected_preset["x"]),
                "y": float(selected_preset["y"]),
                "z": float(selected_preset["z"]),
            }
            profile = selected_preset["id"]
        else:
            x = _coerce_positive_float(payload.get("x"))
            y = _coerce_positive_float(payload.get("y"))
            z = _coerce_positive_float(payload.get("z"))
            if x is None or y is None or z is None:
                return jsonify({"success": False, "error": "Invalid printer volume values"}), 400
            volume = {"x": x, "y": y, "z": z}
            profile = "custom"

        try:
            write_config_updates({"printer_volume": volume, "printer_profile": profile})
            return jsonify(
                {
                    "success": True,
                    "printer_volume": get_current_printer_volume(),
                    "printer_profile": profile,
                }
            )
        except Exception as e:
            app.logger.error(f"Error saving printer volume settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/settings/library/history", methods=["GET", "POST"])
    def api_settings_library_history():
        if request.method == "GET":
            return jsonify({"success": True, "history": get_library_history_settings()})

        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get("enabled", True))
        ttl_days = _coerce_non_negative_int(payload.get("ttl_days"))
        if ttl_days is None:
            return jsonify({"success": False, "error": "Invalid TTL value"}), 400

        cleanup_trigger = str(payload.get("cleanup_trigger", "refresh")).strip().lower() or "refresh"
        if cleanup_trigger not in {"refresh"}:
            return jsonify({"success": False, "error": "Unsupported cleanup trigger"}), 400

        try:
            current_config = load_config(app.config["CONFIG_FILE_PATH"])
            library_cfg = current_config.get("library", {})
            if not isinstance(library_cfg, dict):
                library_cfg = {}
            history_cfg = library_cfg.get("history", {})
            if not isinstance(history_cfg, dict):
                history_cfg = {}

            history_cfg["enabled"] = enabled
            history_cfg["ttl_days"] = ttl_days
            history_cfg["cleanup_trigger"] = cleanup_trigger
            library_cfg["history"] = history_cfg

            write_config_updates({"library": library_cfg})
            return jsonify({"success": True, "history": get_library_history_settings()})
        except Exception as e:
            app.logger.error(f"Error saving library history settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/settings/integrations/bambu", methods=["GET", "POST"])
    def api_settings_bambu_integration():
        if request.method == "GET":
            return jsonify({"success": True, "integration": get_bambu_integration_state()})

        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get("enabled", False))
        mode = str(payload.get("mode", "cloud")).strip().lower() or "cloud"
        access_token = str(payload.get("access_token", "")).strip()
        refresh_token = str(payload.get("refresh_token", "")).strip()
        region = str(payload.get("region", "global")).strip().lower() or "global"

        if mode != "cloud":
            return jsonify(
                {
                    "success": False,
                    "error": "Only cloud mode is available right now. Local mode will be added next.",
                }
            ), 400

        if enabled and not access_token:
            return jsonify({"success": False, "error": "Bambu access token is required when enabled"}), 400

        try:
            current_config = load_config(app.config["CONFIG_FILE_PATH"])
            integrations = current_config.get("integrations", {})
            if not isinstance(integrations, dict):
                integrations = {}

            bambu_cfg = integrations.get("bambu", {})
            if not isinstance(bambu_cfg, dict):
                bambu_cfg = {}

            bambu_cfg["enabled"] = enabled
            bambu_cfg["mode"] = mode
            bambu_cfg["cloud"] = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "region": region,
            }
            integrations["bambu"] = bambu_cfg

            write_config_updates({"integrations": integrations})
            return jsonify({"success": True, "integration": get_bambu_integration_state()})
        except Exception as e:
            app.logger.error(f"Error saving bambu integration settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/settings/integrations/moonraker", methods=["GET", "POST"])
    def api_settings_moonraker_integration():
        if request.method == "GET":
            return jsonify({"success": True, "integration": get_moonraker_integration_state()})

        payload = request.get_json(silent=True) or {}
        enabled = bool(payload.get("enabled", False))
        base_url = str(payload.get("base_url", "")).strip()

        if enabled and not base_url:
            return jsonify({"success": False, "error": "Moonraker URL is required when enabled"}), 400

        try:
            current_config = load_config(app.config["CONFIG_FILE_PATH"])
            integrations = current_config.get("integrations", {})
            if not isinstance(integrations, dict):
                integrations = {}

            moonraker_cfg = integrations.get("moonraker", {})
            if not isinstance(moonraker_cfg, dict):
                moonraker_cfg = {}

            moonraker_cfg["enabled"] = enabled
            moonraker_cfg["base_url"] = base_url
            integrations["moonraker"] = moonraker_cfg

            write_config_updates({"integrations": integrations, "moonraker_url": base_url})

            return jsonify({"success": True, "integration": get_moonraker_integration_state()})
        except Exception as e:
            app.logger.error(f"Error saving moonraker integration settings: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    def get_moonraker_printing_stats():
        """Get aggregated printing statistics from database."""
        try:
            return db_manager.get_printing_stats()
        except Exception as e:
            app.logger.error(f"Error getting printing stats from database: {e}")
            return {
                "total_prints": 0,
                "successful_prints": 0,
                "canceled_prints": 0,
                "avg_print_time_hours": 0,
                "total_filament_meters": 0,
                "print_days": 0,
            }

    @app.route("/reload_index", methods=["POST"])
    def reload_index():
        """Reload the entire index from filesystem."""
        try:
            mode = request.args.get("mode", "all").strip().lower() or "all"
            if mode not in {"all", "files", "stats"}:
                return jsonify({"success": False, "error": "Invalid reload mode"}), 400

            counts = {}
            if mode == "all":
                stl_base_path = app.config["STL_FILES_PATH"]
                gcode_base_path = app.config["GCODE_FILES_PATH"]

                moonraker_url = get_enabled_moonraker_url()
                moonraker_client = get_enabled_moonraker_client()
                counts = db_manager.reload_index(
                    stl_base_path, gcode_base_path, moonraker_url, moonraker_client
                )
                counts["bambu_history_synced"] = sync_bambu_history(cleanup_expired=True)
            elif mode == "files":
                stl_base_path = app.config["STL_FILES_PATH"]
                gcode_base_path = app.config["GCODE_FILES_PATH"]
                counts = db_manager.reload_index(stl_base_path, gcode_base_path)
            else:
                moonraker_url = get_enabled_moonraker_url()
                moonraker_client = get_enabled_moonraker_client()
                if moonraker_url:
                    moonraker_counts = db_manager.reload_moonraker_only(
                        moonraker_url, moonraker_client
                    )
                    counts["moonraker_stats_updated"] = moonraker_counts.get("updated", 0)
                    counts["moonraker_stats_failed"] = moonraker_counts.get("failed", 0)
                counts["bambu_history_synced"] = sync_bambu_history(cleanup_expired=True)

            return jsonify(
                {"success": True, "message": "Index reloaded successfully", "counts": counts}
            ), 200
        except Exception as e:
            app.logger.error(f"Error reloading index: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/add_to_queue", methods=["POST"])
    def api_add_to_queue():
        data = request.get_json(force=True)
        filenames = data.get("filenames")
        reset = data.get("reset", False)
        if not isinstance(filenames, list) or not all(isinstance(f, str) for f in filenames):
            app.logger.error(f"Invalid filenames payload: {filenames}")
            return jsonify({"error": "Invalid filenames payload"}), 400
        integration = get_printer_integration("moonraker")
        if integration is None:
            return jsonify({"error": "Moonraker integration is unavailable"}), 500

        runtime_config = get_runtime_integration_config()
        if not integration.is_enabled(runtime_config):
            return jsonify({"error": "Moonraker integration is disabled in Settings"}), 400
        if not integration.is_configured(runtime_config):
            return jsonify({"error": "Moonraker integration is not configured"}), 400

        app.logger.debug(
            f"Calling Moonraker integration queue with: filenames={filenames}, reset={reset}"
        )
        success = integration.queue_jobs(runtime_config, filenames, reset)
        app.logger.debug(f"Moonraker integration queue result: {success}")
        if not success:
            return jsonify({"error": "Failed to add files to Moonraker queue"}), 502
        return jsonify({"result": "ok"})

    # Attach helpers for testing
    app.get_stl_files = get_stl_files
    app.extract_gcode_metadata_from_file = extract_gcode_metadata_from_file
    app.get_folder_contents = get_folder_contents
    app.get_folder_three_mf_projects = get_folder_three_mf_projects
    app.get_moonraker_printing_stats = get_moonraker_printing_stats
    app.get_current_printer_volume = get_current_printer_volume
    app.get_library_history_settings = get_library_history_settings
    app.get_bambu_integration_state = get_bambu_integration_state
    app.get_moonraker_integration_state = get_moonraker_integration_state
    app.allowed_file = allowed_file
    app.safe_extract = safe_extract
    app.safe_join = safe_join
    app.load_config = load_config

    return app


if __name__ == "__main__":
    app = create_app()
    logger.info(
        f"STL files: {app.config['STL_FILES_PATH']}, GCODE files: {app.config['GCODE_FILES_PATH']}"
    )

    if app.config.get("MODE", "PROD") == "DEV":
        app.run(host="0.0.0.0", port=app.config.get("PORT", 8969), debug=False)
    else:
        app.run()

# Create global app instance for gunicorn
app = create_app()
