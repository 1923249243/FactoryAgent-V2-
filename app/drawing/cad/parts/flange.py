"""Parametric stepped flange builder."""

from __future__ import annotations

from typing import Any

from app.drawing.cad.parts.common import rounded_box
from app.drawing.schemas import PartSpec


def build_flange(cq: Any, part: PartSpec) -> Any:
    diameter = part.outer_diameter or part.length or 120.0
    thickness = part.height or 15.0
    inner = part.inner_diameter or 0.0
    base = cq.Workplane("XY").circle(diameter / 2).extrude(thickness)
    step_diameter = diameter * 0.66
    step_height = max(thickness * 0.38, 3.0)
    step = cq.Workplane("XY").circle(step_diameter / 2).extrude(step_height).translate((0, 0, thickness))
    shape = base.union(step)
    if inner:
        shape = shape.cut(cq.Workplane("XY").circle(inner / 2).extrude(thickness + step_height + 2).translate((0, 0, -1)))
    for hole in part.holes:
        cutter = (
            cq.Workplane("XY")
            .center(hole.x - diameter / 2, hole.y - diameter / 2)
            .circle(hole.diameter / 2)
            .extrude(thickness + step_height + 2)
            .translate((0, 0, -1))
        )
        shape = shape.cut(cutter)
    # A shallow rectangular adapter pad is useful for the motor interface and
    # keeps the transition visibly different from the output flange.
    if part.slot_width:
        pad = rounded_box(cq, diameter * 0.55, diameter * 0.34, thickness * 0.55, min(part.slot_width / 2, thickness / 2))
        pad = pad.translate((-diameter * 0.275, -diameter * 0.17, thickness * 0.25))
        shape = shape.union(pad)
    return shape
