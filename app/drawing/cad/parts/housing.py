"""Parametric gearbox housing with cavity, bores, feet, ribs and cover."""

from __future__ import annotations

from typing import Any

from app.drawing.cad.parts.common import cylinder_x, cylinder_z, rounded_box
from app.drawing.schemas import PartSpec


def _vertical_hole(cq: Any, x: float, y: float, radius: float, height: float, z: float = -20.0) -> Any:
    return cylinder_z(cq, radius, height + 40, x, y, z)


def build_housing(cq: Any, part: PartSpec) -> Any:
    length = part.length or 320.0
    width = part.width or 220.0
    height = part.height or 90.0
    wall = part.wall_thickness or max(min(length, width) * 0.08, 12.0)
    radius = part.corner_radius or min(length, width) * 0.08
    outer = rounded_box(cq, length, width, height, radius)
    cavity_length = max(length - 2 * wall, 1.0)
    cavity_width = max(width - 2 * wall, 1.0)
    cavity_height = max(height - wall, 1.0)
    cavity = rounded_box(cq, cavity_length, cavity_width, cavity_height, radius * 0.55).translate((wall, wall, wall))
    shape = outer.cut(cavity)

    # Two parallel bearing seats: the large output seat and a smaller input
    # seat. Lower/upper shells meet at the shaft center plane, so each shell
    # cuts its half of the same through bore. This keeps the assembled STEP
    # mechanically coherent instead of placing the bores in unrelated faces.
    primary_bore = part.bearing_bore_diameter or min(width, height) * 0.66
    part_name = part.name.lower()
    if "lower" in part_name:
        shaft_center_z = height
    elif "upper" in part_name:
        shaft_center_z = 0.0
    else:
        shaft_center_z = height * 0.52
    bore_specs = (
        (width * 0.58, shaft_center_z, primary_bore),
        (width * 0.17, shaft_center_z, primary_bore * 0.68),
    )
    for center_y, center_z, diameter in bore_specs:
        cutter = cylinder_x(cq, diameter / 2, length + 2, -1, center_y, center_z)
        shape = shape.cut(cutter)

    bolt_diameter = part.bolt_hole_diameter or 12.0
    # Feet and their bolt holes belong to the lower casting; keeping them off
    # the upper shell makes the two exported components read as an assembly.
    foot_width = max(width * 0.12, 24.0)
    if "upper" not in part_name:
        foot_length = length * 0.78
        foot_height = max(height * 0.18, 14.0)
        front_foot = cq.Workplane("XY").box(foot_length, foot_width, foot_height, centered=(False, False, False)).translate((length * 0.11, -foot_width * 0.72, -foot_height * 0.55))
        rear_foot = cq.Workplane("XY").box(foot_length, foot_width, foot_height, centered=(False, False, False)).translate((length * 0.11, width - foot_width * 0.28, -foot_height * 0.55))
        shape = shape.union(front_foot).union(rear_foot)
        for x in (length * 0.17, length * 0.83):
            for y in (-foot_width * 0.38, width + foot_width * 0.38):
                shape = shape.cut(_vertical_hole(cq, x, y, bolt_diameter / 2, height, -foot_height))

    # External ribs are separated boxes joined to the side walls; they make
    # the housing read as a cast/machined enclosure in shaded CAD views.
    rib_width = max(length * 0.055, 12.0)
    for x in (length * 0.22, length * 0.50, length * 0.78):
        rib = cq.Workplane("XY").box(rib_width, 18, height * 0.72, centered=(False, False, False)).translate((x, -15, height * 0.10))
        shape = shape.union(rib)
        rib = cq.Workplane("XY").box(rib_width, 18, height * 0.72, centered=(False, False, False)).translate((x, width - 3, height * 0.10))
        shape = shape.union(rib)

    # Raised inspection cover with a four-hole pattern on the upper casting.
    if "lower" not in part_name:
        cover_length = length * 0.36
        cover_width = width * 0.42
        cover_height = max(height * 0.10, 8.0)
        cover = rounded_box(cq, cover_length, cover_width, cover_height, radius * 0.45).translate((length * 0.32, width * 0.29, height - 0.5))
        shape = shape.union(cover)
        for x in (length * 0.35, length * 0.65):
            for y in (width * 0.35, width * 0.65):
                shape = shape.cut(_vertical_hole(cq, x, y, max(bolt_diameter * 0.34, 3.0), height + cover_height, height - 1))
    return shape
