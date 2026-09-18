"""CadQuery geometry backend for deterministic part and assembly specs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.drawing.cad.parts.bearing import build_bearing
from app.drawing.cad.parts.common import rounded_box, variant_part
from app.drawing.cad.parts.fastener import build_fastener
from app.drawing.cad.parts.flange import build_flange
from app.drawing.cad.parts.gear import build_gear
from app.drawing.cad.parts.housing import build_housing
from app.drawing.cad.parts.motor import build_motor
from app.drawing.cad.parts.plate import build_plate
from app.drawing.cad.parts.shaft import build_shaft
from app.drawing.schemas import DrawingSpec, PartSpec


@dataclass
class PartGeometry:
    part: PartSpec
    native: Any = None
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    exploded_position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    variant: str | None = None


@dataclass
class GeometryResult:
    spec: DrawingSpec
    parts: list[PartGeometry]
    native: Any = None
    backend: str = "fallback"


def _cadquery_module() -> Any | None:
    try:
        import cadquery as cq  # type: ignore
    except Exception:
        return None
    return cq


def cadquery_available() -> bool:
    return _cadquery_module() is not None


def _build_bracket(cq: Any, part: PartSpec) -> Any:
    length = part.length or 160.0
    width = part.width or 120.0
    height = part.height or 55.0
    outer = rounded_box(cq, length, width, height, part.corner_radius or 8.0)
    cavity = cq.Workplane("XY").box(length * 0.52, width * 0.52, height * 0.62, centered=(False, False, False)).translate((length * 0.24, width * 0.24, height * 0.38))
    return outer.cut(cavity)


def _build_part(cq: Any, part: PartSpec, variant: str | None = None) -> Any:
    effective = variant_part(part, variant)
    if effective.part_type == "plate":
        return build_plate(cq, effective)
    if effective.part_type == "flange":
        return build_flange(cq, effective)
    if effective.part_type == "shaft":
        return build_shaft(cq, effective)
    if effective.part_type == "bearing":
        return build_bearing(cq, effective)
    if effective.part_type == "gear":
        return build_gear(cq, effective)
    if effective.part_type == "motor":
        return build_motor(cq, effective)
    if effective.part_type == "fastener":
        return build_fastener(cq, effective)
    if effective.part_type == "bracket":
        return _build_bracket(cq, effective)
    return build_housing(cq, effective)


def _transform(cq_shape: Any, position: tuple[float, float, float], rotation: tuple[float, float, float]) -> Any:
    result = cq_shape
    for axis, angle in zip(((1, 0, 0), (0, 1, 0), (0, 0, 1)), rotation):
        if angle:
            result = result.rotate((0, 0, 0), axis, angle)
    if any(position):
        result = result.translate(position)
    return result


def _fallback_parts(spec: DrawingSpec) -> list[PartGeometry]:
    if spec.drawing_type == "assembly" and spec.assembly:
        by_id = {part.part_id: part for part in spec.parts}
        return [
            PartGeometry(
                part=by_id[component.part_id],
                position=component.position,
                rotation=component.rotation,
                exploded_position=(
                    component.position[0] + component.exploded_offset[0],
                    component.position[1] + component.exploded_offset[1],
                    component.position[2] + component.exploded_offset[2],
                ),
                variant=component.variant,
            )
            for component in spec.assembly.components
        ]
    return [PartGeometry(part=spec.parts[0])]


def build_geometry(spec: DrawingSpec) -> GeometryResult:
    """Build one deterministic geometry graph from the validated spec."""

    cq = _cadquery_module()
    if cq is None:
        return GeometryResult(spec=spec, parts=_fallback_parts(spec))

    if spec.drawing_type == "assembly" and spec.assembly:
        by_id = {part.part_id: part for part in spec.parts}
        part_geometries: list[PartGeometry] = []
        native_shapes: list[Any] = []
        for component in spec.assembly.components:
            part = by_id[component.part_id]
            base = _build_part(cq, part, component.variant)
            transformed = _transform(base, component.position, component.rotation)
            exploded = (
                component.position[0] + component.exploded_offset[0],
                component.position[1] + component.exploded_offset[1],
                component.position[2] + component.exploded_offset[2],
            )
            part_geometries.append(
                PartGeometry(
                    part=part,
                    native=transformed,
                    position=component.position,
                    rotation=component.rotation,
                    exploded_position=exploded,
                    variant=component.variant,
                )
            )
            native_shapes.append(transformed.val() if hasattr(transformed, "val") else transformed)
        compound = cq.Compound.makeCompound(native_shapes)
        return GeometryResult(spec=spec, parts=part_geometries, native=compound, backend="cadquery")

    part = spec.parts[0]
    native = _build_part(cq, part)
    return GeometryResult(
        spec=spec,
        parts=[PartGeometry(part=part, native=native)],
        native=native,
        backend="cadquery",
    )
