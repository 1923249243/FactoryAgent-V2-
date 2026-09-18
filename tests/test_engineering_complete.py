from pathlib import Path

import pytest

from app.config import settings
from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.service import create_engineering_object
from app.engineering.simulation import simulate_gripper_continuous
from app.engineering.schemas import GripperDesignRequest
from app.engineering.calculator import calculate_requirements


@pytest.fixture()
def engineering_root(tmp_path, monkeypatch):
    root = tmp_path / "engineering"
    monkeypatch.setattr(settings, "engineering_dir", str(root))
    return root


def test_full_generic_export_bundle(engineering_root):
    spec = EngineeringObjectSpec(
        object_type="part",
        template="plate",
        name="Export Bundle Plate",
        parameters={"length": 180, "width": 120, "thickness": 12},
    )
    result = create_engineering_object(spec)
    for key in ("step", "stl", "drawing", "sheet", "png", "dxf", "bom"):
        path = Path(result["outputs"][key])
        assert path.is_file() and path.stat().st_size > 50
    try:
        from PIL import Image

        with Image.open(result["outputs"]["png"]) as image:
            assert image.size == (1600, 1000)
    except ImportError:
        pytest.skip("Pillow is optional")


def test_gripper_runs_continuous_sweep_and_writes_handoffs(engineering_root):
    spec = EngineeringObjectSpec(
        object_type="mechanism",
        template="parallel_gripper",
        name="Complete Gripper",
        requirements={"workpiece_diameter": 60, "workpiece_mass": 8, "max_opening": 80},
    )
    result = create_engineering_object(spec)
    simulation = result["kinematics"]["simulation"]
    assert simulation["continuous_collision_checked"] is True
    assert simulation["solver_backend"] == "deterministic_swept_kinematic"
    assert len(simulation["samples"]) == 41
    assert result["fem"]["status"] == "review_required"
    assert Path(result["outputs"]["assembly_constraints"]).is_file()
    assert Path(result["outputs"]["freecad_recipe"]).is_file()
    assert Path(result["outputs"]["fem_plan"]).is_file()


def test_freecad_recipe_contains_explicit_joints(engineering_root):
    spec = EngineeringObjectSpec(
        object_type="mechanism",
        template="parallel_gripper",
        name="Recipe Gripper",
    )
    result = create_engineering_object(spec)
    recipe = Path(result["outputs"]["freecad_recipe"]).read_text(encoding="utf-8")
    constraints = Path(result["outputs"]["assembly_constraints"]).read_text(encoding="utf-8")
    assert "AssemblyConstraintRecipe" in recipe
    assert "left_jaw_prismatic" in constraints
    assert "drive_screw_revolute" in constraints


def test_continuous_simulation_is_deterministic():
    request = GripperDesignRequest()
    first = simulate_gripper_continuous(request, calculate_requirements(request))
    second = simulate_gripper_continuous(request, calculate_requirements(request))
    assert first.model_dump() == second.model_dump()
    assert first.collision_events == []


def test_real_motor_step_is_imported_into_geometry(tmp_path):
    cq = pytest.importorskip("cadquery")
    motor_path = tmp_path / "manufacturer_motor.step"
    cq.exporters.export(
        cq.Workplane("XY").box(30, 30, 60),
        str(motor_path),
        exportType="STEP",
    )
    spec = EngineeringObjectSpec(
        object_type="mechanism",
        template="parallel_gripper",
        name="Real Motor Geometry",
        requirements={
            "motor": {
                "model": "DEMO-MOTOR-STEP",
                "manufacturer": "Fixture Manufacturer",
                "step_path": str(motor_path),
            }
        },
    )
    result = create_engineering_object(spec)
    assert result["geometry"]["motor_import"]["imported"] is True
    assert result["selection"]["compatibility"]["verified_real_part"] is True
    assert result["selection"]["selection_status"] == "verified_geometry"
