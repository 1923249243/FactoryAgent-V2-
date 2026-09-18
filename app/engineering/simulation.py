from __future__ import annotations

from app.engineering.schemas import (
    CalculationResult,
    GripperDesignRequest,
    MotionSample,
    SimulationResult,
)
from app.engineering.adapters.dynamics import run_optional_pybullet_check


def _phase(index: int, total: int) -> str:
    if index == 0:
        return "OPEN"
    if index == total - 1:
        return "CLOSED"
    if index * 2 == total - 1:
        return "HALF_OPEN"
    return "MOVE"


def simulate_gripper(
    request: GripperDesignRequest,
    calculations: CalculationResult,
    sample_count: int = 9,
) -> SimulationResult:
    """Run a deterministic first-pass prismatic-jaw motion check."""

    sample_count = max(3, sample_count)
    samples: list[MotionSample] = []
    structural_collisions: list[str] = []
    for index in range(sample_count):
        progress = index / (sample_count - 1)
        opening = request.opening_max_mm * (1.0 - progress)
        time_s = request.close_time_s * progress
        half_opening = opening / 2.0
        collision = not (request.opening_min_mm <= opening <= request.opening_max_mm)
        if collision:
            structural_collisions.append(f"sample_{index}: opening outside stroke limits")
        samples.append(
            MotionSample(
                index=index,
                phase=_phase(index, sample_count),
                time_s=round(time_s, 4),
                opening_mm=round(opening, 4),
                left_jaw_x_mm=round(-half_opening, 4),
                right_jaw_x_mm=round(half_opening, 4),
                workpiece_contact=opening <= request.workpiece_diameter_mm,
                structural_collision=collision,
            )
        )

    speed_ok = request.motor.max_rpm >= calculations.screw_speed_rpm
    interferences: list[str] = []
    notes = [
        "运动模型为两侧同步直线移动副；未建模柔性、间隙、接触刚度和控制器动态。",
        "工件接触被视为设计目标，不等同于结构碰撞。",
    ]
    if request.workpiece_diameter_mm > request.opening_max_mm:
        interferences.append("workpiece diameter exceeds maximum opening")
    if not speed_ok:
        interferences.append("selected motor maximum speed is below required screw speed")

    status = "pass"
    if structural_collisions or interferences:
        status = "fail"
    elif not request.motor.verified or not request.motor.step_path:
        status = "review"

    return SimulationResult(
        status=status,
        samples=samples,
        max_opening_speed_mm_s=calculations.opening_speed_mm_s,
        required_screw_speed_rpm=calculations.screw_speed_rpm,
        motor_speed_sufficient=speed_ok,
        workpiece_contact_at_closed=samples[-1].workpiece_contact,
        structural_collisions=structural_collisions,
        interferences=interferences,
        notes=notes,
    )


def simulate_gripper_continuous(
    request: GripperDesignRequest,
    calculations: CalculationResult,
    sample_count: int = 41,
) -> SimulationResult:
    """Perform a dense swept-envelope check for the synchronized jaws.

    This is intentionally deterministic and kinematic: every intermediate
    pose is checked against the declared stroke and workpiece envelope.  It
    is stronger than checking only OPEN/HALF_OPEN/CLOSED, but it is not a
    substitute for a contact-dynamics or flexible-body solver.
    """

    result = simulate_gripper(request, calculations, sample_count=max(3, sample_count))
    collision_events: list[dict[str, object]] = []
    clearances: list[float] = []
    for sample in result.samples:
        lower_clearance = sample.opening_mm - request.opening_min_mm
        upper_clearance = request.opening_max_mm - sample.opening_mm
        clearances.append(max(0.0, min(lower_clearance, upper_clearance)))
        if sample.structural_collision:
            collision_events.append(
                {
                    "sample": sample.index,
                    "time_s": sample.time_s,
                    "reason": "opening_outside_declared_stroke",
                }
            )

    dynamics_check = run_optional_pybullet_check(request, result.samples)
    if dynamics_check.get("status") == "fail":
        collision_events.extend(dynamics_check.get("collisions", []))
    structural_collisions = list(result.structural_collisions)
    if collision_events and not structural_collisions:
        structural_collisions.append("continuous swept-envelope collision detected")
    notes = list(result.notes)
    notes.extend(
        [
            "连续检查覆盖了整个 OPEN→CLOSED 轨迹，而不是只检查三个关键姿态。",
            "默认后端不包含接触刚度、摩擦锥、柔性或控制器动态；PyBullet 可选。",
        ]
    )
    return result.model_copy(
        update={
            "status": "fail" if structural_collisions or result.interferences else result.status,
            "structural_collisions": structural_collisions,
            "solver_backend": str(dynamics_check.get("backend", "deterministic_swept_kinematic")),
            "solver_available": bool(dynamics_check.get("available", True)),
            "continuous_collision_checked": True,
            "swept_min_clearance_mm": round(min(clearances), 4) if clearances else None,
            "collision_events": collision_events,
            "dynamics_check": dynamics_check,
            "notes": notes,
        }
    )
