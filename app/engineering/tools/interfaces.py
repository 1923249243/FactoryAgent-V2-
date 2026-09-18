from __future__ import annotations

from typing import Any

from app.engineering.schemas import (
    GripperDesignRequest,
    InterfaceComparison,
    InterfaceIssue,
    MechanicalInterface,
    MotorSpec,
)


def motor_interface(motor: MotorSpec) -> MechanicalInterface:
    return MechanicalInterface(
        interface_type="motor_flange",
        shaft_diameter_mm=motor.shaft_diameter_mm,
        shaft_length_mm=motor.shaft_length_mm,
        pilot_diameter_mm=motor.pilot_diameter_mm,
        face_width_mm=motor.face_width_mm,
        face_height_mm=motor.face_height_mm,
        bolt_circle_diameter_mm=motor.bolt_circle_diameter_mm,
        bolt_count=motor.bolt_count,
        bolt_diameter_mm=motor.bolt_hole_diameter_mm,
        source=motor.source,
        verified=bool(motor.verified),
        evidence=list(motor.evidence),
    )


def gripper_input_interface(request: GripperDesignRequest) -> MechanicalInterface:
    return MechanicalInterface(
        interface_type="gripper_drive_input",
        shaft_diameter_mm=request.interface_shaft_diameter_mm,
        shaft_length_mm=20.0,
        pilot_diameter_mm=request.interface_pilot_diameter_mm,
        face_width_mm=request.interface_face_width_mm,
        face_height_mm=request.interface_face_height_mm,
        bolt_circle_diameter_mm=request.interface_bolt_circle_diameter_mm,
        bolt_count=request.interface_bolt_count,
        bolt_diameter_mm=request.interface_bolt_hole_diameter_mm,
        source="ParallelGripperTemplate",
        verified=True,
    )


def _compare_value(
    issues: list[InterfaceIssue],
    parameter: str,
    source: float | int | None,
    target: float | int | None,
    tolerance: float | None,
    *,
    adapter_supported: bool = True,
) -> None:
    if source is None or target is None:
        issues.append(
            InterfaceIssue(
                parameter=parameter,
                source=source,
                target=target,
                tolerance=tolerance,
                severity="warning",
                adapter_supported=adapter_supported,
            )
        )
        return
    passed = abs(float(source) - float(target)) <= (tolerance or 0.0)
    if not passed:
        issues.append(
            InterfaceIssue(
                parameter=parameter,
                source=source,
                target=target,
                tolerance=tolerance,
                severity="error",
                adapter_supported=adapter_supported,
            )
        )


def compare_interfaces(
    source: MechanicalInterface,
    target: MechanicalInterface,
) -> InterfaceComparison:
    """Compare two mating interfaces without asking an LLM to judge geometry."""

    issues: list[InterfaceIssue] = []
    _compare_value(issues, "shaft_diameter_mm", source.shaft_diameter_mm, target.shaft_diameter_mm, 0.20)
    _compare_value(issues, "pilot_diameter_mm", source.pilot_diameter_mm, target.pilot_diameter_mm, 0.20)
    _compare_value(issues, "bolt_circle_diameter_mm", source.bolt_circle_diameter_mm, target.bolt_circle_diameter_mm, 0.50)
    _compare_value(issues, "bolt_count", source.bolt_count, target.bolt_count, 0.0)
    _compare_value(issues, "bolt_diameter_mm", source.bolt_diameter_mm, target.bolt_diameter_mm, 0.20)
    _compare_value(issues, "face_width_mm", source.face_width_mm, target.face_width_mm, 0.50)
    _compare_value(issues, "face_height_mm", source.face_height_mm, target.face_height_mm, 0.50)
    errors = [issue for issue in issues if issue.severity == "error"]
    provenance = [
        {
            "conclusion": "mechanical interface comparison",
            "status": "COMPUTED",
            "source": "deterministic_interface_comparator",
            "evidence": source.evidence + target.evidence,
            "details": {
                "error_count": len(errors),
                "warning_count": len(issues) - len(errors),
            },
        }
    ]
    return InterfaceComparison(
        status="COMPUTED",
        compatible=not errors,
        adapter_required=bool(errors),
        issues=issues,
        source_interface=source,
        target_interface=target,
        provenance=provenance,
    )
