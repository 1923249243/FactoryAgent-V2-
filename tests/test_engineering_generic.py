from pathlib import Path

import pytest

from app.config import settings
from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.pipeline import EngineeringPipeline
from app.engineering.schemas import (
    EngineeringRevisionRequest,
    GripperDesignRequest,
)
from app.engineering.service import (
    create_engineering_object,
    create_gripper_design,
    revise_engineering_object,
)
from app.engineering.templates.base import EngineeringTemplate
from app.engineering.templates.registry import EngineeringTemplateRegistry, get_default_registry
from app.main import app
from fastapi.testclient import TestClient


client = TestClient(app)


@pytest.fixture()
def engineering_root(tmp_path, monkeypatch):
    root = tmp_path / "engineering"
    monkeypatch.setattr(settings, "engineering_dir", str(root))
    return root


def plate_spec(name: str = "Test Plate") -> EngineeringObjectSpec:
    return EngineeringObjectSpec(
        object_type="part",
        template="plate",
        name=name,
        parameters={
            "length": 180,
            "width": 120,
            "thickness": 12,
            "holes": [
                {"x": 15, "y": 15, "diameter": 10},
                {"x": 165, "y": 15, "diameter": 10},
                {"x": 165, "y": 105, "diameter": 10},
                {"x": 15, "y": 105, "diameter": 10},
            ],
        },
    )


def flange_spec(name: str = "Test Flange") -> EngineeringObjectSpec:
    return EngineeringObjectSpec(
        object_type="part",
        template="flange",
        name=name,
        parameters={
            "outer_diameter": 120,
            "inner_diameter": 50,
            "thickness": 15,
            "bolt_circle": 90,
            "bolt_count": 6,
            "bolt_diameter": 8,
        },
    )


class DummyTemplate(EngineeringTemplate):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def object_type(self) -> str:
        return "part"

    @property
    def capabilities(self) -> set[str]:
        return {"geometry"}


def test_registry_register():
    registry = EngineeringTemplateRegistry()
    registry.register(DummyTemplate())
    assert registry.get("part", "dummy") is not None
    with pytest.raises(ValueError, match="already registered"):
        registry.register(DummyTemplate())


def test_registry_lookup():
    registry = get_default_registry()
    assert registry.get("part", "plate").name == "plate"
    assert registry.get("part", "flange").name == "flange"
    assert registry.get("mechanism", "parallel_gripper").name == "parallel_gripper"


def test_registry_unknown():
    assert get_default_registry().get("mechanism", "six_axis_robot") is None


def test_template_capabilities():
    templates = get_default_registry().list_templates()
    by_name = {item.name: set(item.capabilities) for item in templates}
    assert by_name["plate"] == {"geometry", "drawing", "export"}
    assert by_name["flange"] == {"geometry", "drawing", "export"}
    assert {"geometry", "assembly", "kinematics", "interference"}.issubset(
        by_name["parallel_gripper"]
    )


def test_generic_plate_pipeline(engineering_root):
    result = create_engineering_object(plate_spec())
    assert result["object_type"] == "part"
    assert result["template"] == "plate"
    assert result["status"] == "completed"
    assert Path(result["outputs"]["step"]).exists()
    assert result["bom"][0]["part_number"] == "ENG-PLATE-01"


def test_generic_flange_pipeline(engineering_root):
    result = create_engineering_object(flange_spec())
    assert result["object_type"] == "part"
    assert result["template"] == "flange"
    assert result["status"] == "completed"
    assert result["geometry"]["hole_count"] == 6
    assert Path(result["outputs"]["drawing"]).exists()


def test_generic_gripper_pipeline(engineering_root):
    spec = EngineeringObjectSpec(
        object_type="mechanism",
        template="parallel_gripper",
        name="Generic Gripper",
        requirements={"workpiece_diameter": 60, "workpiece_mass": 8, "max_opening": 80},
    )
    result = create_engineering_object(spec)
    assert result["template"] == "parallel_gripper"
    assert result["selection"]["selection_status"] == "concept"
    assert result["kinematics"]["motion_type"] == "synchronized_prismatic_jaws"
    assert result["interference"]["status"] == "pass"


