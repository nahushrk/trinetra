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
from trinetra.moonraker import MoonrakerAPI, add_to_queue


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
        logging.error(f"Error loading configuration file: {e}")
        return {}


def create_app(config_file=None, config_overrides=None):
    config = load_config(config_file)
    if config_overrides:
        config.update(config_overrides)

    app = Flask(__name__)
    Compress(app)

    # Set up config in app.config
    for k, v in config.items():
        app.config[k.upper()] = v

    log_level = config.get("log_level", "INFO")
    app.logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    app.logger.info(f"Config: {config}")

    # Set up paths
    stl_files_path = os.path.expanduser(config.get("base_path", "./stl_files"))
    gcode_files_path = os.path.expanduser(config.get("gcode_path", "./gcode_files"))
    os.makedirs(stl_files_path, exist_ok=True)
    os.makedirs(gcode_files_path, exist_ok=True)
    app.config["STL_FILES_PATH"] = stl_files_path
    app.config["GCODE_FILES_PATH"] = gcode_files_path

    def get_stl_files(base_path):
        stl_files = []
        for root, dirs, files in os.walk(base_path):
            folder_files = []
            for file in files:
                if file.lower().endswith(".stl"):
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, base_path)
                    folder_files.append({"file_name": file, "rel_path": rel_path})
            if folder_files:
                folder_name = os.path.relpath(root, base_path)
                top_level_folder = folder_name.split(os.sep)[0]
                stl_files.append(
                    {
                        "folder_name": folder_name,
                        "top_level_folder": top_level_folder,
                        "files": folder_files,
                    }
                )
        return stl_files

    def extract_gcode_metadata_from_file(file_path):
        metadata = {}
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as file:
                metadata = gcode_handler.extract_gcode_metadata(file)
        except Exception as e:
            app.logger.error(f"Error reading G-code file {file_path}: {e}")
        return metadata

    def get_folder_contents(folder_name):
        try:
            folder_path = safe_join(app.config["STL_FILES_PATH"], folder_name)
        except Exception as e:
            app.logger.error(f"Invalid folder path: {e}")
            return [], [], [], []

        stl_files = []
        image_files = []
        pdf_files = []
        gcode_files = []

        if not os.path.isdir(folder_path):
            app.logger.error(f"Folder {folder_path} does not exist")
            return stl_files, image_files, pdf_files, gcode_files
        app.logger.debug(f"Scanning folder {folder_path}")

        for root, dirs, files in os.walk(folder_path):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, app.config["STL_FILES_PATH"])
                ext = os.path.splitext(file)[1].lower()
                if os.path.isfile(abs_path):
                    app.logger.debug(f"Found file {file}")
                    if ext == ".stl":
                        stl_files.append(
                            {"file_name": file, "path": "STL_BASE_PATH", "rel_path": rel_path}
                        )
                    elif ext in [".png", ".jpg", ".jpeg", ".gif", ".bmp"]:
                        image_files.append(
                            {
                                "file_name": file,
                                "path": "STL_BASE_PATH",
                                "rel_path": rel_path,
                                "ext": ext,
                            }
                        )
                    elif ext == ".pdf":
                        pdf_files.append(
                            {
                                "file_name": file,
                                "path": "STL_BASE_PATH",
                                "rel_path": rel_path,
                                "ext": ext,
                            }
                        )
                    elif ext == ".gcode":
                        metadata = extract_gcode_metadata_from_file(abs_path)
                        gcode_files.append(
                            {
                                "file_name": file,
                                "path": "STL_BASE_PATH",
                                "rel_path": rel_path,
                                "metadata": metadata,
                            }
                        )

        gcode_files_path = app.config["GCODE_FILES_PATH"]
        if gcode_files_path and os.path.isdir(gcode_files_path):
            for stl_file in stl_files:
                stl_file_name = os.path.splitext(stl_file["file_name"])[0].lower()
                for root, dirs, files in os.walk(gcode_files_path):
                    for gcode_file in files:
                        if gcode_file.endswith(".gcode") and search.search_tokens_all_match(
                            search.tokenize(stl_file_name), search.tokenize(gcode_file.lower())
                        ):
                            abs_gcode_path = os.path.join(root, gcode_file)
                            rel_gcode_path = os.path.relpath(abs_gcode_path, gcode_files_path)
                            metadata = extract_gcode_metadata_from_file(abs_gcode_path)
                            gcode_files.append(
                                {
                                    "file_name": gcode_file,
                                    "path": "GCODE_BASE_PATH",
                                    "rel_path": rel_gcode_path,
                                    "metadata": metadata,
                                }
                            )
                            app.logger.debug(
                                f"Found matching G-code file for {stl_file_name}: {gcode_file}"
                            )

        app.logger.debug(f"STL files: {stl_files}")
        app.logger.debug(f"Image files: {image_files}")
        app.logger.debug(f"PDF files: {pdf_files}")
        app.logger.debug(f"G-code files: {gcode_files}")
        return stl_files, image_files, pdf_files, gcode_files

    # --- All routes below, using app.config for paths ---
    @app.route("/")
    def index():
        stl_files = get_stl_files(app.config["STL_FILES_PATH"])
        return render_template("index.html", stl_files=stl_files)

    @app.route("/gcode_files")
    def gcode_files_view():
        """Display all G-code files across all folders with links to their parent folders."""
        all_gcode_files = []

        # Collect G-code files from the GCODE_FILES_PATH
        if app.config["GCODE_FILES_PATH"] and os.path.isdir(app.config["GCODE_FILES_PATH"]):
            for root, dirs, files in os.walk(app.config["GCODE_FILES_PATH"]):
                for file in files:
                    if file.lower().endswith(".gcode"):
                        abs_path = os.path.join(root, file)
                        rel_path = os.path.relpath(abs_path, app.config["GCODE_FILES_PATH"])

                        # Try to find the associated STL file to determine the folder
                        stl_file_name = os.path.splitext(file)[0].lower()
                        folder_name = "Unknown"

                        # Search for matching STL file to determine folder
                        for stl_root, stl_dirs, stl_files in os.walk(app.config["STL_FILES_PATH"]):
                            for stl_file in stl_files:
                                if stl_file.lower().endswith(".stl"):
                                    stl_name = os.path.splitext(stl_file)[0].lower()
                                    if search.search_tokens_all_match(
                                        search.tokenize(stl_name), search.tokenize(stl_file_name)
                                    ):
                                        stl_rel_path = os.path.relpath(
                                            os.path.join(stl_root, stl_file),
                                            app.config["STL_FILES_PATH"],
                                        )
                                        folder_name = (
                                            os.path.dirname(stl_rel_path)
                                            if os.path.dirname(stl_rel_path)
                                            else os.path.basename(stl_root)
                                        )
                                        break
                            if folder_name != "Unknown":
                                break

                        metadata = extract_gcode_metadata_from_file(abs_path)
                        all_gcode_files.append(
                            {
                                "file_name": file,
                                "rel_path": rel_path,
                                "folder_name": folder_name,
                                "metadata": metadata,
                                "base_path": "GCODE_BASE_PATH",
                            }
                        )

        # Sort by folder name, then by file name
        all_gcode_files.sort(key=lambda x: (x["folder_name"], x["file_name"]))

        return render_template("gcode_files.html", gcode_files=all_gcode_files)

    @app.route("/folder/<path:folder_name>")
    def folder_view(folder_name):
        folder_name = folder_name.split("/")[0]
        stl_files, image_files, pdf_files, gcode_files = get_folder_contents(folder_name)
        return render_template(
            "folder_view.html",
            folder_name=folder_name,
            stl_files=stl_files,
            image_files=image_files,
            pdf_files=pdf_files,
            gcode_files=gcode_files,
        )

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
        if "file" not in request.files:
            return jsonify({"error": "No file part"}), 400

        files = request.files.getlist("file")
        if not files:
            return jsonify({"error": "No files selected"}), 400

        # Only accept zip files
        for file in files:
            if not file.filename.lower().endswith(".zip"):
                return jsonify({"error": "Only ZIP files are allowed"}), 400

        results = []
        for file in files:
            filename = secure_filename(file.filename)
            if not filename:
                continue

            # Create a folder with the same name as the zip file (without the extension)
            folder_name = os.path.splitext(filename)[0]
            extract_to = os.path.join(app.config["STL_FILES_PATH"], folder_name)

            # Check if folder already exists
            folder_exists = os.path.exists(extract_to)

            # Save the zip file temporarily
            temp_zip_path = os.path.join(app.config["STL_FILES_PATH"], filename)
            file.save(temp_zip_path)

            try:
                # Extract the ZIP into the created folder
                with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                    if folder_exists:
                        # If folder exists, remove it first (overwrite mode)
                        import shutil

                        shutil.rmtree(extract_to)

                    os.makedirs(extract_to, exist_ok=True)
                    safe_extract(zip_ref, extract_to)

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
                # Clean up temporary zip file
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
            folder_path = safe_join(app.config["STL_FILES_PATH"], folder_name)
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

        if not os.path.isdir(folder_path):
            return jsonify({"success": False, "error": "Folder does not exist."}), 404

        try:
            import shutil

            shutil.rmtree(folder_path)
            return jsonify({"success": True}), 200
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
        """Get Moonraker print statistics for a G-code file."""
        try:
            moonraker_url = app.config.get("MOONRAKER_URL")
            if not moonraker_url:
                return jsonify({"success": False, "message": "Moonraker URL not configured"}), 503

            stats = moonraker.get_moonraker_stats(filename, moonraker_url)

            if stats:
                return jsonify({"success": True, "stats": stats})
            else:
                return jsonify(
                    {"success": False, "message": "No print history found for this file"}
                )
        except Exception as e:
            app.logger.error(f"Error getting Moonraker stats for {filename}: {e}")
            return jsonify({"success": False, "message": "Failed to get print statistics"}), 500

    @app.route("/search", methods=["GET"])
    def search_route():
        query_text = request.args.get("q", "").strip()
        search_limit = app.config.get("SEARCH_RESULT_LIMIT", 25)

        stl_folders = get_stl_files(app.config["STL_FILES_PATH"])
        filtered_folders = search.search_files_and_folders(query_text, stl_folders, search_limit)

        total_matches = sum(len(folder["files"]) for folder in filtered_folders)
        metadata = {"matches": total_matches}

        return jsonify({"stl_files": filtered_folders, "metadata": metadata})

    @app.route("/search_gcode", methods=["GET"])
    def search_gcode_route():
        query_text = request.args.get("q", "").strip()
        search_limit = app.config.get("SEARCH_RESULT_LIMIT", 25)

        # Get all G-code files
        all_gcode_files = []
        if app.config["GCODE_FILES_PATH"] and os.path.isdir(app.config["GCODE_FILES_PATH"]):
            for root, dirs, files in os.walk(app.config["GCODE_FILES_PATH"]):
                for file in files:
                    if file.lower().endswith(".gcode"):
                        abs_path = os.path.join(root, file)
                        rel_path = os.path.relpath(abs_path, app.config["GCODE_FILES_PATH"])

                        # Try to find the associated STL file to determine the folder
                        stl_file_name = os.path.splitext(file)[0].lower()
                        folder_name = "Unknown"

                        # Search for matching STL file to determine folder
                        for stl_root, stl_dirs, stl_files in os.walk(app.config["STL_FILES_PATH"]):
                            for stl_file in stl_files:
                                if stl_file.lower().endswith(".stl"):
                                    stl_name = os.path.splitext(stl_file)[0].lower()
                                    if search.search_tokens_all_match(
                                        search.tokenize(stl_name), search.tokenize(stl_file_name)
                                    ):
                                        stl_rel_path = os.path.relpath(
                                            os.path.join(stl_root, stl_file),
                                            app.config["STL_FILES_PATH"],
                                        )
                                        folder_name = (
                                            os.path.dirname(stl_rel_path)
                                            if os.path.dirname(stl_rel_path)
                                            else os.path.basename(stl_root)
                                        )
                                        break
                        if folder_name != "Unknown":
                            break

                        metadata = extract_gcode_metadata_from_file(abs_path)
                        all_gcode_files.append(
                            {
                                "file_name": file,
                                "rel_path": rel_path,
                                "folder_name": folder_name,
                                "metadata": metadata,
                                "base_path": "GCODE_BASE_PATH",
                            }
                        )

        filtered_gcode_files = search.search_gcode_files(query_text, all_gcode_files, search_limit)
        metadata = {"matches": len(filtered_gcode_files)}

        return jsonify({"gcode_files": filtered_gcode_files, "metadata": metadata})

    @app.route("/stats")
    def stats_view():
        """Display comprehensive statistics about files, folders, and printing activity."""
        try:
            # Get file and folder statistics
            stl_folders = get_stl_files(app.config["STL_FILES_PATH"])
            total_folders = len(stl_folders)
            total_stl_files = sum(len(folder["files"]) for folder in stl_folders)

            # Count G-code files
            total_gcode_files = 0
            folders_with_gcode = set()

            if app.config["GCODE_FILES_PATH"] and os.path.isdir(app.config["GCODE_FILES_PATH"]):
                for root, dirs, files in os.walk(app.config["GCODE_FILES_PATH"]):
                    for file in files:
                        if file.lower().endswith(".gcode"):
                            total_gcode_files += 1

                            # Find associated STL folder
                            stl_file_name = os.path.splitext(file)[0].lower()
                            for folder in stl_folders:
                                for stl_file in folder["files"]:
                                    stl_name = os.path.splitext(stl_file["file_name"])[0].lower()
                                    if search.search_tokens_all_match(
                                        search.tokenize(stl_name), search.tokenize(stl_file_name)
                                    ):
                                        folders_with_gcode.add(folder["folder_name"])
                                        break

            # Get Moonraker printing statistics
            printing_stats = get_moonraker_printing_stats()

            # --- Activity Calendar Generation ---
            from datetime import datetime, timedelta
            import collections

            moonraker_url = app.config.get("MOONRAKER_URL")
            activity_calendar = collections.OrderedDict()
            # Default: 0 prints for each day
            today = datetime.now().date()
            start_date = today - timedelta(days=364)
            for i in range(365):
                day = start_date + timedelta(days=i)
                activity_calendar[day.strftime("%Y-%m-%d")] = 0
            # Fill with Moonraker data
            history_data = None
            if moonraker_url:
                from trinetra import moonraker

                history_data = moonraker.get_moonraker_history(moonraker_url)
            if history_data and "jobs" in history_data:
                for job in history_data["jobs"]:
                    if job.get("start_time"):
                        try:
                            d = datetime.fromtimestamp(job["start_time"]).date()
                            d_str = d.strftime("%Y-%m-%d")
                            if d_str in activity_calendar:
                                activity_calendar[d_str] += 1
                        except Exception:
                            pass
            # --- End Activity Calendar Generation ---

            stats = {
                "total_folders": total_folders,
                "total_stl_files": total_stl_files,
                "total_gcode_files": total_gcode_files,
                "folders_with_gcode": len(folders_with_gcode),
                "printing_stats": printing_stats,
                "activity_calendar": activity_calendar,
            }

            return render_template("stats.html", stats=stats)

        except Exception as e:
            app.logger.error(f"Error generating stats: {e}")
            return "Error generating statistics", 500

    def get_moonraker_printing_stats():
        """Get aggregated printing statistics from Moonraker API."""
        try:
            moonraker_url = app.config.get("MOONRAKER_URL")
            if not moonraker_url:
                return {
                    "total_prints": 0,
                    "successful_prints": 0,
                    "canceled_prints": 0,
                    "avg_print_time_hours": 0,
                    "total_filament_meters": 0,
                    "print_days": 0,
                }

            # Get all print history
            history_data = moonraker.get_moonraker_history(moonraker_url)
            if not history_data or "jobs" not in history_data:
                return {
                    "total_prints": 0,
                    "successful_prints": 0,
                    "canceled_prints": 0,
                    "avg_print_time_hours": 0,
                    "total_filament_meters": 0,
                    "print_days": 0,
                }

            jobs = history_data["jobs"]
            total_prints = len(jobs)
            successful_prints = 0
            canceled_prints = 0
            total_print_time = 0
            total_filament = 0
            print_days = set()

            for job in jobs:
                # Count successful vs canceled
                if job.get("status") == "completed":
                    successful_prints += 1
                elif job.get("status") == "cancelled":
                    canceled_prints += 1

                # Calculate print time
                if job.get("print_duration"):
                    total_print_time += job["print_duration"]

                # Calculate filament usage
                if job.get("filament_used"):
                    total_filament += job["filament_used"]

                # Track print days
                if job.get("start_time"):
                    try:
                        start_date = datetime.fromtimestamp(job["start_time"])
                        print_days.add(start_date.strftime("%Y-%m-%d"))
                    except:
                        pass

            avg_print_time_hours = (
                total_print_time / successful_prints if successful_prints > 0 else 0
            )
            total_filament_meters = (
                total_filament / 1000 if total_filament > 0 else 0
            )  # Convert mm to meters

            return {
                "total_prints": total_prints,
                "successful_prints": successful_prints,
                "canceled_prints": canceled_prints,
                "avg_print_time_hours": avg_print_time_hours / 3600,  # Convert seconds to hours
                "total_filament_meters": total_filament_meters,
                "print_days": len(print_days),
            }

        except Exception as e:
            app.logger.error(f"Error getting Moonraker printing stats: {e}")
            return {
                "total_prints": 0,
                "successful_prints": 0,
                "canceled_prints": 0,
                "avg_print_time_hours": 0,
                "total_filament_meters": 0,
                "print_days": 0,
            }

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
    app.get_moonraker_printing_stats = get_moonraker_printing_stats
    app.allowed_file = allowed_file
    app.safe_extract = safe_extract
    app.safe_join = safe_join
    app.load_config = load_config

    return app


if __name__ == "__main__":
    app = create_app()
    print(
        f"STL files: {app.config['STL_FILES_PATH']}, GCODE files: {app.config['GCODE_FILES_PATH']}"
    )

    if app.config.get("MODE", "PROD") == "DEV":
        app.run(host="0.0.0.0", port=app.config.get("PORT", 8969), debug=False)
    else:
        app.run()
