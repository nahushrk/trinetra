import io
import logging
import os
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

from trinetra import gcode_handler, search, moonraker
from trinetra import three_mf
from trinetra.moonraker import MoonrakerAPI, add_to_queue
from trinetra.database import DatabaseManager
from trinetra.config_paths import resolve_storage_paths

# Import logging configuration from trinetra package
from trinetra.logger import get_logger, configure_logging

# Global logger - will be configured after config is loaded
logger = None


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
    config = load_config(config_file)
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
        # Check if pagination is requested
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 15, type=int)
        sort_by = request.args.get("sort_by", "folder_name")
        sort_order = request.args.get("sort_order", "asc")
        filter_text = request.args.get("filter", "")
        filter_type = request.args.get("filter_type", "all")

        # Get paginated data
        paginated_data = db_manager.get_stl_files_paginated(
            page=page,
            per_page=per_page,
            sort_by=sort_by,
            sort_order=sort_order,
            filter_text=filter_text,
            filter_type=filter_type,
        )

        # Ensure proper JSON serialization
        formatted_data = {
            "folders": paginated_data.get("folders", []),
            "pagination": paginated_data.get("pagination", {}),
            "filter": paginated_data.get("filter", {})
        }
        
        return render_template("index.html", stl_files=formatted_data)

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
        conflict_action = request.form.get("conflict_action", "check")
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400
        files = request.files.getlist("file")
        if not files:
            return jsonify({"error": "No files selected"}), 400
        # Only accept zip files
        for file in files:
            if not file.filename.lower().endswith(".zip"):
                return jsonify({"error": "Only ZIP files are allowed"}), 400
        # Step 1: Check for conflicts if conflict_action is missing or 'check'
        if conflict_action == "check":
            conflicts = []
            for file in files:
                filename = secure_filename(file.filename)
                if not filename:
                    continue
                folder_name = os.path.splitext(filename)[0]
                extract_to = os.path.join(app.config["STL_FILES_PATH"], folder_name)
                if os.path.exists(extract_to):
                    conflicts.append(folder_name)
            if conflicts:
                return jsonify({"ask_user": True, "conflicts": conflicts}), 200
            # If no conflicts, proceed as normal (fall through)
        # Step 2: Actually process files (skip/overwrite)
        results = []
        for file in files:
            filename = secure_filename(file.filename)
            if not filename:
                continue
            folder_name = os.path.splitext(filename)[0]
            extract_to = os.path.join(app.config["STL_FILES_PATH"], folder_name)
            folder_exists = os.path.exists(extract_to)
            # If skipping, skip files whose folders exist
            if conflict_action == "skip" and folder_exists:
                results.append(
                    {
                        "filename": filename,
                        "folder_name": folder_name,
                        "status": "skipped",
                        "folder_existed": True,
                        "error": "Folder already exists, skipped as per user choice.",
                    }
                )
                continue
            # Save the zip file temporarily
            temp_zip_path = os.path.join(app.config["STL_FILES_PATH"], filename)
            file.save(temp_zip_path)
            try:
                with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                    if folder_exists:
                        import shutil

                        shutil.rmtree(extract_to)
                    os.makedirs(extract_to, exist_ok=True)

                    # Extract to a temporary location first to handle folder duplication
                    import tempfile

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
                                if os.path.isdir(source_path):
                                    import shutil

                                    shutil.move(source_path, dest_path)
                                else:
                                    import shutil

                                    shutil.move(source_path, dest_path)
                        else:
                            # Normal case: move all contents from temp_dir to extract_to
                            for item in os.listdir(temp_dir):
                                source_path = os.path.join(temp_dir, item)
                                dest_path = os.path.join(extract_to, item)
                                if os.path.isdir(source_path):
                                    import shutil

                                    shutil.move(source_path, dest_path)
                                else:
                                    import shutil

                                    shutil.move(source_path, dest_path)

                    # Remove __MACOSX folder if present
                    macosx_path = os.path.join(extract_to, "__MACOSX")
                    if os.path.exists(macosx_path):
                        import shutil

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
        return jsonify({"success": True, "results": results}), 200

    def allowed_file(filename):
        # Only allow zip files now
        return filename.lower().endswith(".zip")

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
        sort_by = request.args.get("sort_by", "folder_name")
        sort_order = request.args.get("sort_order", "asc")
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
            stl_base_path = app.config["STL_FILES_PATH"]
            gcode_base_path = app.config["GCODE_FILES_PATH"]

            moonraker_url = app.config.get("MOONRAKER_URL")
            counts = db_manager.reload_index(stl_base_path, gcode_base_path, moonraker_url)

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
        moonraker_url = app.config.get("MOONRAKER_URL", "http://localhost:7125")
        app.logger.debug(
            f"Calling Moonraker add_to_queue with: filenames={filenames}, reset={reset}"
        )
        success = add_to_queue(filenames, reset, moonraker_url)
        app.logger.debug(f"Moonraker add_to_queue result: {success}")
        if not success:
            return jsonify({"error": "Failed to add files to Moonraker queue"}), 502
        return jsonify({"result": "ok"})

    # Attach helpers for testing
    app.get_stl_files = get_stl_files
    app.extract_gcode_metadata_from_file = extract_gcode_metadata_from_file
    app.get_folder_contents = get_folder_contents
    app.get_folder_three_mf_projects = get_folder_three_mf_projects
    app.get_moonraker_printing_stats = get_moonraker_printing_stats
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