def test_pipeline_skips_unsupported_steps(engineering_root):
    result = create_engineering_object(
        plate_spec(), requested_capabilities=["geometry", "export"]
    )
    assert result["geometry"]["status"] != "skipped"
    assert result["selection"]["status"] == "skipped"
    assert result["kinematics"]["status"] == "skipped"
    assert result["outputs"]["step"]


def test_unsupported_template(engineering_root):
    spec = EngineeringObjectSpec(
        object_type="mechanism",
        template="six_axis_robot",
        name="Unsupported Robot",
    )
    result = create_engineering_object(spec)
    assert result["status"] == "unsupported"
    assert result["outputs"] == {}


def test_review_required_capability(engineering_root):
    result = create_engineering_object(
        plate_spec(), requested_capabilities=["geometry", "fem"]
    )
    assert result["status"] == "review_required"
    assert result["unsupported_capabilities"] == ["fem"]


def test_generic_revision(engineering_root):
    created = create_engineering_object(plate_spec())
    revised = revise_engineering_object(
        created["engineering_id"],
        EngineeringRevisionRequest(patch={"parameters": {"length": 220}}),
    )
    assert revised["revision"] == 2
    spec_path = engineering_root / created["engineering_id"] / "revision_002" / "spec.json"
    assert '"length": 220' in spec_path.read_text(encoding="utf-8")


def test_engineering_ids_are_isolated(engineering_root):
    first = create_engineering_object(plate_spec("First"))
    second = create_engineering_object(plate_spec("Second"))
    assert first["engineering_id"] != second["engineering_id"]
    assert first["engineering_id"] in first["outputs"]["step"]
    assert second["engineering_id"] in second["outputs"]["step"]


def test_legacy_gripper_adapter(engineering_root):
    result = create_gripper_design(GripperDesignRequest())
    assert result["agent_version"] == "V4.1-generic-pipeline"
    assert result["metadata"]["template"] == "parallel_gripper"
    assert (engineering_root / result["design_id"] / "revision_001" / "result.json").exists()
    assert Path(result["outputs"]["step"]).exists()


def test_engineering_design_api(engineering_root):
    response = client.post(
        "/engineering/designs",
        json={"prompt": "做一个180×120×12的安装板，四角Ø10孔"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object_type"] == "part"
    assert body["template"] == "plate"


def test_engineering_templates_api():
    response = client.get("/engineering/templates")
    assert response.status_code == 200
    assert {item["name"] for item in response.json()} == {
        "plate",
        "flange",
        "parallel_gripper",
    }


def test_engineering_get_design_api(engineering_root):
    created = client.post(
        "/engineering/designs",
        json={"spec": plate_spec().model_dump(mode="json")},
    ).json()
    response = client.get(f"/engineering/designs/{created['engineering_id']}")
    assert response.status_code == 200
    assert response.json()["engineering_id"] == created["engineering_id"]


def test_engineering_revise_api(engineering_root):
    created = client.post(
        "/engineering/designs",
        json={"spec": plate_spec().model_dump(mode="json")},
    ).json()
    response = client.post(
        f"/engineering/designs/{created['engineering_id']}/revise",
        json={"patch": {"parameters": {"width": 140}}},
    )
    assert response.status_code == 200
    assert response.json()["revision"] == 2


def test_engineering_simulate_api(engineering_root):
    created = client.post(
        "/engineering/designs",
        json={
            "prompt": "设计一个夹直径60mm、质量8kg、最大开口80mm的电动夹爪"
        },
    ).json()
    response = client.post(f"/engineering/designs/{created['engineering_id']}/simulate")
    assert response.status_code == 200
    body = response.json()
    assert body["kinematics"]["motion_type"] == "synchronized_prismatic_jaws"
    assert body["interference"]["status"] == "pass"
