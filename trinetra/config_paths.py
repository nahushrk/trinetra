import os
from typing import Any, Dict, Tuple


def _expand_path(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def resolve_storage_paths(config: Dict[str, Any]) -> Tuple[str, str, str]:
    """
    Resolve STL, G-code, and DB paths from config.

    Backward-compatible behavior:
    - Legacy mode: when gcode_path or database_path is explicitly set,
      treat base_path as STL/models path.
    - Single-root mode: when only base_path is provided, derive:
      base_path/models, base_path/gcodes, base_path/system/trinetra.db.
    """
    base_path = _expand_path(str(config.get("base_path", "./stl_files")))
    has_base_path = bool(config.get("base_path"))
    gcode_path = config.get("gcode_path")
    database_path = config.get("database_path")

    if has_base_path and not gcode_path and not database_path:
        stl_files_path = os.path.join(base_path, "models")
        gcode_files_path = os.path.join(base_path, "gcodes")
        db_path = os.path.join(base_path, "system", "trinetra.db")
        return stl_files_path, gcode_files_path, db_path

    stl_files_path = base_path
    gcode_files_path = _expand_path(str(gcode_path or "./gcode_files"))
    db_path = _expand_path(str(database_path or "trinetra.db"))
    return stl_files_path, gcode_files_path, db_path
