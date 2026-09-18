from __future__ import annotations

import math

from app.engineering.adapters.motor import motor_step_status
from app.engineering.tools.interfaces import (
    compare_interfaces,
    gripper_input_interface,
    motor_interface,
)
from app.engineering.schemas import (
    CalculationResult,
    CompatibilityResult,
    GripperDesignRequest,
    InterfaceCheck,
)


GRAVITY = 9.80665
_DIAMETER_TOLERANCE_MM = 0.20
_PCD_TOLERANCE_MM = 0.50


def calculate_requirements(request: GripperDesignRequest) -> CalculationResult:
    """Calculate a conservative first-pass screw-driven gripping demand.

    The model assumes two opposed jaws, equal normal force on each jaw, a
    Coulomb friction model, and a symmetric screw mechanism. It is an
    engineering estimate, not a release calculation for a safety-critical
    machine.
    """

    total_weight_n = request.payload_kg * GRAVITY
    total_normal_force_n = total_weight_n * request.safety_factor / request.friction_coefficient
    per_jaw_force_n = total_normal_force_n / 2.0
    opening_speed_mm_s = request.opening_max_mm / request.close_time_s

    # Both jaws travel one screw lead per revolution in opposite directions.
    screw_speed_rpm = opening_speed_mm_s * 60.0 / (2.0 * request.screw_lead_mm)
    screw_torque_nm = (
        total_normal_force_n
        * (request.screw_lead_mm / 1000.0)
        / (2.0 * math.pi * request.screw_efficiency)
    )
    required_motor_torque_nm = screw_torque_nm / (
        request.transmission_ratio * request.transmission_efficiency
    )
    required_motor_power_w = required_motor_torque_nm * screw_speed_rpm * 2.0 * math.pi / 60.0

    return CalculationResult(
        gravity_m_s2=GRAVITY,
        required_total_normal_force_n=round(total_normal_force_n, 3),
        required_per_jaw_force_n=round(per_jaw_force_n, 3),
        opening_speed_mm_s=round(opening_speed_mm_s, 3),
        screw_speed_rpm=round(screw_speed_rpm, 3),
        screw_torque_nm=round(screw_torque_nm, 3),
        required_motor_torque_nm=round(required_motor_torque_nm, 3),
        required_motor_power_w=round(required_motor_power_w, 3),
        motor_torque_margin=round(
            request.motor.rated_torque_nm / required_motor_torque_nm, 3
        ),
        motor_speed_margin_rpm=round(request.motor.max_rpm - screw_speed_rpm, 3),
    )


def check_motor_interface(request: GripperDesignRequest) -> CompatibilityResult:
    motor = request.motor
    import_status = motor_step_status(motor.step_path)
    geometry_imported = bool(import_status.get("imported"))
    source_interface = motor_interface(motor)
    target_interface = gripper_input_interface(request)
    comparison = compare_interfaces(source_interface, target_interface)
    checks = [
        InterfaceCheck(
            name="shaft_diameter_mm",
            expected=request.interface_shaft_diameter_mm,
            actual=motor.shaft_diameter_mm,
            tolerance=_DIAMETER_TOLERANCE_MM,
            passed=abs(request.interface_shaft_diameter_mm - motor.shaft_diameter_mm)
            <= _DIAMETER_TOLERANCE_MM,
            note="Motor shaft must match the coupling/bore nominal diameter.",
        ),
        InterfaceCheck(
            name="pilot_diameter_mm",
            expected=request.interface_pilot_diameter_mm,
            actual=motor.pilot_diameter_mm,
            tolerance=_DIAMETER_TOLERANCE_MM,
            passed=abs(request.interface_pilot_diameter_mm - motor.pilot_diameter_mm)
            <= _DIAMETER_TOLERANCE_MM,
            note="Pilot/centering diameter must match the adapter seat.",
        ),
        InterfaceCheck(
            name="bolt_circle_diameter_mm",
            expected=request.interface_bolt_circle_diameter_mm,
            actual=motor.bolt_circle_diameter_mm,
            tolerance=_PCD_TOLERANCE_MM,
            passed=abs(
                request.interface_bolt_circle_diameter_mm - motor.bolt_circle_diameter_mm
            )
            <= _PCD_TOLERANCE_MM,
            note="Bolt circle must match the motor adapter pattern.",
        ),
        InterfaceCheck(
            name="bolt_hole_diameter_mm",
            expected=request.interface_bolt_hole_diameter_mm,
            actual=motor.bolt_hole_diameter_mm,
            tolerance=_DIAMETER_TOLERANCE_MM,
            passed=abs(request.interface_bolt_hole_diameter_mm - motor.bolt_hole_diameter_mm)
            <= _DIAMETER_TOLERANCE_MM,
            note="Hole diameter is checked as a nominal clearance interface.",
        ),
        InterfaceCheck(
            name="body_diameter_mm",
            expected=request.allowed_motor_body_diameter_mm,
            actual=motor.body_diameter_mm,
            tolerance=0.0,
            passed=motor.body_diameter_mm <= request.allowed_motor_body_diameter_mm,
            note="Motor body must stay inside the gripper envelope.",
        ),
        InterfaceCheck(
            name="body_length_mm",
            expected=request.allowed_motor_body_length_mm,
            actual=motor.body_length_mm,
            tolerance=0.0,
            passed=motor.body_length_mm <= request.allowed_motor_body_length_mm,
            note="Motor body length must stay inside the rear envelope.",
        ),
    ]
    warnings: list[str] = []
    if not motor.verified:
        warnings.append(
            "当前电机是概念/用户输入件，尚未用制造商 STEP、样本或铭牌数据验证。"
        )
    if not motor.step_path:
        warnings.append("未提供电机 STEP 文件，当前配合检查只使用接口尺寸字段。")
    elif geometry_imported:
        warnings.append(
            "已导入电机 STEP 几何；方向、基准面和制造商性能数据仍需工程确认。"
        )
    else:
        warnings.append(
            f"电机 STEP 几何未导入（{import_status.get('status')}），当前只检查接口尺寸。"
        )
    return CompatibilityResult(
        compatible=all(item.passed for item in checks) and comparison.compatible,
        verified_real_part=geometry_imported,
        checks=checks,
        warnings=warnings,
        adapter_required=comparison.adapter_required,
        issues=[item.model_dump(mode="json") for item in comparison.issues],
        source_interface=source_interface.model_dump(mode="json"),
        target_interface=target_interface.model_dump(mode="json"),
        provenance=comparison.provenance,
    )
