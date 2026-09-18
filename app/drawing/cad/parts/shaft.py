"""Stepped shaft with simplified keyway geometry."""

from __future__ import annotations

from typing import Any

from app.drawing.cad.parts.common import cylinder_z
from app.drawing.schemas import PartSpec


def build_shaft(cq: Any, part: PartSpec) -> Any:
    diameter = part.outer_diameter or part.width or part.height or 30.0
    sections = [(section.length, section.diameter) for section in part.shaft_sections]
    if not sections:
        sections = [(part.length or 120.0, diameter)]
    shape = None
    cursor = 0.0
    for section_length, section_diameter in sections:
        segment = cylinder_z(cq, section_diameter / 2, section_length, 0.0, 0.0, cursor)
        shape = segment if shape is None else shape.union(segment)
        cursor += section_length

    key_width = part.slot_width or 0.0
    if key_width and shape is not None:
        key_length = max(sections[0][0] * 0.55, 8.0)
        key_depth = max(diameter * 0.18, 1.0)
        keyway = (
            cq.Workplane("XY")
            .box(key_depth, key_width, key_length, centered=(False, True, False))
            .translate((diameter / 2 - key_depth, 0, max(cursor * 0.22, 0.0)))
        )
        shape = shape.cut(keyway)
    assert shape is not None
    return shape
