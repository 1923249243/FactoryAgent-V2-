from __future__ import annotations

from pathlib import Path
from typing import Any

from app.engineering.adapters.adapter import generate_mechanical_adapter
from app.engineering.adapters.motor import import_motor_step
from app.engineering.schemas import (
    AdapterGenerationResult,
    GripperDesignRequest,
    MechanicalInterface,
)
from app.engineering.tools.interfaces import compare_interfaces, gripper_input_interface, motor_interface


def _cadquery() -> Any | None:
    try:
        import cadquery as cq  # type: ignore
    except Exception:
        return None
    return cq


def cadquery_available() -> bool:
    return _cadquery() is not None


def _axis_x(shape: Any, cq: Any, x: float, y: float, z: float) -> Any:
    return shape.rotate((0, 0, 0), (0, 1, 0), 90).translate((x, y, z))


def _axis_cylinder(cq: Any, diameter: float, length: float, x: float, y: float, z: float) -> Any:
    cylinder = cq.Workplane("XY").cylinder(
        diameter / 2.0,
        length,
        centered=(True, True, False),
    )
    return _axis_x(cylinder, cq, x, y, z).val()


def _pattern_centers(diameter: float, count: int, center_z: float) -> list[tuple[float, float]]:
    import math

    return [
        (
            diameter / 2.0 * math.cos(2.0 * math.pi * index / count),
            center_z + diameter / 2.0 * math.sin(2.0 * math.pi * index / count),
        )
        for index in range(count)
    ]


def _build_adapter_plate(cq: Any, adapter: Any) -> Any:
    plate_spec = adapter.adapter_plate
    assert plate_spec is not None
    plate = cq.Workplane("XY").box(
        plate_spec.thickness_mm,
        plate_spec.width_mm,
        plate_spec.height_mm,
        centered=(True, True, True),
    ).translate((84.0, 0.0, 58.0))
    bore_diameter = max(
        plate_spec.target_pilot_diameter_mm,
        plate_spec.source_pilot_diameter_mm,
    )
    plate = plate.cut(_axis_cylinder(cq, bore_diameter, plate_spec.thickness_mm + 4.0, 78.0, 0.0, 58.0))
    for pcd, count, hole_diameter in (
        (
            plate_spec.target_bolt_circle_diameter_mm,
            plate_spec.target_bolt_count,
            plate_spec.target_bolt_diameter_mm,
        ),
        (
            plate_spec.source_bolt_circle_diameter_mm,
            plate_spec.source_bolt_count,
            plate_spec.source_bolt_diameter_mm,
        ),
    ):
        for y, z in _pattern_centers(pcd, count, 58.0):
            plate = plate.cut(
                _axis_cylinder(
                    cq,
                    hole_diameter,
                    plate_spec.thickness_mm + 4.0,
                    78.0,
                    y,
                    z,
                )
            )
    return plate.val()


def _build_coupling(cq: Any, coupling: Any) -> Any:
    spec = coupling.coupling
    assert spec is not None
    start_x = 62.0
    half_length = spec.length_mm / 2.0
    body = cq.Workplane("XY").cylinder(
        spec.outer_diameter_mm / 2.0,
        spec.length_mm,
        centered=(True, True, False),
    )
    body = _axis_x(body, cq, start_x, 0.0, 58.0)
    body = body.cut(
        _axis_cylinder(cq, spec.motor_bore_diameter_mm, half_length + 1.0, start_x - 1.0, 0.0, 58.0)
    )
    body = body.cut(
        _axis_cylinder(cq, spec.driven_bore_diameter_mm, half_length + 1.0, start_x + half_length - 1.0, 0.0, 58.0)
    )
    return body.val()


def _default_adapter(request: GripperDesignRequest) -> AdapterGenerationResult:
    source: MechanicalInterface = motor_interface(request.motor)
    target = gripper_input_interface(request)
    comparison = compare_interfaces(source, target)
    return generate_mechanical_adapter(source, target, comparison)


