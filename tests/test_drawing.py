from pathlib import Path

import pytest

from app.config import settings
from app.drawing.cad.assembly.exploded import exploded_components
from app.drawing.cad.engine import build_geometry
from app.drawing.drawing.bom import generate_bom
from app.drawing.parser import build_px2100_demo, parse_drawing_prompt
from app.drawing.service import create_drawing, get_drawing, revise_drawing
from app.drawing.sheet.renderer import _exploded_slots, validate_sheet_layout
from app.drawing.validator import DrawingValidationError, validate_drawing_spec


@pytest.fixture()
def drawing_root(tmp_path, monkeypatch):
    root = tmp_path / "drawings"
    monkeypatch.setattr(settings, "drawings_dir", str(root))
    return root


def plate_prompt() -> str:
    return "画一个180×120×12mm的6061铝板，四角Ø10通孔，孔中心距离边缘15mm"


def test_parse_plate_prompt():
    spec = parse_drawing_prompt(plate_prompt())
    part = spec.parts[0]
    assert spec.drawing_type == "part"
    assert (part.length, part.width, part.height) == (180, 120, 12)
    assert part.material == "Aluminum 6061-T6"
    assert len(part.holes) == 4


def test_create_plate(drawing_root):
    result = create_drawing(plate_prompt())
    assert result["status"] == "completed"
    assert result["drawing_type"] == "part"
    assert Path(result["outputs"]["sheet"]).exists()
    assert Path(result["outputs"]["bom"]).exists()


def test_plate_four_holes(drawing_root):
    result = create_drawing(plate_prompt())
    holes = result["spec"]["parts"][0]["holes"]
    assert {(hole["x"], hole["y"]) for hole in holes} == {
        (15.0, 15.0),
        (165.0, 15.0),
        (165.0, 105.0),
        (15.0, 105.0),
    }


def test_invalid_hole_position():
    spec = parse_drawing_prompt(plate_prompt())
    spec.parts[0].holes[0].x = 1
    with pytest.raises(DrawingValidationError, match="孔中心位置超过板材边界"):
        validate_drawing_spec(spec)


def test_export_step(drawing_root):
    result = create_drawing(plate_prompt())
    step = Path(result["outputs"]["step"])
    assert step.stat().st_size > 100
    assert step.read_text(encoding="ascii", errors="ignore").startswith("ISO-10303-21;")


def test_export_dxf(drawing_root):
    result = create_drawing(plate_prompt())
    dxf = Path(result["outputs"]["dxf"])
    assert dxf.stat().st_size > 100
    assert b"SECTION" in dxf.read_bytes()


def test_export_svg(drawing_root):
    result = create_drawing(plate_prompt())
    svg = Path(result["outputs"]["svg"])
    assert svg.read_text(encoding="utf-8").startswith("<svg")
    assert "MOUNTING PLATE" in svg.read_text(encoding="utf-8")


def test_revision_hole_diameter(drawing_root):
    created = create_drawing(plate_prompt())
    revised = revise_drawing(created["drawing_id"], "把四个孔的孔径改成12mm")
    assert revised["revision"] == 2
    assert all(hole["diameter"] == 12 for hole in revised["spec"]["parts"][0]["holes"])
    assert (drawing_root / created["drawing_id"] / "spec_v1.json").exists()
    assert (drawing_root / created["drawing_id"] / "spec_v2.json").exists()


def test_revision_thickness(drawing_root):
    created = create_drawing(plate_prompt())
    revised = revise_drawing(created["drawing_id"], "把厚度改成15mm")
    assert revised["spec"]["parts"][0]["height"] == 15


def test_create_assembly(drawing_root):
    result = create_drawing("生成 PX-2100 Modular Gear Drive 装配体")
    assert result["drawing_type"] == "assembly"
    assert len(result["spec"]["assembly"]["components"]) >= 10
    assert Path(result["outputs"]["sheet"]).exists()


def test_assembly_bom(drawing_root):
    spec = build_px2100_demo()
    bom = generate_bom(spec)
    fasteners = next(row for row in bom if row["part_number"] == "PX-2100-11")
    assert fasteners["qty"] == 2
    assert len(bom) == 11


