"""Visual bearing assembly with races and simplified rolling elements."""

from __future__ import annotations

from math import cos, pi, sin
from typing import Any

from app.drawing.cad.parts.common import compound_workplane, cylinder_z
from app.drawing.schemas import PartSpec


def build_bearing(cq: Any, part: PartSpec) -> Any:
    outer = part.outer_diameter or part.length or 100.0
    inner = part.inner_diameter or outer * 0.5
    height = part.height or 24.0
    race_thickness = max((outer - inner) * 0.20, 3.0)
    outer_race = cylinder_z(cq, outer / 2, height, 0, 0).cut(cylinder_z(cq, outer / 2 - race_thickness, height + 2, 0, 0, -1))
    inner_race = cylinder_z(cq, inner / 2 + race_thickness, height, 0, 0).cut(cylinder_z(cq, inner / 2, height + 2, 0, 0, -1))
    roller_radius = max((outer - inner) * 0.095, 2.0)
    roller_circle = (outer + inner) / 4
    rollers = []
    for index in range(8):
        angle = 2 * pi * index / 8
        x = roller_circle * cos(angle)
        y = roller_circle * sin(angle)
        rollers.append(cylinder_z(cq, roller_radius, height * 0.55, x, y, height * 0.225))
    return compound_workplane(cq, [outer_race, inner_race, *rollers])
