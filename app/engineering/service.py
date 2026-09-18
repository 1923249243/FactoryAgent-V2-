from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import settings
from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.pipeline import EngineeringPipeline
from app.engineering.planner import EngineeringPlanner
from app.engineering.schemas import (
    CalculationResult,
    CompatibilityResult,
    EngineeringReport,
    EngineeringRevisionRequest,
    EngineeringSimulationRequest,
    GripperDesignRequest,
    SimulationResult,
)
from app.engineering.templates.registry import get_default_registry


_DESIGN_ID = re.compile(r"^ENG-[A-F0-9]{8}$")


class EngineeringDesignNotFoundError(FileNotFoundError):
    pass


def _root() -> Path:
    root = Path(settings.engineering_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _design_id() -> str:
    return f"ENG-{uuid4().hex[:8].upper()}"


def _validate_id(design_id: str) -> str:
    if not _DESIGN_ID.fullmatch(design_id):
        raise ValueError("invalid engineering design id")
    return design_id


def design_dir(design_id: str) -> Path:
    return _root() / _validate_id(design_id)


def revision_dir(design_id: str, revision: int) -> Path:
    return design_dir(design_id) / f"revision_{revision:03d}"


def _save_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_revision(design_id: str) -> int:
    directory = design_dir(design_id)
    revisions = [
        int(item.name.removeprefix("revision_"))
        for item in directory.glob("revision_*")
        if item.is_dir() and item.name.removeprefix("revision_").isdigit()
    ]
    if not revisions:
        raise EngineeringDesignNotFoundError(design_id)
    return max(revisions)


def _run_revision(
    engineering_id: str,
    spec: EngineeringObjectSpec,
    revision: int,
    requested_capabilities: list[str] | None = None,
):
    directory = revision_dir(engineering_id, revision)
    outputs_dir = directory / "outputs"
    result = EngineeringPipeline().run(
        spec,
        engineering_id=engineering_id,
        revision=revision,
        output_dir=outputs_dir,
        requested_capabilities=requested_capabilities,
    )
    _save_json(directory / "spec.json", spec.model_dump(mode="json"))
    _save_json(directory / "result.json", result.model_dump(mode="json"))
    _save_json(directory / "selection.json", result.selection)
    _save_json(directory / "simulation.json", result.kinematics)
    _save_json(directory / "fem.json", result.fem)
    return result


def create_engineering_object(
    spec: EngineeringObjectSpec,
    requested_capabilities: list[str] | None = None,
    engineering_id: str | None = None,
) -> dict[str, Any]:
    design_id = engineering_id or _design_id()
    directory = design_dir(design_id)
    directory.mkdir(parents=True, exist_ok=True)
    revision = 1 if engineering_id is None else _latest_revision(design_id) + 1
    result = _run_revision(design_id, spec, revision, requested_capabilities)
    _save_json(
        directory / "index.json",
        {"engineering_id": design_id, "latest_revision": revision},
    )
    return result.model_dump(mode="json")


def get_engineering_design(design_id: str) -> dict[str, Any]:
    revision = _latest_revision(design_id)
    path = revision_dir(design_id, revision) / "result.json"
    if not path.exists():
        raise EngineeringDesignNotFoundError(design_id)
    return _load_json(path)


def _latest_spec(design_id: str) -> EngineeringObjectSpec:
    revision = _latest_revision(design_id)
    path = revision_dir(design_id, revision) / "spec.json"
    if not path.exists():
        raise EngineeringDesignNotFoundError(design_id)
    return EngineeringObjectSpec.model_validate(_load_json(path))


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _apply_revision_patch(spec: EngineeringObjectSpec, patch: dict[str, Any]) -> EngineeringObjectSpec:
    payload = spec.model_dump(mode="json")
    known_gripper_fields = {
        "payload_kg",
        "workpiece_mass",
        "workpiece_diameter",
        "opening_max_mm",
        "max_opening",
        "close_time_s",
        "open_time",
        "safety_factor",
    }
    direct_gripper_patch = {key: value for key, value in patch.items() if key in known_gripper_fields}
    if direct_gripper_patch and spec.template == "parallel_gripper":
        payload["requirements"] = _deep_merge(payload.get("requirements", {}), direct_gripper_patch)
        patch = {key: value for key, value in patch.items() if key not in direct_gripper_patch}
    return EngineeringObjectSpec.model_validate(_deep_merge(payload, patch))


def _number_from_prompt(prompt: str, default: float) -> float:
    match = re.search(r"(?:开口|opening)[^0-9]*(\d+(?:\.\d+)?)", prompt, re.IGNORECASE)
    return float(match.group(1)) if match else default


def revise_engineering_object(
    design_id: str,
    request: EngineeringRevisionRequest,
) -> dict[str, Any]:
    current = _latest_spec(design_id)
    if request.spec is not None:
        revised = request.spec
    elif request.patch is not None:
        revised = _apply_revision_patch(current, request.patch)
    else:
        assert request.prompt is not None
        planner = EngineeringPlanner()
        if current.template == "parallel_gripper" and "开口" in request.prompt:
            revised = _apply_revision_patch(
                current,
                {"opening_max_mm": _number_from_prompt(request.prompt, 80.0)},
            )
        else:
            planned = planner.plan(request.prompt)
            if planned.spec is None:
                raise ValueError("revision prompt did not resolve to a registered template")
            revised = planned.spec
    return create_engineering_object(
        revised,
        requested_capabilities=request.requested_capabilities or None,
        engineering_id=design_id,
    )


def simulate_engineering_object(
    design_id: str,
    request: EngineeringSimulationRequest | None = None,
) -> dict[str, Any]:
    spec = _latest_spec(design_id)
    revision = _latest_revision(design_id)
    requested = (request or EngineeringSimulationRequest()).requested_capabilities
    outputs_dir = revision_dir(design_id, revision) / "outputs"
    result = EngineeringPipeline().run(
        spec,
        engineering_id=design_id,
        revision=revision,
        output_dir=outputs_dir,
        requested_capabilities=requested,
    )
    _save_json(revision_dir(design_id, revision) / "result.json", result.model_dump(mode="json"))
    _save_json(revision_dir(design_id, revision) / "selection.json", result.selection)
    _save_json(revision_dir(design_id, revision) / "simulation.json", result.kinematics)
    _save_json(revision_dir(design_id, revision) / "fem.json", result.fem)
    return result.model_dump(mode="json")


def list_engineering_templates() -> list[dict[str, Any]]:
    return [
        {
            "name": info.name,
            "object_type": info.object_type,
            "capabilities": list(info.capabilities),
        }
        for info in get_default_registry().list_templates()
    ]


def generic_artifact(design_id: str, artifact: str) -> Path:
    revision = _latest_revision(design_id)
    names = {
        "step": "model.step",
        "stl": "model.stl",
        "drawing": "drawing.svg",
        "sheet": "sheet.svg",
        "png": "sheet.png",
        "dxf": "drawing.dxf",
        "bom": "bom.json",
        "assembly_constraints": "assembly_constraints.json",
        "freecad_recipe": "freecad_assembly.py",
        "fem_plan": "fem/analysis_plan.json",
        "fem_template": "fem/calculix_template.inp",
        "provenance": "provenance.json",
        "report": "result.json",
        "selection": "selection.json",
        "simulation": "simulation.json",
        "spec": "spec.json",
    }
    if artifact not in names:
        raise EngineeringDesignNotFoundError(f"{design_id}/{artifact}")
    if artifact in {
        "step",
        "stl",
        "drawing",
        "sheet",
        "png",
        "dxf",
        "bom",
        "assembly_constraints",
        "freecad_recipe",
        "fem_plan",
        "fem_template",
        "provenance",
    }:
        path = revision_dir(design_id, revision) / "outputs" / names[artifact]
    else:
        path = revision_dir(design_id, revision) / names[artifact]
    if not path.is_file():
        raise EngineeringDesignNotFoundError(f"{design_id}/{artifact}")
    return path


def _legacy_spec(request: GripperDesignRequest) -> EngineeringObjectSpec:
    payload = request.model_dump(mode="json")
    name = payload.pop("name")
    return EngineeringObjectSpec(
        object_type="mechanism",
        template="parallel_gripper",
        name=name,
        requirements=payload,
        metadata={"preset": "RG80Preset"},
    )


def _copy_legacy_outputs(design_id: str) -> dict[str, str]:
    revision = _latest_revision(design_id)
    root = design_dir(design_id)
    output_dir = revision_dir(design_id, revision) / "outputs"
    root.mkdir(parents=True, exist_ok=True)
    names = {
        "step": ("model.step", "rg80_gripper.step"),
        "stl": ("model.stl", "rg80_gripper.stl"),
        "drawing": ("drawing.svg", "drawing.svg"),
        "sheet": ("sheet.svg", "sheet.svg"),
        "png": ("sheet.png", "sheet.png"),
        "dxf": ("drawing.dxf", "drawing.dxf"),
        "provenance": ("provenance.json", "provenance.json"),
    }
    outputs: dict[str, str] = {}
    for key, (source_name, legacy_name) in names.items():
        source = output_dir / source_name
        if source.is_file():
            target = root / legacy_name
            shutil.copy2(source, target)
            outputs[key] = str(target)
    return outputs


def create_gripper_design(request: GripperDesignRequest) -> dict[str, Any]:
    """Legacy adapter: converts the old request into the generic pipeline."""

    generic = create_engineering_object(_legacy_spec(request))
    design_id = generic["engineering_id"]
    outputs = _copy_legacy_outputs(design_id)
    selection = generic.get("selection", {})
    calculations = CalculationResult.model_validate(selection.get("calculations", {}))
    compatibility = CompatibilityResult.model_validate(selection.get("compatibility", {}))
    motor_imported = compatibility.verified_real_part
    simulation_payload = generic.get("kinematics", {}).get("simulation", {})
    simulation = SimulationResult.model_validate(simulation_payload)
    legacy_status = "fail" if generic["status"] == "failed" else (
        "review" if generic["status"] == "review_required" or compatibility.warnings else "pass"
    )
    report = EngineeringReport(
        design_id=design_id,
        status=legacy_status,
        agent_version="V4.1-generic-pipeline",
        design_type="gripper",
        model_name=request.name,
        cad_backend=(
            "cadquery"
            if generic.get("geometry", {}).get("backend") == "cadquery"
            else "unavailable"
        ),
        requirements=request,
        calculations=calculations,
        compatibility=compatibility,
        simulation=simulation,
        assumptions=[
            "RG-80 是 ParallelGripperTemplate 的默认参数集，不代表某个制造商的现货型号。",
            "夹持力按双指对称、库仑摩擦和静态重力一阶模型估算。",
            (
                "已导入用户提供的电机 STEP；方向、基准面和制造商性能数据仍需工程确认。"
                if motor_imported
                else "当前使用参数化概念电机；未提供可导入的真实电机 STEP。"
            ),
        ],
        outputs=outputs,
        warnings=compatibility.warnings,
        metadata={
            "component_count": generic.get("assembly", {}).get("component_count", 9),
            "motion_samples": len(simulation.samples),
            "real_motor_model_imported": motor_imported,
            "template": generic["template"],
            "preset": "RG80Preset",
        },
    )
    root = design_dir(design_id)
    _save_json(root / "report.json", report.model_dump(mode="json"))
    _save_json(root / "motion.json", simulation.model_dump(mode="json"))
    return report.model_dump(mode="json")


def get_gripper_design(design_id: str) -> dict[str, Any]:
    root_report = design_dir(design_id) / "report.json"
    if not root_report.exists():
        raise EngineeringDesignNotFoundError(design_id)
    return _load_json(root_report)


def engineering_artifact(design_id: str, artifact: str) -> Path:
    names = {
        "step": "rg80_gripper.step",
        "stl": "rg80_gripper.stl",
        "report": "report.json",
        "motion": "motion.json",
        "drawing": "drawing.svg",
        "sheet": "sheet.svg",
        "png": "sheet.png",
        "dxf": "drawing.dxf",
        "provenance": "provenance.json",
    }
    if artifact not in names:
        raise EngineeringDesignNotFoundError(f"{design_id}/{artifact}")
    path = design_dir(design_id) / names[artifact]
    if not path.is_file():
        raise EngineeringDesignNotFoundError(f"{design_id}/{artifact}")
    return path
