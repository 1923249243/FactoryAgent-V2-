"""Deterministic, simplified involute-like gear profile for the demo."""

from __future__ import annotations

from typing import Any

from app.drawing.cad.parts.common import gear_points
from app.drawing.schemas import PartSpec


def build_gear(cq: Any, part: PartSpec) -> Any:
    diameter = part.gear_diameter or part.outer_diameter or part.length or 160.0
    teeth = part.gear_teeth or 24
    thickness = part.height or 24.0
    bore = part.inner_diameter or diameter * 0.24
    profile = cq.Workplane("XY").polyline(gear_points(diameter, teeth)).close().extrude(thickness)
    hub = cq.Workplane("XY").circle(bore * 0.72).extrude(thickness + 8).translate((0, 0, -4))
    shape = profile.union(hub)
    shape = shape.cut(cq.Workplane("XY").circle(bore / 2).extrude(thickness + 12).translate((0, 0, -6)))
    # Light face relief leaves a visible shoulder around the hub without
    # changing the pitch diameter or tooth profile.
    relief = cq.Workplane("XY").circle(diameter * 0.36).circle(bore * 0.78).extrude(2).translate((0, 0, thickness - 2))
    return shape.cut(relief)
