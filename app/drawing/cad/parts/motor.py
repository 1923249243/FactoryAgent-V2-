"""Compact industrial servo-motor package for the PX-2100 assembly."""

from __future__ import annotations

from typing import Any

from app.drawing.cad.parts.common import compound_workplane, cylinder_x, cylinder_z, rounded_box
from app.drawing.schemas import PartSpec


def build_motor(cq: Any, part: PartSpec) -> Any:
    length = part.length or 240.0
    width = part.width or 180.0
    height = part.height or 210.0
    body = rounded_box(cq, length, width, height, min(14.0, width / 8))
    front_diameter = part.outer_diameter or min(width, height) * 0.55
    front = cylinder_x(cq, front_diameter / 2, 20, -20, width / 2, height / 2)
    front_bore = cylinder_x(cq, front_diameter * 0.18, 28, -24, width / 2, height / 2)
    front = front.cut(front_bore)
    output_shaft = cylinder_x(cq, front_diameter * 0.13, 55, -70, width / 2, height / 2)
    rear_cap = cylinder_x(cq, width * 0.36, 18, length, width / 2, height / 2)
    terminal = rounded_box(cq, 48, 62, 32, 5).translate((length * 0.27, width * 0.62, height))
    terminal_bolts = [
        cylinder_z(cq, 4, 34, length * 0.30, width * 0.68, height),
        cylinder_z(cq, 4, 34, length * 0.30 + 32, width * 0.68, height),
    ]
    fins = [
        cq.Workplane("XY").box(length * 0.72, 6, height * 0.82, centered=(False, False, False)).translate((length * 0.14, -7, height * 0.09)),
        cq.Workplane("XY").box(length * 0.72, 6, height * 0.82, centered=(False, False, False)).translate((length * 0.14, width + 1, height * 0.09)),
    ]
    return compound_workplane(cq, [body, front, output_shaft, rear_cap, terminal, *terminal_bolts, *fins])
