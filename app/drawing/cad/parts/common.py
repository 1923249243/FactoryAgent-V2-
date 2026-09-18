"""Small CadQuery helpers shared by the parametric PX-2100 parts."""

from __future__ import annotations

from math import cos, pi, sin
from typing import Any

from app.drawing.schemas import PartSpec


def rounded_box(cq: Any, length: float, width: float, height: float, radius: float = 0.0) -> Any:
    shape = cq.Workplane("XY").box(length, width, height, centered=(False, False, False))
    if radius > 0:
        safe_radius = min(radius, length / 2 - 0.1, width / 2 - 0.1, height / 2 - 0.1)
        if safe_radius > 0:
            try:
                shape = shape.edges("|Z").fillet(safe_radius)
            except Exception:
                # The primitive remains valid on CadQuery/OCC versions where
                # this particular edge selector cannot fillet the box.
                pass
    return shape


def cylinder_x(cq: Any, radius: float, length: float, x: float, y: float, z: float) -> Any:
    return (
        cq.Workplane("XY")
        .circle(radius)
        .extrude(length)
        .rotate((0, 0, 0), (0, 1, 0), 90)
        .translate((x, y, z))
    )


def cylinder_z(cq: Any, radius: float, length: float, x: float, y: float, z: float = 0.0) -> Any:
    return cq.Workplane("XY").center(x, y).circle(radius).extrude(length).translate((0, 0, z))


def compound_workplane(cq: Any, shapes: list[Any]) -> Any:
    values = [shape.val() if hasattr(shape, "val") else shape for shape in shapes]
    return cq.Workplane("XY").newObject([cq.Compound.makeCompound(values)])


def gear_points(diameter: float, teeth: int) -> list[tuple[float, float]]:
    root = diameter * 0.44
    tip = diameter * 0.50
    points: list[tuple[float, float]] = []
    for index in range(teeth):
        base = 2 * pi * index / teeth
        for offset, radius in ((0.00, root), (0.42, root), (0.52, tip), (0.78, tip)):
            angle = base + 2 * pi * offset / teeth
            points.append((radius * cos(angle), radius * sin(angle)))
    return points


def variant_part(part: PartSpec, variant: str | None) -> PartSpec:
    """Resolve instance-level input/output and large/small variants safely."""

    if variant not in {"input", "small"}:
        return part
    updates: dict[str, Any] = {}
    if part.part_type == "bearing":
        updates = {
            "outer_diameter": part.secondary_outer_diameter or part.outer_diameter,
            "inner_diameter": part.secondary_inner_diameter or part.inner_diameter,
            "length": part.secondary_outer_diameter or part.length,
            "width": part.secondary_outer_diameter or part.width,
            "height": part.secondary_height or part.height,
        }
    elif part.part_type == "gear":
        diameter = part.secondary_gear_diameter or part.gear_diameter or part.outer_diameter
        updates = {
            "gear_diameter": diameter,
            "outer_diameter": diameter,
            "length": diameter,
            "width": diameter,
            "gear_teeth": part.secondary_gear_teeth or part.gear_teeth,
        }
    elif part.part_type == "shaft":
        diameter = part.secondary_outer_diameter or part.outer_diameter
        updates = {
            "length": part.secondary_length or part.length,
            "outer_diameter": diameter,
            "width": diameter,
            "height": diameter,
            "shaft_sections": part.secondary_shaft_sections or part.shaft_sections,
        }
    return part.model_copy(update={key: value for key, value in updates.items() if value is not None})
