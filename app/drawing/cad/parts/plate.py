"""Parametric plate and mounting-base builder."""

from __future__ import annotations

from typing import Any

from app.drawing.cad.parts.common import rounded_box
from app.drawing.schemas import PartSpec


def build_plate(cq: Any, part: PartSpec) -> Any:
    length = part.length or 160.0
    width = part.width or 100.0
    height = part.height or 12.0
    shape = rounded_box(cq, length, width, height, part.corner_radius or 0.0)
    for hole in part.holes:
        cutter = (
            cq.Workplane("XY")
            .center(hole.x, hole.y)
            .circle(hole.diameter / 2)
            .extrude(height + 2)
            .translate((0, 0, -1))
        )
        shape = shape.cut(cutter)
    return shape
