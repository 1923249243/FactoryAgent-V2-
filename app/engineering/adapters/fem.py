from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def calculix_command() -> str | None:
    for name in ("ccx", "calculix", "CalculiX"):
        command = shutil.which(name)
        if command:
            return command
    return None


def _number(values: dict[str, Any], *names: str, default: float) -> float:
    for name in names:
        if values.get(name) is not None:
            try:
                return float(values[name])
            except (TypeError, ValueError):
                continue
    return default


def _file_evidence(path: Path, kind: str, note: str) -> dict[str, Any]:
    digest = None
    if path.is_file():
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
    return {
        "kind": kind,
        "reference": str(path),
        "path": str(path) if path.is_file() else None,
        "sha256": digest,
        "note": note,
    }


def _analytic_precheck(spec: Any, state: dict[str, Any]) -> dict[str, Any]:
    """Provide a labelled screening calculation, never an FEM result."""

    values = {**getattr(spec, "parameters", {}), **getattr(spec, "requirements", {})}
    selection = state.get("selection", {})
    calculations = selection.get("calculations", {})
    force = float(calculations.get("required_per_jaw_force_n", 0.0) or 0.0)
    jaw_width = _number(values, "jaw_width_mm", default=30.0)
    jaw_height = _number(values, "jaw_height_mm", default=28.0)
    area = max(jaw_width * jaw_height, 0.001)
    stress = force / area
    allowable = _number(values, "allowable_stress_mpa", default=120.0)
    return {
        "method": "analytic_screening_only",
        "scope": "uniform jaw cross-section; no mesh, contacts, bolt preload or boundary solve",
        "force_per_jaw_n": round(force, 3),
        "assumed_section_area_mm2": round(area, 3),
        "estimated_nominal_stress_mpa": round(stress, 3),
        "allowable_stress_mpa": round(allowable, 3),
        "screening_margin": round(allowable / stress, 3) if stress else None,
        "screening_pass": stress <= allowable,
    }


def _write_calculix_plan(
    path: Path,
    *,
    spec: Any,
    precheck: dict[str, Any],
) -> None:
    path.write_text(
        "** FactoryAgent CalculiX plan\n"
        "** This file is a template only; a validated mesh and boundary conditions are required.\n"
        f"** Object: {spec.name}\n"
        f"** Analytic screening stress [MPa]: {precheck['estimated_nominal_stress_mpa']}\n"
        "*HEADING\n"
        "FACTORYAGENT MESH-REQUIRED FEM TEMPLATE\n"
        "** Add *NODE, *ELEMENT, *MATERIAL, *BOUNDARY and *CLOAD from a validated mesh.\n",
        encoding="utf-8",
    )


def run_fem_adapter(
    spec: Any,
    state: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Prepare or run FEM without fabricating solver output.

    A caller can provide ``metadata.calculix_input_path`` and a local
    CalculiX executable.  Otherwise the adapter writes a complete handoff
    package and an analytic screening result with ``review_required`` status.
    """

    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    fem_dir = directory / "fem"
    fem_dir.mkdir(parents=True, exist_ok=True)
    precheck = _analytic_precheck(spec, state)
    template_path = fem_dir / "calculix_template.inp"
    plan_path = fem_dir / "analysis_plan.json"
    _write_calculix_plan(template_path, spec=spec, precheck=precheck)

    metadata = getattr(spec, "metadata", {}) or {}
    requested_input = metadata.get("calculix_input_path")
    command = calculix_command()
    solver_result: dict[str, Any] = {}
    status = "review_required"
    input_path: Path | None = None
    if requested_input and Path(str(requested_input)).is_file():
        input_path = Path(str(requested_input))
        if command:
            run_dir = fem_dir / "solver_run"
            run_dir.mkdir(parents=True, exist_ok=True)
            copied_input = run_dir / input_path.name
            copied_input.write_bytes(input_path.read_bytes())
            try:
                completed = subprocess.run(
                    [command, copied_input.stem],
                    cwd=run_dir,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                status = "completed" if completed.returncode == 0 else "failed"
                solver_result = {
                    "returncode": completed.returncode,
                    "stdout_tail": completed.stdout[-2000:],
                    "stderr_tail": completed.stderr[-2000:],
                    "run_directory": str(run_dir),
                }
            except (OSError, subprocess.TimeoutExpired) as exc:
                status = "failed"
                solver_result = {"error": str(exc)}
        else:
            solver_result = {"message": "CalculiX executable was not found"}

    plan = {
        "status": status,
        "solver_backend": "calculix" if command else "unavailable",
        "solver_available": command is not None,
        "input_mesh_provided": input_path is not None,
        "calculix_command": command,
        "analytic_precheck": precheck,
        "solver_result": solver_result,
        "warnings": [
            "解析预检不是 FEM 求解结果。",
            "没有同时提供可验证网格、边界条件和材料卡片时，不会生成应力/位移结论。",
        ],
    }
    solver_evidence: list[dict[str, Any]] = []
    if input_path is not None:
        solver_evidence.append(
            _file_evidence(
                input_path,
                "calculix_input",
                "User-provided CalculiX input; mesh and boundary conditions remain caller responsibility.",
            )
        )
    if status == "completed" and input_path is not None:
        run_dir = fem_dir / "solver_run"
        for suffix, kind in ((".frd", "calculix_result"), (".dat", "calculix_log"), (".sta", "calculix_status")):
            candidate = run_dir / f"{input_path.stem}{suffix}"
            if candidate.is_file():
                solver_evidence.append(_file_evidence(candidate, kind, "CalculiX solver output."))
    plan["provenance"] = [
        {
            "conclusion": "analytic engineering screening",
            "status": "COMPUTED",
            "source": "deterministic_analytic_precheck",
            "evidence": [],
            "details": precheck,
        },
        {
            "conclusion": "CalculiX FEM execution",
            "status": "VERIFIED" if status == "completed" else "REVIEW_REQUIRED",
            "source": "calculix" if command else "solver_unavailable",
            "evidence": solver_evidence,
            "details": {
                "solver_available": command is not None,
                "input_mesh_provided": input_path is not None,
                "solver_status": status,
            },
        },
    ]
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        **plan,
        "analysis_plan": str(plan_path),
        "calculix_template": str(template_path),
    }
