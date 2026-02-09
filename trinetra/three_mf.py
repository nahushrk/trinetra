"""
3MF parsing helpers with Bambu/Orca style plate extraction.

This module parses:
- Core 3MF mesh/build data from ``3D/3dmodel.model``
- Plate mappings from ``Metadata/model_settings.config`` (or Slic3r fallback)
- Per-plate slice metadata from ``Metadata/slice_info.config``
- Project-level key/value settings from ``Metadata/project_settings.config``

It also provides binary STL generation per extracted plate so the existing STL
viewer pipeline can render each plate independently.
"""

from __future__ import annotations

import io
import json
import os
import re
import struct
import zipfile
from functools import lru_cache
from math import sqrt
from typing import Any
from xml.etree import ElementTree as ET


Matrix4 = tuple[
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
    tuple[float, float, float, float],
]
Vec3 = tuple[float, float, float]
Triangle = tuple[Vec3, Vec3, Vec3]
ObjectKey = tuple[str, int]

IDENTITY_MATRIX: Matrix4 = (
    (1.0, 0.0, 0.0, 0.0),
    (0.0, 1.0, 0.0, 0.0),
    (0.0, 0.0, 1.0, 0.0),
    (0.0, 0.0, 0.0, 1.0),
)


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _safe_int(value: str | None, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_3mf_transform(value: str | None) -> Matrix4:
    """Parse a 3MF transform attribute into a 4x4 matrix."""
    if not value:
        return IDENTITY_MATRIX

    parts = value.strip().split()
    if len(parts) != 12:
        return IDENTITY_MATRIX

    nums = [_safe_float(p, 0.0) for p in parts]
    # 3MF transform order:
    # m00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32
    # with position transformed as:
    # x' = m00*x + m10*y + m20*z + m30
    # y' = m01*x + m11*y + m21*z + m31
    # z' = m02*x + m12*y + m22*z + m32
    return (
        (nums[0], nums[3], nums[6], nums[9]),
        (nums[1], nums[4], nums[7], nums[10]),
        (nums[2], nums[5], nums[8], nums[11]),
        (0.0, 0.0, 0.0, 1.0),
    )


def _mat_mul(a: Matrix4, b: Matrix4) -> Matrix4:
    out: list[list[float]] = [[0.0] * 4 for _ in range(4)]
    for r in range(4):
        for c in range(4):
            out[r][c] = (
                a[r][0] * b[0][c]
                + a[r][1] * b[1][c]
                + a[r][2] * b[2][c]
                + a[r][3] * b[3][c]
            )
    return (
        (out[0][0], out[0][1], out[0][2], out[0][3]),
        (out[1][0], out[1][1], out[1][2], out[1][3]),
        (out[2][0], out[2][1], out[2][2], out[2][3]),
        (out[3][0], out[3][1], out[3][2], out[3][3]),
    )


def _transform_point(matrix: Matrix4, point: Vec3) -> Vec3:
    x, y, z = point
    return (
        matrix[0][0] * x + matrix[0][1] * y + matrix[0][2] * z + matrix[0][3],
        matrix[1][0] * x + matrix[1][1] * y + matrix[1][2] * z + matrix[1][3],
        matrix[2][0] * x + matrix[2][1] * y + matrix[2][2] * z + matrix[2][3],
    )


def _vector_sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalize(v: Vec3) -> Vec3:
    mag = sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if mag <= 0:
        return (0.0, 0.0, 0.0)
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def _iter_children(elem: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(elem) if _local_name(child.tag) == name]


def _get_attr_local(elem: ET.Element, name: str) -> str | None:
    for key, value in elem.attrib.items():
        if _local_name(key) == name:
            return value
    return None


def _collect_metadata_elements(elem: ET.Element) -> dict[str, str]:
    out: dict[str, str] = {}
    for child in list(elem):
        if _local_name(child.tag) != "metadata":
            continue
        key = child.attrib.get("name") or child.attrib.get("key")
        if not key:
            continue
        value = child.attrib.get("value")
        if value is None:
            value = (child.text or "").strip()
        out[key] = value
    return out


def _normalize_archive_path(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def _read_zip_text(archive: zipfile.ZipFile, candidate_paths: list[str]) -> str | None:
    names = {name.lower(): name for name in archive.namelist()}
    for path in candidate_paths:
        normalized = _normalize_archive_path(path)
        real_name = names.get(normalized.lower())
        if not real_name:
            continue
        try:
            raw = archive.read(real_name)
        except KeyError:
            continue
        return raw.decode("utf-8", errors="ignore")
    return None


def _parse_key_value_config(text: str | None) -> dict[str, str]:
    if not text:
        return {}

    # Bambu/Orca project settings are JSON.
    try:
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            out: dict[str, str] = {}
            for key, value in loaded.items():
                scalar = value
                if isinstance(value, list):
                    scalar = value[0] if value else ""
                elif isinstance(value, dict):
                    scalar = json.dumps(value, ensure_ascii=True)

                if scalar is None:
                    continue
                out[str(key)] = str(scalar)
            return out
    except Exception:
        pass

    # Fallback for legacy text configs.
    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Legacy Slic3r/Prusa project config is typically prefixed with ';'
        if line.startswith(";"):
            line = line[1:].strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            continue
        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            out[key] = value

    return out


def _parse_model_settings_xml(text: str | None) -> list[dict[str, Any]]:
    if not text:
        return []

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []

    plates: list[dict[str, Any]] = []
    plate_counter = 1

    for node in list(root):
        if _local_name(node.tag) != "plate":
            continue

        plate_metadata = _collect_metadata_elements(node)
        plate_index = _safe_int(
            plate_metadata.get("plater_id")
            or plate_metadata.get("index")
            or plate_metadata.get("plate_id"),
            default=plate_counter,
        )
        plate_counter = max(plate_counter + 1, plate_index + 1)

        instance_refs: list[dict[str, int]] = []
        for child in list(node):
            if _local_name(child.tag) == "metadata":
                continue
            child_meta = _collect_metadata_elements(child)
            object_id = child_meta.get("object_id")
            if object_id is None:
                continue
            instance_refs.append(
                {
                    "object_id": _safe_int(object_id, -1),
                    "instance_id": _safe_int(child_meta.get("instance_id"), 0),
                }
            )

        plates.append(
            {
                "index": plate_index,
                "metadata": plate_metadata,
                "instance_refs": instance_refs,
            }
        )

    plates.sort(key=lambda p: p["index"])
    return plates


def _parse_slice_info_xml(text: str | None) -> dict[int, dict[str, Any]]:
    if not text:
        return {}

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}

    result: dict[int, dict[str, Any]] = {}

    for node in list(root):
        if _local_name(node.tag) != "plate":
            continue

        metadata = _collect_metadata_elements(node)
        index = _safe_int(metadata.get("index"), -1)
        if index < 0:
            continue

        filaments: list[dict[str, str]] = []
        for child in list(node):
            if _local_name(child.tag) != "filament":
                continue
            filament_meta = _collect_metadata_elements(child)
            if filament_meta:
                filaments.append(filament_meta)

        result[index] = {"metadata": metadata, "filaments": filaments}

    return result


def _parse_model_file_recursive(
    archive: zipfile.ZipFile,
    model_path: str,
    object_defs: dict[ObjectKey, dict[str, Any]],
    visited_models: set[str],
) -> dict[str, Any]:
    normalized_model_path = _normalize_archive_path(model_path)
    if normalized_model_path in visited_models:
        return {"model_metadata": {}, "build_items": []}
    visited_models.add(normalized_model_path)

    model_xml = _read_zip_text(archive, [normalized_model_path])
    if not model_xml:
        return {"model_metadata": {}, "build_items": []}

    root = ET.fromstring(model_xml)
    model_metadata = _collect_metadata_elements(root)
    build_items: list[dict[str, Any]] = []

    resources_nodes = _iter_children(root, "resources")
    if resources_nodes:
        resources = resources_nodes[0]
        for obj in _iter_children(resources, "object"):
            object_id = _safe_int(_get_attr_local(obj, "id"), -1)
            if object_id < 0:
                continue

            object_key: ObjectKey = (normalized_model_path, object_id)
            obj_meta = _collect_metadata_elements(obj)
            vertices: list[Vec3] = []
            triangles: list[tuple[int, int, int]] = []
            components: list[dict[str, Any]] = []

            mesh_nodes = _iter_children(obj, "mesh")
            if mesh_nodes:
                mesh = mesh_nodes[0]
                vertex_nodes = _iter_children(mesh, "vertices")
                if vertex_nodes:
                    for vertex in _iter_children(vertex_nodes[0], "vertex"):
                        vertices.append(
                            (
                                _safe_float(_get_attr_local(vertex, "x"), 0.0),
                                _safe_float(_get_attr_local(vertex, "y"), 0.0),
                                _safe_float(_get_attr_local(vertex, "z"), 0.0),
                            )
                        )
                triangle_nodes = _iter_children(mesh, "triangles")
                if triangle_nodes:
                    for tri in _iter_children(triangle_nodes[0], "triangle"):
                        triangles.append(
                            (
                                _safe_int(_get_attr_local(tri, "v1"), 0),
                                _safe_int(_get_attr_local(tri, "v2"), 0),
                                _safe_int(_get_attr_local(tri, "v3"), 0),
                            )
                        )

            component_nodes = _iter_children(obj, "components")
            if component_nodes:
                for comp in _iter_children(component_nodes[0], "component"):
                    child_object_id = _safe_int(_get_attr_local(comp, "objectid"), -1)
                    if child_object_id < 0:
                        continue

                    child_path_raw = _get_attr_local(comp, "path")
                    child_model_path = normalized_model_path
                    if child_path_raw:
                        child_model_path = _normalize_archive_path(child_path_raw)
                        _parse_model_file_recursive(
                            archive, child_model_path, object_defs, visited_models
                        )

                    components.append(
                        {
                            "object_key": (child_model_path, child_object_id),
                            "transform": parse_3mf_transform(
                                _get_attr_local(comp, "transform")
                            ),
                        }
                    )

            object_defs[object_key] = {
                "id": object_id,
                "model_path": normalized_model_path,
                "type": _get_attr_local(obj, "type") or "model",
                "metadata": obj_meta,
                "vertices": vertices,
                "triangles_idx": triangles,
                "components": components,
            }

    build_nodes = _iter_children(root, "build")
    if build_nodes:
        build = build_nodes[0]
        for idx, item in enumerate(_iter_children(build, "item")):
            object_id = _safe_int(_get_attr_local(item, "objectid"), -1)
            if object_id < 0:
                continue
            printable_raw = (_get_attr_local(item, "printable") or "1").lower()
            printable = printable_raw not in {"0", "false"}
            build_items.append(
                {
                    "seq": idx,
                    "object_id": object_id,
                    "object_key": (normalized_model_path, object_id),
                    "transform": parse_3mf_transform(_get_attr_local(item, "transform")),
                    "printable": printable,
                }
            )

    return {"model_metadata": model_metadata, "build_items": build_items}


def _flatten_object_triangles(
    object_key: ObjectKey,
    object_defs: dict[ObjectKey, dict[str, Any]],
    memo: dict[ObjectKey, list[Triangle]],
    stack: set[ObjectKey],
) -> list[Triangle]:
    if object_key in memo:
        return memo[object_key]
    if object_key in stack:
        return []
    stack.add(object_key)

    obj = object_defs.get(object_key)
    if not obj:
        stack.remove(object_key)
        memo[object_key] = []
        return []

    out: list[Triangle] = []
    vertices = obj.get("vertices", [])
    for v1, v2, v3 in obj.get("triangles_idx", []):
        if v1 >= len(vertices) or v2 >= len(vertices) or v3 >= len(vertices):
            continue
        out.append((vertices[v1], vertices[v2], vertices[v3]))

    for comp in obj.get("components", []):
        child_key = comp.get("object_key")
        if not child_key:
            continue
        child_tris = _flatten_object_triangles(child_key, object_defs, memo, stack)
        transform = comp.get("transform", IDENTITY_MATRIX)
        for t in child_tris:
            out.append(
                (
                    _transform_point(transform, t[0]),
                    _transform_point(transform, t[1]),
                    _transform_point(transform, t[2]),
                )
            )

    stack.remove(object_key)
    memo[object_key] = out
    return out


def _build_plate_triangles(
    object_defs: dict[ObjectKey, dict[str, Any]], build_items: list[dict[str, Any]]
) -> list[Triangle]:
    memo: dict[ObjectKey, list[Triangle]] = {}
    out: list[Triangle] = []

    for item in build_items:
        if not item.get("printable", True):
            continue
        object_key = item.get("object_key")
        if object_key is None:
            continue
        local_triangles = _flatten_object_triangles(object_key, object_defs, memo, set())
        transform = item.get("transform", IDENTITY_MATRIX)
        for tri in local_triangles:
            out.append(
                (
                    _transform_point(transform, tri[0]),
                    _transform_point(transform, tri[1]),
                    _transform_point(transform, tri[2]),
                )
            )
    return out


def _compute_triangle_dimensions(triangles: list[Triangle]) -> dict[str, float]:
    """Compute axis-aligned dimensions (mm) for a triangle set."""
    if not triangles:
        return {}

    min_x = float("inf")
    min_y = float("inf")
    min_z = float("inf")
    max_x = float("-inf")
    max_y = float("-inf")
    max_z = float("-inf")

    for tri in triangles:
        for x, y, z in tri:
            if x < min_x:
                min_x = x
            if y < min_y:
                min_y = y
            if z < min_z:
                min_z = z
            if x > max_x:
                max_x = x
            if y > max_y:
                max_y = y
            if z > max_z:
                max_z = z

    return {
        "x": round(max_x - min_x, 2),
        "y": round(max_y - min_y, 2),
        "z": round(max_z - min_z, 2),
    }


def _resolve_plate_build_items(
    build_items: list[dict[str, Any]],
    model_settings_plates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not build_items:
        return []

    build_by_object: dict[int, list[dict[str, Any]]] = {}
    for item in build_items:
        build_by_object.setdefault(item["object_id"], []).append(item)

    if not model_settings_plates:
        return [
            {
                "index": 1,
                "metadata": {},
                "slice_info": {},
                "filaments": [],
                "build_items": build_items,
            }
        ]

    result: list[dict[str, Any]] = []
    for plate in model_settings_plates:
        selected: list[dict[str, Any]] = []
        seen_seq: set[int] = set()

        for ref in plate.get("instance_refs", []):
            object_id = ref.get("object_id", -1)
            instance_id = ref.get("instance_id", 0)
            object_items = build_by_object.get(object_id, [])
            if not object_items:
                continue

            # Bambu-style instance ids are usually 0-based in model_settings.
            # Try both 0-based and 1-based interpretations for resilience.
            candidate = None
            if 0 <= instance_id < len(object_items):
                candidate = object_items[instance_id]
            elif 0 <= instance_id - 1 < len(object_items):
                candidate = object_items[instance_id - 1]
            else:
                candidate = object_items[0]

            seq = candidate.get("seq")
            if seq is not None and seq not in seen_seq:
                selected.append(candidate)
                seen_seq.add(seq)

        result.append(
            {
                "index": plate.get("index", 1),
                "metadata": plate.get("metadata", {}),
                "slice_info": {},
                "filaments": [],
                "build_items": selected,
            }
        )

    result.sort(key=lambda p: p["index"])
    return result


def _merge_slice_info(
    plates: list[dict[str, Any]], slice_info: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    for plate in plates:
        index = plate.get("index", -1)
        plate_slice = slice_info.get(index)
        if not plate_slice:
            continue
        plate["slice_info"] = plate_slice.get("metadata", {})
        plate["filaments"] = plate_slice.get("filaments", [])
    return plates


@lru_cache(maxsize=8)
def _parse_3mf_cached(path: str, mtime: float, file_size: int) -> dict[str, Any]:
    del mtime, file_size  # Cache invalidation key only.

    with zipfile.ZipFile(path, "r") as archive:
        model_xml = _read_zip_text(archive, ["3D/3dmodel.model"])
        if not model_xml:
            raise ValueError(f"3MF model file missing in archive: {path}")

        object_defs: dict[ObjectKey, dict[str, Any]] = {}
        model_data = _parse_model_file_recursive(
            archive, "3D/3dmodel.model", object_defs, visited_models=set()
        )
        model_settings_xml = _read_zip_text(
            archive,
            ["Metadata/model_settings.config", "Metadata/Slic3r_PE_model.config"],
        )
        slice_info_xml = _read_zip_text(archive, ["Metadata/slice_info.config"])
        project_settings_text = _read_zip_text(
            archive,
            ["Metadata/project_settings.config", "Metadata/Slic3r_PE.config"],
        )

        model_settings_plates = _parse_model_settings_xml(model_settings_xml)
        slice_info = _parse_slice_info_xml(slice_info_xml)
        project_settings = _parse_key_value_config(project_settings_text)

        resolved_plates = _resolve_plate_build_items(
            model_data["build_items"], model_settings_plates
        )
        resolved_plates = _merge_slice_info(resolved_plates, slice_info)

        for plate in resolved_plates:
            triangles = _build_plate_triangles(object_defs, plate["build_items"])
            plate["triangles"] = triangles
            plate["triangle_count"] = len(triangles)
            plate["instance_count"] = len(plate["build_items"])
            plate["object_ids"] = sorted({item["object_id"] for item in plate["build_items"]})

        # If model settings exist but produced no build match, expose one fallback plate
        if not resolved_plates:
            triangles = _build_plate_triangles(
                object_defs, model_data["build_items"]
            )
            resolved_plates = [
                {
                    "index": 1,
                    "metadata": {},
                    "slice_info": {},
                    "filaments": [],
                    "build_items": model_data["build_items"],
                    "triangles": triangles,
                    "triangle_count": len(triangles),
                    "instance_count": len(model_data["build_items"]),
                    "object_ids": sorted(
                        {item["object_id"] for item in model_data["build_items"]}
                    ),
                }
            ]

        return {
            "model_metadata": model_data["model_metadata"],
            "project_settings": project_settings,
            "plates": resolved_plates,
        }


def load_3mf_project(path: str) -> dict[str, Any]:
    """Load and parse a 3MF project with cache invalidation based on file stats."""
    stat = os.stat(path)
    return _parse_3mf_cached(path, stat.st_mtime, stat.st_size)


def project_to_summary(parsed: dict[str, Any]) -> dict[str, Any]:
    """Return JSON-serializable project summary without raw geometry payload."""
    plate_summaries: list[dict[str, Any]] = []
    for plate in parsed.get("plates", []):
        plate_summaries.append(
            {
                "index": plate.get("index", 0),
                "metadata": plate.get("metadata", {}),
                "slice_info": plate.get("slice_info", {}),
                "filaments": plate.get("filaments", []),
                "triangle_count": plate.get("triangle_count", 0),
                "instance_count": plate.get("instance_count", 0),
                "object_ids": plate.get("object_ids", []),
                "dimensions_mm": _compute_triangle_dimensions(
                    plate.get("triangles", [])
                ),
            }
        )

    return {
        "model_metadata": parsed.get("model_metadata", {}),
        "project_settings": parsed.get("project_settings", {}),
        "plates": plate_summaries,
    }


def get_plate_triangles(parsed: dict[str, Any], plate_index: int) -> list[Triangle]:
    for plate in parsed.get("plates", []):
        if _safe_int(str(plate.get("index")), -1) == plate_index:
            return plate.get("triangles", [])
    return []


def _build_binary_stl(triangles: list[Triangle], header_text: str = "") -> bytes:
    header = (header_text or "Trinetra 3MF plate").encode("ascii", errors="ignore")[:80]
    header = header.ljust(80, b"\0")

    buf = io.BytesIO()
    buf.write(header)
    buf.write(struct.pack("<I", len(triangles)))

    for tri in triangles:
        v1, v2, v3 = tri
        normal = _normalize(_cross(_vector_sub(v2, v1), _vector_sub(v3, v1)))
        buf.write(
            struct.pack(
                "<12fH",
                normal[0],
                normal[1],
                normal[2],
                v1[0],
                v1[1],
                v1[2],
                v2[0],
                v2[1],
                v2[2],
                v3[0],
                v3[1],
                v3[2],
                0,
            )
        )

    return buf.getvalue()


def build_plate_stl_bytes(
    parsed: dict[str, Any], plate_index: int, header_text: str | None = None
) -> bytes:
    triangles = get_plate_triangles(parsed, plate_index)
    if header_text is None:
        header_text = f"Trinetra plate {plate_index}"
    return _build_binary_stl(triangles, header_text=header_text)


def summarize_settings(settings: dict[str, str], max_items: int = 20) -> dict[str, str]:
    """
    Return concise, relevant project settings for UI display.

    Prefers common slicer/printer keys first, then fills with additional keys.
    """
    if not settings:
        return {}

    preferred_keys = [
        "filament_type",
        "default_filament_profile",
        "filament_colour",
        "layer_height",
        "initial_layer_print_height",
        "sparse_infill_density",
        "sparse_infill_pattern",
        "enable_support",
        "support_type",
        "support_threshold_angle",
        "nozzle_diameter",
        "curr_bed_type",
        "printer_model",
        "default_print_profile",
    ]

    ignored_patterns = [
        r"gcode",
        r"thumbnail",
        r"custom_",
        r"time_lapse",
        r"machine_start",
        r"machine_end",
        r"change_filament",
    ]

    ordered: dict[str, str] = {}
    for key in preferred_keys:
        if key in settings:
            value = settings[key]
            if not value:
                continue
            if len(value) > 120:
                continue
            ordered[key] = value
            if len(ordered) >= max_items:
                break

    # If no preferred keys were found, fall back to short relevant scalar values.
    if not ordered:
        for key, value in settings.items():
            if any(re.search(pattern, key, flags=re.IGNORECASE) for pattern in ignored_patterns):
                continue
            if not value or len(value) > 120:
                continue
            if re.search(r"(layer|filament|infill|support|printer|nozzle|bed)", key, re.IGNORECASE):
                ordered[key] = value
            if len(ordered) >= max_items:
                break

    return ordered


def summarize_model_metadata(metadata: dict[str, str], max_items: int = 8) -> dict[str, str]:
    """Keep only concise model-level metadata useful for UI."""
    if not metadata:
        return {}

    preferred = [
        "Title",
        "Application",
        "Designer",
        "CreationDate",
        "ModificationDate",
        "ProfileTitle",
        "DesignRegion",
        "License",
    ]
    out: dict[str, str] = {}
    for key in preferred:
        value = metadata.get(key)
        if value and len(value) <= 120:
            out[key] = value
        if len(out) >= max_items:
            break
    return out
