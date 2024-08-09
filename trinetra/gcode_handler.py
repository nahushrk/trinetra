import configparser
import json


def yaml_config_to_dict(yaml_text):
    config = configparser.ConfigParser()

    config.read_string(yaml_text)

    config_dict = {section: dict(config.items(section)) for section in config.sections()}
    return config_dict


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


def extract_gcode_metadata_from_header(file):
    extract_keys = {"M140", "M104", "TIME", "Filament used", "M117 Time Left"}
    metadata = {}

    file_iterator = iter(file.splitlines())
    for line in file_iterator:
        line = line.strip()

        if "G28 ;Home" in line:
            break

        for key in extract_keys:
            if key in line:
                if key == "M117 Time Left":
                    metadata[key] = line.split("M117 Time Left", 1)[-1].strip()
                else:
                    metadata[key] = line.split(key, 1)[-1].strip()

    return metadata


def extract_gcode_metadata(file):
    header_lines = []
    cura_config_lines = []
    in_cura_config = False

    file_iterator = iter(file)

    for line in file_iterator:
        line = line.strip()
        if "G28 ;Home" in line:
            break
        header_lines.append(line)

    for line in file_iterator:
        line = line.strip()
        if ";End of Gcode" in line:
            in_cura_config = True
            break

    if in_cura_config:
        for line in file_iterator:
            cura_config_lines.append(line.strip())

    cura_config_data = "".join(cura_config_lines).replace(";SETTING_3 ", "").replace("\n", "")

    metadata_from_header = {}
    metadata_from_cura = {}

    if header_lines:
        metadata_from_header = extract_gcode_metadata_from_header("\n".join(header_lines))
    if cura_config_data:
        metadata_from_cura = extract_gcode_metadata_from_cura_config(json.loads(cura_config_data))

    metadata = {**metadata_from_header, **metadata_from_cura}

    return metadata
