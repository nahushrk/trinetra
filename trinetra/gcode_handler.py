import configparser
import json
import re


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
        return f"{hours}h:{minutes}m:{remaining_seconds}s"
    else:
        # Otherwise, display in m:s format
        return f"{minutes}m:{remaining_seconds}s"


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
    extract_keys = {"M140", "M104", "TIME", "Filament used", "M117 Time Left"}
    metadata = {}
    file_lines = file_content.splitlines()

    for line in file_lines:
        line = line.strip()
        if "G28 ;Home" in line:
            break
        for key in extract_keys:
            if key in line:
                if key == "M117 Time Left":
                    metadata[key] = line.split("M117 Time Left", 1)[-1].strip()
                else:
                    metadata[key] = line.split(key, 1)[-1].strip()

    # Format metadata for readability - but keep original keys for consistency
    if "TIME" in metadata:
        time_value = metadata["TIME"]
        # Keep the original format as expected by tests
        if not time_value.startswith(":"):
            metadata["TIME"] = ":" + time_value

    # Keep original M104 and M140 keys as expected by tests
    # Don't transform them to Extruder_Temp and Bed_Temp

    return metadata


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
            print(f"JSON decode error: {e}")
            print(f"Cura config data: {cura_config_data[:200]}...")

    metadata = {**metadata_from_header, **metadata_from_cura}

    return metadata