def test_exploded_view(drawing_root):
    spec = build_px2100_demo()
    geometry = build_geometry(spec)
    exploded = exploded_components(geometry.parts)
    assert len(exploded) == len(spec.assembly.components)
    assert exploded[0].position != geometry.parts[0].position


def test_sheet_render(drawing_root):
    result = create_drawing("生成 PX-2100 装配体")
    sheet = Path(result["outputs"]["sheet"])
    png = Path(result["outputs"]["png"])
    assert sheet.stat().st_size > 1000
    assert png.stat().st_size > 0


def test_sheet_layout_validation(drawing_root):
    report = validate_sheet_layout(build_px2100_demo())
    assert report["canvas"] == {"width": 1600, "height": 1000}
    assert report["hero_panel_occupancy"] >= 0.45
    assert report["bom_font_size"] > 0
    assert report["exploded_min_gap"] > 0


def test_drawing_record_round_trip(drawing_root):
    created = create_drawing(plate_prompt())
    loaded = get_drawing(created["drawing_id"])
    assert loaded["drawing_id"] == created["drawing_id"]
    assert loaded["spec"]["revision"] == 1


def test_px2100_housing_has_bearing_bores():
    spec = build_px2100_demo()
    housings = [part for part in spec.parts if part.part_type == "housing"]
    assert {part.name for part in housings} == {"Main Housing Lower", "Main Housing Upper"}
    assert all(part.bearing_bore_diameter == 110 for part in housings)
    assert all(part.wall_thickness == 18 for part in housings)
    assert all(part.corner_radius == 20 for part in housings)


def test_px2100_has_two_gears():
    spec = build_px2100_demo()
    gear = next(part for part in spec.parts if part.part_type == "gear")
    variants = {component.variant for component in spec.assembly.components if component.part_id == gear.part_id}
    assert {"large", "small"}.issubset(variants)
    assert gear.gear_diameter == 150
    assert gear.secondary_gear_diameter == 76
    assert gear.gear_teeth == 36
    assert gear.secondary_gear_teeth == 20


def test_px2100_has_input_output_shafts():
    spec = build_px2100_demo()
    shaft = next(part for part in spec.parts if part.part_type == "shaft")
    shaft_components = {component.instance_id: component for component in spec.assembly.components if component.part_id == shaft.part_id}
    assert shaft_components["output-shaft"].variant == "output"
    assert shaft_components["input-shaft"].variant == "input"
    assert sum(section.length for section in shaft.shaft_sections) == shaft.length
    assert sum(section.length for section in shaft.secondary_shaft_sections) == shaft.secondary_length
    assert shaft.outer_diameter == 55
    assert shaft.secondary_outer_diameter == 35


def test_px2100_flange_hole_pattern():
    spec = build_px2100_demo()
    flange = next(part for part in spec.parts if part.name == "Output Flange")
    assert flange.bolt_circle_diameter == 144
    assert len(flange.holes) == 8
    center = flange.outer_diameter / 2
    radii = {round(((hole.x - center) ** 2 + (hole.y - center) ** 2) ** 0.5, 3) for hole in flange.holes}
    assert radii == {72.0}


def test_px2100_component_count():
    spec = build_px2100_demo()
    assert len(spec.assembly.components) == 15
    assert len({component.instance_id for component in spec.assembly.components}) == 15


def test_px2100_exploded_no_overlap():
    spec = build_px2100_demo()
    scenes = _exploded_slots(spec)
    assert [scene.items[0].instance_id for scene in scenes] == [
        "output-flange",
        "output-bearing",
        "output-shaft",
        "large-gear",
        "housing-lower",
        "housing-upper",
        "small-gear",
        "input-shaft",
        "input-bearing",
        "motor-adapter",
        "servo-motor",
    ]
    boxes = sorted((scene.items[0].bbox for scene in scenes), key=lambda box: box[0])
    assert all(left[2] < right[0] for left, right in zip(boxes, boxes[1:]))
