import hashlib
import json
from pathlib import Path

import pytest

from app.config import settings
from app.engineering.adapters.adapter import generate_mechanical_adapter
from app.engineering.catalog import get_catalog_motor, motor_catalog
from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.pipeline import EngineeringPipeline
from app.engineering.planner import EngineeringPlanner
from app.engineering.schemas import GripperDesignRequest
from app.engineering.tools.interfaces import (
    compare_interfaces,
    gripper_input_interface,
    motor_interface,
)


@pytest.fixture()
def engineering_root(tmp_path, monkeypatch):
    root = tmp_path / "engineering"
    monkeypatch.setattr(settings, "engineering_dir", str(root))
    return root


def test_interface_comparator_reports_real_motor_mismatch():
    motor = get_catalog_motor("PKP243D02B")
    assert motor is not None
    request = GripperDesignRequest(motor=motor)
    comparison = compare_interfaces(
        motor_interface(motor),
        gripper_input_interface(request),
    )
    assert comparison.compatible is False
    assert comparison.adapter_required is True
    assert {issue.parameter for issue in comparison.issues} >= {
        "shaft_diameter_mm",
        "pilot_diameter_mm",
        "bolt_circle_diameter_mm",
    }


def test_adapter_generator_returns_plate_and_coupling():
    motor = get_catalog_motor("PKP243D02B")
    assert motor is not None
    request = GripperDesignRequest(motor=motor)
    comparison = compare_interfaces(motor_interface(motor), gripper_input_interface(request))
    adapter = generate_mechanical_adapter(
        comparison.source_interface,
        comparison.target_interface,
        comparison,
    )
    assert adapter.required is True
    assert adapter.adapter_plate is not None
    assert adapter.coupling is not None
    assert adapter.adapter_plate.source_pilot_diameter_mm == motor.pilot_diameter_mm
    assert adapter.coupling.motor_bore_diameter_mm == motor.shaft_diameter_mm


def test_catalog_contains_official_evidence_metadata():
    motors = motor_catalog()
    assert len(motors) >= 1
    motor = get_catalog_motor("oriental_motor_pkp243d02b")
    assert motor is not None
    assert motor.verified is True
    assert motor.source == "official_manufacturer_catalog"
    assert motor.step_url and motor.datasheet_url
    assert any(item["kind"] == "manufacturer_step" for item in motor.evidence)


def test_local_catalog_step_hash_matches_manifest_when_present():
    motor = get_catalog_motor("PKP243D02B")
    assert motor is not None
    step_item = next(item for item in motor.evidence if item["kind"] == "manufacturer_step")
    if not step_item.get("path"):
        pytest.skip("vendor evidence bundle is not downloaded")
    path = Path(step_item["path"])
    if not path.is_file():
        pytest.skip("vendor evidence bundle is not downloaded")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == step_item["sha256"]


def test_real_motor_pipeline_writes_adapter_and_provenance(engineering_root):
    motor = get_catalog_motor("PKP243D02B")
    assert motor is not None
    spec = EngineeringObjectSpec(
        object_type="mechanism",
        template="parallel_gripper",
        name="V4.3 Real Motor Gripper",
        requirements={"motor": motor.model_dump(mode="json")},
    )
    result = EngineeringPipeline().run(
        spec,
        engineering_id="ENG-V43TEST",
        output_dir=engineering_root / "ENG-V43TEST" / "outputs",
    )
    assert result.selection["adapter"]["required"] is True
    assert "motor_adapter_plate" in result.assembly["components"]
    assert "flexible_coupling" in result.assembly["components"]
    assert "motor_adapter" not in result.assembly["components"]
    assert result.assembly["component_count"] == len(result.assembly["components"])
    assert len(result.bom) == result.assembly["component_count"]
    assert result.verification_status == "REVIEW_REQUIRED"
    provenance_path = Path(result.outputs["provenance"])
    payload = json.loads(provenance_path.read_text(encoding="utf-8"))
    assert payload["verification_status"] == "REVIEW_REQUIRED"
    assert any(item["conclusion"] == "mechanical adapter specification generated" for item in payload["records"])


def test_planner_selects_catalog_motor_for_explicit_request():
    planned = EngineeringPlanner().plan("设计一个真实电机夹爪，使用 PKP243D02B")
    assert planned.spec is not None
    assert planned.spec.template == "parallel_gripper"
    assert planned.spec.requirements["motor"]["model"] == "PKP243D02B"
