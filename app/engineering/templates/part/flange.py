from __future__ import annotations

import math
from typing import Any

from app.drawing.cad.parts.flange import build_flange
from app.drawing.schemas import HoleSpec, PartSpec
from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.templates.base import EngineeringTemplate


def _number(values: dict[str, Any], *names: str, default: float) -> float:
    for name in names:
        if name in values and values[name] is not None:
            return float(values[name])
    return default


class FlangeTemplate(EngineeringTemplate):
    @property
    def name(self) -> str:
        return "flange"

    @property
    def object_type(self) -> str:
        return "part"

    @property
    def capabilities(self) -> set[str]:
        return {"geometry", "drawing", "export"}

    def _part(self, spec: EngineeringObjectSpec) -> PartSpec:
        values = {**spec.parameters, **spec.requirements}
        outer = _number(values, "outer_diameter", "diameter", default=120.0)
        inner = _number(values, "inner_diameter", "bore_diameter", default=50.0)
        thickness = _number(values, "thickness", "height", default=15.0)
        bolt_circle = _number(values, "bolt_circle", "bolt_circle_diameter", default=90.0)
        bolt_count = int(values.get("bolt_count", 6))
        bolt_diameter = _number(values, "bolt_diameter", "bolt_hole_diameter", default=8.0)
        holes = [
            HoleSpec(
                x=outer / 2.0 + bolt_circle / 2.0 * math.cos(2 * math.pi * index / bolt_count),
                y=outer / 2.0 + bolt_circle / 2.0 * math.sin(2 * math.pi * index / bolt_count),
                diameter=bolt_diameter,
            )
            for index in range(bolt_count)
        ]
        return PartSpec(
            part_id="ENG-FLANGE-01",
            name=spec.name,
            part_type="flange",
            length=outer,
            width=outer,
            height=thickness,
            material=str(values.get("material", "Aluminum 6082")),
            outer_diameter=outer,
            inner_diameter=inner,
            bolt_circle_diameter=bolt_circle,
            bolt_hole_diameter=bolt_diameter,
            holes=holes,
        )

    def validate(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        try:
            part = self._part(spec)
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            return {"status": "failed", "errors": [str(exc)]}
        errors: list[str] = []
        if (part.inner_diameter or 0) >= (part.outer_diameter or 0):
            errors.append("flange inner diameter must be smaller than outer diameter")
        if (part.bolt_circle_diameter or 0) + (part.bolt_hole_diameter or 0) >= (part.outer_diameter or 0):
            errors.append("flange bolt circle exceeds outer envelope")
        return {"status": "passed" if not errors else "failed", "errors": errors}

    def build_geometry(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        part = self._part(spec)
        try:
            import cadquery as cq  # type: ignore
        except Exception:
            return {
                "backend": "fallback",
                "shape": "flange",
                "outer_diameter": part.outer_diameter,
                "inner_diameter": part.inner_diameter,
                "thickness": part.height,
                "hole_count": len(part.holes),
            }
        return {
            "backend": "cadquery",
            "native": build_flange(cq, part),
            "shape": "flange",
            "outer_diameter": part.outer_diameter,
            "inner_diameter": part.inner_diameter,
            "thickness": part.height,
            "hole_count": len(part.holes),
        }

    def build_drawing(self, spec: EngineeringObjectSpec, state: dict[str, Any]) -> dict[str, Any]:
        return {"status": "completed", "views": ["top", "front", "side"]}

    def get_bom(self, spec: EngineeringObjectSpec) -> list[dict[str, Any]]:
        values = {**spec.parameters, **spec.requirements}
        return [
            {
                "item": 1,
                "part_number": "ENG-FLANGE-01",
                "description": spec.name,
                "qty": 1,
                "material": str(values.get("material", "Aluminum 6082")),
            }
        ]
