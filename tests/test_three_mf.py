import os
import struct
import tempfile
import zipfile

from trinetra import three_mf


MODEL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <metadata name="Title">Synthetic Bambu Project</metadata>
  <metadata name="Application">BambuStudio</metadata>
  <resources>
    <object id="1" type="model">
      <mesh>
        <vertices>
          <vertex x="0" y="0" z="0"/>
          <vertex x="10" y="0" z="0"/>
          <vertex x="0" y="10" z="0"/>
        </vertices>
        <triangles>
          <triangle v1="0" v2="1" v3="2"/>
        </triangles>
      </mesh>
    </object>
    <object id="2" type="model">
      <mesh>
        <vertices>
          <vertex x="0" y="0" z="0"/>
          <vertex x="0" y="10" z="0"/>
          <vertex x="0" y="0" z="10"/>
        </vertices>
        <triangles>
          <triangle v1="0" v2="1" v3="2"/>
        </triangles>
      </mesh>
    </object>
  </resources>
  <build>
    <item objectid="1" transform="1 0 0 0 0 1 0 0 0 0 1 0"/>
    <item objectid="2" transform="1 0 0 20 0 1 0 0 0 0 1 0"/>
  </build>
</model>
"""

MODEL_SETTINGS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="gcode_file" value="plate_1.gcode"/>
    <model_instance>
      <metadata key="object_id" value="1"/>
      <metadata key="instance_id" value="0"/>
    </model_instance>
  </plate>
  <plate>
    <metadata key="plater_id" value="2"/>
    <metadata key="gcode_file" value="plate_2.gcode"/>
    <model_instance>
      <metadata key="object_id" value="2"/>
      <metadata key="instance_id" value="0"/>
    </model_instance>
  </plate>
</config>
"""

SLICE_INFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="1h 2m"/>
    <filament>
      <metadata key="id" value="1"/>
      <metadata key="type" value="PLA"/>
      <metadata key="used_g" value="4.2"/>
    </filament>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <metadata key="prediction" value="0h 45m"/>
    <filament>
      <metadata key="id" value="2"/>
      <metadata key="type" value="PETG"/>
      <metadata key="used_g" value="5.7"/>
    </filament>
  </plate>
</config>
"""

PROJECT_SETTINGS = """
printer_model = Bambu Lab X1 Carbon
filament_type = PLA
layer_height = 0.2
"""


def _write_synthetic_3mf(path: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("3D/3dmodel.model", MODEL_XML)
        archive.writestr("Metadata/model_settings.config", MODEL_SETTINGS_XML)
        archive.writestr("Metadata/slice_info.config", SLICE_INFO_XML)
        archive.writestr("Metadata/project_settings.config", PROJECT_SETTINGS)


def test_parse_existing_project_file():
    path = os.path.join(
        "tests",
        "test_data",
        "models",
        "pegboard-hooks-us-model_files",
        "F45 pegboard assortment.3mf",
    )
    parsed = three_mf.load_3mf_project(path)

    assert "model_metadata" in parsed
    assert "plates" in parsed
    assert len(parsed["plates"]) >= 1
    assert parsed["model_metadata"].get("Title")


def test_parse_real_bambu_swirl_lamp_file():
    path = os.path.join("tests", "test_data", "models", "swirl_lamp.3mf")
    parsed = three_mf.load_3mf_project(path)
    summary = three_mf.project_to_summary(parsed)

    assert summary["model_metadata"].get("Application", "").startswith("BambuStudio")
    assert len(summary["plates"]) == 2
    assert summary["plates"][0]["index"] == 1
    assert summary["plates"][1]["index"] == 2
    assert summary["plates"][0]["triangle_count"] > 0
    assert summary["plates"][1]["triangle_count"] > 0
    assert summary["plates"][0]["dimensions_mm"]["x"] > 0
    assert summary["plates"][0]["dimensions_mm"]["y"] > 0
    assert summary["plates"][0]["dimensions_mm"]["z"] > 0


def test_parse_bambu_style_plate_mapping_and_metadata():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "synthetic.3mf")
        _write_synthetic_3mf(path)

        parsed = three_mf.load_3mf_project(path)
        summary = three_mf.project_to_summary(parsed)

        assert len(summary["plates"]) == 2
        assert summary["plates"][0]["index"] == 1
        assert summary["plates"][1]["index"] == 2
        assert summary["plates"][0]["metadata"]["gcode_file"] == "plate_1.gcode"
        assert summary["plates"][1]["metadata"]["gcode_file"] == "plate_2.gcode"
        assert summary["plates"][0]["slice_info"]["prediction"] == "1h 2m"
        assert summary["plates"][1]["slice_info"]["prediction"] == "0h 45m"
        assert summary["plates"][0]["filaments"][0]["type"] == "PLA"
        assert summary["plates"][1]["filaments"][0]["type"] == "PETG"
        assert summary["plates"][0]["triangle_count"] == 1
        assert summary["plates"][1]["triangle_count"] == 1
        dims_plate_1 = summary["plates"][0]["dimensions_mm"]
        dims_plate_2 = summary["plates"][1]["dimensions_mm"]
        assert set(dims_plate_1.keys()) == {"x", "y", "z"}
        assert set(dims_plate_2.keys()) == {"x", "y", "z"}
        assert max(dims_plate_1["x"], dims_plate_1["y"], dims_plate_1["z"]) > 0
        assert max(dims_plate_2["x"], dims_plate_2["y"], dims_plate_2["z"]) > 0


def test_build_plate_stl_bytes():
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "synthetic.3mf")
        _write_synthetic_3mf(path)

        parsed = three_mf.load_3mf_project(path)
        stl_bytes = three_mf.build_plate_stl_bytes(parsed, 1)

        assert len(stl_bytes) > 84
        triangle_count = struct.unpack("<I", stl_bytes[80:84])[0]
        assert triangle_count == 1


def test_settings_and_model_metadata_summarization():
    raw_settings = {
        "layer_height": "0.2",
        "default_filament_profile": "Bambu PLA Basic @BBL A1",
        "sparse_infill_density": "15%",
        "machine_start_gcode": "G1 " * 500,
    }
    summarized = three_mf.summarize_settings(raw_settings, max_items=10)
    assert summarized.get("layer_height") == "0.2"
    assert summarized.get("default_filament_profile") == "Bambu PLA Basic @BBL A1"
    assert "machine_start_gcode" not in summarized

    raw_model_meta = {
        "Title": "Swirl Lamp",
        "Application": "BambuStudio",
        "Description": "x" * 5000,
        "Designer": "SoDR",
    }
    model_summary = three_mf.summarize_model_metadata(raw_model_meta)
    assert model_summary.get("Title") == "Swirl Lamp"
    assert model_summary.get("Designer") == "SoDR"
    assert "Description" not in model_summary
