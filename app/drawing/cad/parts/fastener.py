"""Simplified hex-head fastener used for visible assembly detail."""

from __future__ import annotations

from typing import Any

from app.drawing.cad.parts.common import cylinder_z
from app.drawing.schemas import PartSpec


def build_fastener(cq: Any, part: PartSpec) -> Any:
    diameter = part.outer_diameter or part.width or 12.0
    length = part.length or 30.0
    shank = cylinder_z(cq, diameter / 2, length, 0, 0)
    head = cq.Workplane("XY").polygon(6, diameter * 1.65).extrude(max(diameter * 0.42, 3.0)).translate((0, 0, length - diameter * 0.42))
    return shank.union(head)
