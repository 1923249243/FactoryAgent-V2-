from pathlib import Path

import pytest

from app.config import settings
from app.engineering.calculator import check_motor_interface, calculate_requirements
from app.engineering.schemas import GripperDesignRequest, MotorSpec
from app.engineering.service import create_gripper_design, get_gripper_design
from app.engineering.simulation import simulate_gripper
from app.main import app
from fastapi.testclient import TestClient


client = TestClient(app)


@pytest.fixture()
def engineering_root(tmp_path, monkeypatch):
    root = tmp_path / "engineering"
    monkeypatch.setattr(settings, "engineering_dir", str(root))
    return root


def test_gripper_calculation_is_deterministic():
    request = GripperDesignRequest()
    result = calculate_requirements(request)
    assert result.required_total_normal_force_n == pytest.approx(784.532, abs=0.01)
    assert result.required_per_jaw_force_n == pytest.approx(392.266, abs=0.01)
    assert result.opening_speed_mm_s == pytest.approx(100.0)
    assert result.screw_speed_rpm == pytest.approx(750.0)
    assert result.required_motor_torque_nm > 0


def test_motor_interface_mismatch_is_reported():
    request = GripperDesignRequest(motor=MotorSpec(shaft_diameter_mm=10.0))
    result = check_motor_interface(request)
    assert result.compatible is False
    assert any(check.name == "shaft_diameter_mm" and not check.passed for check in result.checks)


def test_gripper_motion_has_open_half_closed_samples():
    request = GripperDesignRequest()
    calculations = calculate_requirements(request)
    result = simulate_gripper(request, calculations)
    assert [result.samples[0].phase, result.samples[4].phase, result.samples[-1].phase] == [
        "OPEN",
        "HALF_OPEN",
        "CLOSED",
    ]
    assert result.samples[0].opening_mm == 80
    assert result.samples[-1].opening_mm == 0
    assert result.workpiece_contact_at_closed is True
    assert result.structural_collisions == []


def test_gripper_design_persists_report_and_motion(engineering_root):
    result = create_gripper_design(GripperDesignRequest())
    design_id = result["design_id"]
    assert result["design_type"] == "gripper"
    assert result["cad_backend"] in {"cadquery", "unavailable"}
    assert result["simulation"]["samples"]
    assert (engineering_root / design_id / "report.json").exists()
    assert (engineering_root / design_id / "motion.json").exists()
    assert get_gripper_design(design_id)["design_id"] == design_id
    if result["cad_backend"] == "cadquery":
        assert Path(result["outputs"]["step"]).stat().st_size > 100
        assert Path(result["outputs"]["stl"]).stat().st_size > 100


def test_gripper_api_returns_engineering_report(engineering_root):
    response = client.post(
        "/engineering/grippers",
        json={
            "payload_kg": 8,
            "workpiece_diameter_mm": 60,
            "opening_max_mm": 80,
            "close_time_s": 0.8,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "review"
    assert body["calculations"]["required_motor_torque_nm"] > 0
    assert body["simulation"]["motion_type"] == "synchronized_prismatic_jaws"
    detail = client.get(f"/engineering/grippers/{body['design_id']}")
    assert detail.status_code == 200
    assert detail.json()["design_id"] == body["design_id"]


def test_gripper_infeasible_workpiece_is_rejected_in_report(engineering_root):
    result = create_gripper_design(
        GripperDesignRequest(workpiece_diameter_mm=100, opening_max_mm=80)
    )
    assert result["status"] == "fail"
    assert "workpiece diameter exceeds maximum opening" in result["simulation"]["interferences"]