def build_rg80_compound(
    request: GripperDesignRequest,
    adapter: AdapterGenerationResult | None = None,
) -> Any | None:
    """Build a concept RG-80 assembly from deterministic primitive geometry."""

    cq = _cadquery()
    if cq is None:
        return None
    adapter = adapter or _default_adapter(request)

    parts: list[Any] = []
    base = cq.Workplane("XY").box(180, 120, 18, centered=(True, True, False))
    try:
        base = base.edges("|Z").fillet(8)
    except Exception:
        pass
    parts.append(base.val())

    # Parallel guide rails and symmetric jaw blocks.
    for y in (-38, 28):
        rail = cq.Workplane("XY").box(130, 10, 10, centered=(True, True, False)).translate((0, y, 18))
        parts.append(rail.val())

    jaw_width = 30.0
    jaw_depth = 42.0
    jaw_height = 28.0
    half_opening = request.opening_max_mm / 2.0
    left_x = -half_opening - jaw_width / 2.0
    right_x = half_opening + jaw_width / 2.0
    for x in (left_x, right_x):
        jaw = cq.Workplane("XY").box(
            jaw_width,
            jaw_depth,
            jaw_height,
            centered=(True, True, False),
        ).translate((x, 0, 28))
        parts.append(jaw.val())

    # Serrated-looking replaceable pads, kept simple so they remain robust in
    # both the visual and STEP export paths.
    pad_width = 8.0
    for x in (-half_opening - jaw_width + pad_width / 2.0, half_opening + jaw_width - pad_width / 2.0):
        pad = cq.Workplane("XY").box(pad_width, 32, 24, centered=(True, True, False)).translate((x, 0, 30))
        parts.append(pad.val())

    screw = cq.Workplane("XY").cylinder(5, 130, centered=(True, True, False))
    parts.append(_axis_x(screw, cq, -65, 0, 38).val())

    # Two simple drive wheels convey the intended motor -> screw transmission.
    for x, radius in ((58, 18), (78, 28)):
        gear = cq.Workplane("XY").cylinder(radius, 10, centered=(True, True, False))
        parts.append(_axis_x(gear, cq, x, 0, 38).val())

    if adapter.required and adapter.adapter_plate is not None:
        parts.append(_build_adapter_plate(cq, adapter))
        if adapter.coupling is not None:
            parts.append(_build_coupling(cq, adapter))
    else:
        motor_adapter = cq.Workplane("XY").cylinder(
            request.motor.pilot_diameter_mm / 2.0,
            12,
            centered=(True, True, False),
        )
        parts.append(_axis_x(motor_adapter, cq, 84, 0, 58).val())
    imported_motor = import_motor_step(
        request.motor.step_path,
        target_center=(96.0, 0.0, 58.0),
    )
    if imported_motor.imported:
        # Keep the supplied B-rep intact apart from a translation that places
        # its bounding-box centre at the concept motor mounting location.
        parts.append(imported_motor.shape.val())
    else:
        motor = cq.Workplane("XY").cylinder(
            request.motor.body_diameter_mm / 2.0,
            request.motor.body_length_mm,
            centered=(True, True, False),
        )
        parts.append(_axis_x(motor, cq, 96, 0, 58).val())
        motor_shaft = cq.Workplane("XY").cylinder(
            request.motor.shaft_diameter_mm / 2.0,
            request.motor.shaft_length_mm,
            centered=(True, True, False),
        )
        parts.append(_axis_x(motor_shaft, cq, 70, 0, 58).val())

    return cq.Compound.makeCompound(parts)


def export_rg80_cad(request: GripperDesignRequest, directory: str | Path) -> dict[str, str]:
    """Export real STEP/STL when CadQuery is installed; otherwise return no CAD paths."""

    cq = _cadquery()
    if cq is None:
        return {}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    compound = build_rg80_compound(request)
    if compound is None:
        return {}
    from cadquery import exporters  # type: ignore

    step_path = directory / "rg80_gripper.step"
    stl_path = directory / "rg80_gripper.stl"
    exporters.export(compound, str(step_path), exportType="STEP")
    exporters.export(compound, str(stl_path), exportType="STL", tolerance=0.01, angularTolerance=0.1)
    return {"step": str(step_path), "stl": str(stl_path)}
