import configparser
import json
import re

from trinetra.logger import get_logger

# Get logger for this module
logger = get_logger(__name__)


def yaml_config_to_dict(yaml_text):
    config = configparser.ConfigParser()
    config.read_string(yaml_text)
    return {section: dict(config.items(section)) for section in config.sections()}


def seconds_to_readable_duration(seconds: int):
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    remaining_seconds = seconds % 60

    # Determine the format
    if hours > 0:
        # If there are hours, display in h:m:s format
        return f"{hours}h {minutes}m {remaining_seconds}s"
    else:
        # Otherwise, display in m:s format
        return f"{minutes}m {remaining_seconds}s"


def extract_gcode_metadata_from_cura_config(cura_config_dict):
    metadata = {}

    global_quality_dict = yaml_config_to_dict(
        cura_config_dict["global_quality"].replace("\\n", "\n")
    )
    extruder_quality_dict = yaml_config_to_dict(
        cura_config_dict["extruder_quality"][0].replace("\\n", "\n")
    )

    extract_keys = {
        "adhesion_type",
        "layer_height",
        "support_enable",
        "support_structure",
        "support_type",
        "retraction_hop",
        "infill_sparse_density",
    }

    for key in extract_keys:
        if key in global_quality_dict.get("values", {}):
            metadata[key] = global_quality_dict["values"][key]
        elif key in extruder_quality_dict.get("values", {}):
            metadata[key] = extruder_quality_dict["values"][key]

    return metadata


def extract_gcode_metadata_from_header(file_content):
    # Only extract M140, M104, and TIME (not M117 Time Left)
    extract_keys = {"M140", "M104"}
    metadata = {}
    file_lines = file_content.splitlines()

    # Track which keys have already been extracted to ensure first occurrence only
    extracted_keys = set()

    # Find first occurrence of ;TIME:<seconds> and extract M140/M104
    time_value = None
    for line in file_lines:
        line = line.strip()
        if line.startswith(";TIME:") and time_value is None:
            try:
                seconds = int(line.split(":", 1)[1])
                time_value = seconds_to_readable_duration(seconds)
            except Exception:
                pass
        elif "G28 ;Home" in line:
            break
        else:
            # Extract M140 and M104 (only first occurrence)
            for key in extract_keys:
                if key in line and key not in extracted_keys:
                    metadata[key] = line.split(key, 1)[-1].strip()
                    extracted_keys.add(key)

    if time_value is not None:
        metadata["Time"] = time_value

    return metadata


def format_metadata_keys_for_display(metadata):
    """Format metadata keys for HTML display with proper capitalization."""
    formatted_metadata = {}

    for key, value in metadata.items():
        # Handle special cases first
        if key == "M140":
            formatted_key = "Bed Temperature"
        elif key == "M104":
            formatted_key = "Extruder Temperature"
        elif key == "Time":
            formatted_key = "Time"
        else:
            # Convert snake_case to Title Case
            # Replace underscores with spaces and capitalize each word
            formatted_key = key.replace("_", " ").title()

        formatted_metadata[formatted_key] = value

    return formatted_metadata


def extract_gcode_metadata(file):
    # Handle both string and file inputs
    if isinstance(file, str):
        content = file
    else:
        content = file.read()
        file.seek(0)  # Reset file pointer for potential future reads

    lines = content.splitlines()
    header_lines = []
    cura_config_lines = []
    in_cura_config = False

    for line in lines:
        line = line.strip()
        if "G28 ;Home" in line:
            break
        header_lines.append(line)

    # Look for Cura config after "End of Gcode"
    for line in lines:
        line = line.strip()
        if ";End of Gcode" in line:
            in_cura_config = True
            continue
        if in_cura_config and line.startswith(";SETTING_3 "):
            cura_config_lines.append(line.replace(";SETTING_3 ", ""))

    cura_config_data = "".join(cura_config_lines).replace("\n", "")

    metadata_from_header = {}
    metadata_from_cura = {}

    if header_lines:
        metadata_from_header = extract_gcode_metadata_from_header("\n".join(header_lines))
    if cura_config_data:
        try:
            cura_config_dict = json.loads(cura_config_data)
            metadata_from_cura = extract_gcode_metadata_from_cura_config(cura_config_dict)
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            logger.debug(f"Cura config data: {cura_config_data[:200]}...")

    metadata = {**metadata_from_header, **metadata_from_cura}

    # Format keys for HTML display
    return format_metadata_keys_for_display(metadata)
