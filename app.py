import io
import logging
import os
import zipfile

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


config = load_config()

app = Flask(__name__)
Compress(app)

log_level = config.get("log_level", "INFO")
app.logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

app.logger.info(f"Config: {config}")

STL_FILES_PATH = os.path.expanduser(config.get("base_path", "./stl_files"))
os.makedirs(STL_FILES_PATH, exist_ok=True)

GCODE_FILES_PATH = os.path.expanduser(config.get("gcode_path", "./gcode_files"))
os.makedirs(GCODE_FILES_PATH, exist_ok=True)


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
        folder_path = safe_join(STL_FILES_PATH, folder_name)
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
            rel_path = os.path.relpath(abs_path, STL_FILES_PATH)
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

    if GCODE_FILES_PATH and os.path.isdir(GCODE_FILES_PATH):
        for stl_file in stl_files:
            stl_file_name = os.path.splitext(stl_file["file_name"])[0].lower()
            for root, dirs, files in os.walk(GCODE_FILES_PATH):
                for gcode_file in files:
                    if gcode_file.endswith(".gcode") and search.search_tokens_all_match(
                        search.tokenize(stl_file_name), search.tokenize(gcode_file.lower())
                    ):
                        abs_gcode_path = os.path.join(root, gcode_file)
                        rel_gcode_path = os.path.relpath(abs_gcode_path, GCODE_FILES_PATH)
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


@app.route("/")
def index():
    stl_files = get_stl_files(STL_FILES_PATH)
    return render_template("index.html", stl_files=stl_files)


@app.route("/gcode_files")
def gcode_files_view():
    """Display all G-code files across all folders with links to their parent folders."""
    all_gcode_files = []
    
    # Collect G-code files from the GCODE_FILES_PATH
    if GCODE_FILES_PATH and os.path.isdir(GCODE_FILES_PATH):
        for root, dirs, files in os.walk(GCODE_FILES_PATH):
            for file in files:
                if file.lower().endswith(".gcode"):
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, GCODE_FILES_PATH)
                    
                    # Try to find the associated STL file to determine the folder
                    stl_file_name = os.path.splitext(file)[0].lower()
                    folder_name = "Unknown"
                    
                    # Search for matching STL file to determine folder
                    for stl_root, stl_dirs, stl_files in os.walk(STL_FILES_PATH):
                        for stl_file in stl_files:
                            if stl_file.lower().endswith(".stl"):
                                stl_name = os.path.splitext(stl_file)[0].lower()
                                if search.search_tokens_all_match(
                                    search.tokenize(stl_name), search.tokenize(stl_file_name)
                                ):
                                    stl_rel_path = os.path.relpath(os.path.join(stl_root, stl_file), STL_FILES_PATH)
                                    folder_name = os.path.dirname(stl_rel_path) if os.path.dirname(stl_rel_path) else os.path.basename(stl_root)
                                    break
                        if folder_name != "Unknown":
                            break
                    
                    metadata = extract_gcode_metadata_from_file(abs_path)
                    all_gcode_files.append({
                        "file_name": file,
                        "rel_path": rel_path,
                        "folder_name": folder_name,
                        "metadata": metadata,
                        "base_path": "GCODE_BASE_PATH"
                    })
    
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
        return send_from_directory(STL_FILES_PATH, filename, mimetype="application/octet-stream")
    except Exception as e:
        app.logger.error(f"Error serving STL file {filename}: {e}")
        return "File not found", 404


@app.route("/file/<path:filename>")
def serve_file(filename):
    try:
        return send_from_directory(STL_FILES_PATH, filename)
    except Exception as e:
        app.logger.error(f"Error serving file {filename}: {e}")
        return "File not found", 404


@app.route("/gcode/<base_path>/<path:filename>")
def serve_gcode(base_path, filename):
    if base_path == "STL_BASE_PATH":
        _base_path = STL_FILES_PATH
    elif base_path == "GCODE_BASE_PATH":
        _base_path = GCODE_FILES_PATH
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
    for file in files:
        filename = secure_filename(file.filename)
        if not filename:
            continue
        if not allowed_file(filename):
            continue
        if filename.endswith(".zip"):
            temp_zip_path = os.path.join(STL_FILES_PATH, filename)
            file.save(temp_zip_path)
            try:
                # Create a folder with the same name as the zip file (without the extension)
                folder_name = os.path.splitext(filename)[0]
                extract_to = os.path.join(STL_FILES_PATH, folder_name)
                os.makedirs(extract_to, exist_ok=True)
                print(extract_to)

                # Extract the ZIP into the created folder
                with zipfile.ZipFile(temp_zip_path, "r") as zip_ref:
                    safe_extract(zip_ref, extract_to)
            except Exception as e:
                app.logger.error(f"Error extracting zip file: {e}")
                return jsonify({"error": "Invalid zip file"}), 400
            finally:
                os.remove(temp_zip_path)
        else:
            file_path = os.path.join(STL_FILES_PATH, filename)
            file.save(file_path)
    return jsonify({"success": True}), 200


def allowed_file(filename):
    allowed_extensions = {".stl", ".gcode", ".zip", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".pdf"}
    return os.path.splitext(filename)[1].lower() in allowed_extensions


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
        folder_path = safe_join(STL_FILES_PATH, folder_name)
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
        folder_path = safe_join(STL_FILES_PATH, folder_name)
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
        abs_path = safe_join(STL_FILES_PATH, filename)
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
        _base_path = STL_FILES_PATH
    elif base_path == "GCODE_BASE_PATH":
        _base_path = GCODE_FILES_PATH
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


@app.route("/search", methods=["GET"])
def search_route():
    query_text = request.args.get("q", "").lower()
    query_tokens = search.tokenize(query_text)
    stl_folders = get_stl_files(STL_FILES_PATH)
    filtered_folders = []
    total_matches = 0
    for folder in stl_folders:
        folder_name_tokens = search.tokenize(folder["folder_name"])
        if search.search_tokens(query_tokens, folder_name_tokens):
            filtered_folders.append(folder)
            total_matches += len(folder["files"])
        else:
            filtered_files = []
            for file in folder["files"]:
                file_name_tokens = search.tokenize(file["file_name"])
                if search.search_tokens(query_tokens, file_name_tokens):
                    filtered_files.append(file)
            if filtered_files:
                filtered_folders.append(
                    {
                        "folder_name": folder["folder_name"],
                        "top_level_folder": folder["top_level_folder"],
                        "files": filtered_files,
                    }
                )
                total_matches += len(filtered_files)
    metadata = {"matches": total_matches}
    return jsonify({"stl_files": filtered_folders, "metadata": metadata})


if __name__ == "__main__":
    print(f"STL files: {STL_FILES_PATH}, GCODE files: {GCODE_FILES_PATH}")

    if config.get("mode", "PROD") == "DEV":
        app.run(host="0.0.0.0", port=config.get("port", 8969), debug=False)
    else:
        app.run()
