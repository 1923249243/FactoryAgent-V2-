from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.models.result import EngineeringResult
from app.engineering.templates.base import EngineeringTemplate
from app.engineering.templates.registry import EngineeringTemplateRegistry, get_default_registry
from app.engineering.tools import (
    assembly,
    export,
    fem,
    geometry,
    interference,
    kinematics,
    reporting,
    selection,
)


_STAGES: tuple[tuple[str, str], ...] = (
    ("geometry", "geometry"),
    ("selection", "selection"),
    ("assembly", "assembly"),
    ("kinematics", "kinematics"),
    ("interference", "interference"),
    ("fem", "fem"),
    ("drawing", "drawing"),
    ("export", "export"),
)


def _provenance_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="python")
    if not isinstance(value, dict):
        return []
    records = value.get("provenance", [])
    if not isinstance(records, list):
        return []
    return [
        _plain(record)
        for record in records
        if isinstance(record, (dict, BaseModel))
    ]


def _collect_provenance(fields: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten stage evidence while removing repeated adapter records."""

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for field, _capability in _STAGES:
        for record in _provenance_records(fields.get(field, {})):
            key = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records


def _verification_status(
    fields: dict[str, dict[str, Any]],
    errors: list[str],
    unsupported: list[str],
) -> str:
    """Classify evidence quality without turning a computed check into proof."""

    if errors or unsupported:
        return "REVIEW_REQUIRED"
    for field, _capability in _STAGES:
        payload = fields.get(field, {})
        if payload.get("status") in {"failed", "fail", "review_required", "unsupported"}:
            return "REVIEW_REQUIRED"
        if payload.get("performance_status") == "REVIEW_REQUIRED":
            return "REVIEW_REQUIRED"
    fem_payload = fields.get("fem", {})
    solver_result = fem_payload.get("solver_result", {})
    if (
        fem_payload.get("status") == "completed"
        and fem_payload.get("solver_available") is True
        and solver_result.get("returncode") == 0
    ):
        return "VERIFIED"
    return "COMPUTED"


def _plain(value: Any, *, drop_native: bool = True) -> Any:
    if isinstance(value, BaseModel):
        return _plain(value.model_dump(mode="python"), drop_native=drop_native)
    if isinstance(value, dict):
        return {
            str(key): _plain(item, drop_native=drop_native)
            for key, item in value.items()
            if not (drop_native and key == "native")
        }
    if isinstance(value, (list, tuple, set)):
        return [_plain(item, drop_native=drop_native) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value


class EngineeringPipeline:
    """Capability-driven pipeline that never branches on a concrete template."""

    def __init__(self, registry: EngineeringTemplateRegistry | None = None) -> None:
        self.registry = registry or get_default_registry()

    def run(
        self,
        spec: EngineeringObjectSpec,
        engineering_id: str,
        revision: int = 1,
        output_dir: str | Path | None = None,
        requested_capabilities: list[str] | None = None,
    ) -> EngineeringResult:
        template = self.registry.get(spec.object_type, spec.template)
        if template is None:
            return EngineeringResult(
                engineering_id=engineering_id,
                object_type=spec.object_type,
                template=spec.template,
                revision=revision,
                status="unsupported",
                verification_status="REVIEW_REQUIRED",
                errors=[f"template not registered: {spec.object_type}/{spec.template}"],
                metadata={"name": spec.name},
            )

        requested = set(requested_capabilities or template.capabilities)
        if "export" in requested or "drawing" in requested:
            requested.add("geometry")
        unsupported = sorted(requested - template.capabilities)
        state: dict[str, Any] = {}
        # Internal pipeline context is consumed by the export/provenance stage
        # and is never exposed as a geometry or engineering result field.
        state["_engineering_id"] = engineering_id
        state["_template"] = template.name
        fields: dict[str, dict[str, Any]] = {
            field: {"status": "skipped", "capability": capability}
            for field, capability in _STAGES
        }
        errors: list[str] = []
        warnings: list[str] = []

        try:
            validation = template.validate(spec)
        except Exception as exc:
            validation = {"status": "failed", "errors": [str(exc)]}
        if validation.get("status") != "passed":
            errors.extend(str(item) for item in validation.get("errors", []))

        handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "geometry": lambda: geometry.run(template, spec),
            "selection": lambda: selection.run(template, spec),
            "assembly": lambda: assembly.run(template, spec),
            "kinematics": lambda: kinematics.run(template, spec),
            "interference": lambda: interference.run(template, spec, state),
            "fem": lambda: fem.run(template, spec, state, output_dir or Path(".")),
            "drawing": lambda: template.build_drawing(spec, state),
            "export": lambda: export.run(template, spec, state, output_dir or Path(".")),
        }
        if not errors:
            for field, capability in _STAGES:
                if capability not in requested:
                    continue
                if capability not in template.capabilities:
                    fields[field] = {"status": "unsupported", "capability": capability}
                    continue
                try:
                    value = handlers[capability]()
                    state[field] = value
                    normalized_value = _plain(value)
                    if isinstance(normalized_value, dict) and "status" not in normalized_value:
                        normalized_value = {"status": "completed", **normalized_value}
                    fields[field] = normalized_value
                except Exception as exc:
                    errors.append(f"{capability}: {exc}")
                    fields[field] = {"status": "failed", "error": str(exc)}

        selection_result = fields["selection"]
        for warning in selection_result.get("compatibility", {}).get("warnings", []):
            warnings.append(str(warning))
        try:
            bom = reporting.bom(template, spec)
        except Exception as exc:
            bom = []
            errors.append(f"bom: {exc}")

        stage_failed = any(
            fields[field].get("status") in {"failed", "fail"}
            for field, _capability in _STAGES
        )
        if errors or stage_failed:
            status = "failed"
        elif unsupported:
            status = "review_required"
        else:
            status = "completed"
        outputs = fields["export"] if fields["export"].get("status") != "skipped" else {}
        provenance = _collect_provenance(fields)
        verification_status = _verification_status(fields, errors, unsupported)
        outputs = {
            key: value
            for key, value in outputs.items()
            if key
            in {
                "step",
                "stl",
                "drawing",
                "sheet",
                "png",
                "dxf",
                "bom",
                "assembly_constraints",
                "freecad_recipe",
                "fcstd",
                "fem_plan",
                "fem_template",
                "provenance",
            }
            and isinstance(value, str)
        }
        provenance_path = outputs.get("provenance")
        if provenance_path:
            export.write_provenance(
                provenance_path,
                engineering_id=engineering_id,
                template=template.name,
                verification_status=verification_status,
                records=provenance,
            )
        return EngineeringResult(
            engineering_id=engineering_id,
            object_type=spec.object_type,
            template=template.name,
            revision=revision,
            status=status,
            verification_status=verification_status,
            capabilities=sorted(template.capabilities),
            validation=_plain(validation),
            geometry=fields["geometry"],
            selection=fields["selection"],
            assembly=fields["assembly"],
            kinematics=fields["kinematics"],
            interference=fields["interference"],
            fem=fields["fem"],
            drawing=fields["drawing"],
            bom=_plain(bom),
            outputs=outputs,
            provenance=provenance,
            warnings=warnings,
            errors=errors,
            unsupported_capabilities=unsupported,
            metadata={
                "name": spec.name,
                "requested_capabilities": sorted(requested),
                "preset": spec.metadata.get("preset"),
            },
        )
