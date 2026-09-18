from __future__ import annotations

from typing import Any

from app.drawing.cad.parts.plate import build_plate
from app.drawing.schemas import HoleSpec, PartSpec
from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.templates.base import EngineeringTemplate


def _number(values: dict[str, Any], *names: str, default: float) -> float:
    for name in names:
        if name in values and values[name] is not None:
            return float(values[name])
    return default


def _holes(values: dict[str, Any]) -> list[HoleSpec]:
    result: list[HoleSpec] = []
    for item in values.get("holes", []):
        if isinstance(item, dict):
            result.append(
                HoleSpec(
                    x=float(item["x"]),
                    y=float(item["y"]),
                    diameter=float(item["diameter"]),
                    through=bool(item.get("through", True)),
                )
            )
    return result


class PlateTemplate(EngineeringTemplate):
    @property
    def name(self) -> str:
        return "plate"

    @property
    def object_type(self) -> str:
        return "part"

    @property
    def capabilities(self) -> set[str]:
        return {"geometry", "drawing", "export"}

    def _part(self, spec: EngineeringObjectSpec) -> PartSpec:
        values = {**spec.parameters, **spec.requirements}
        length = _number(values, "length", default=180.0)
        width = _number(values, "width", default=120.0)
        thickness = _number(values, "thickness", "height", default=12.0)
        return PartSpec(
            part_id="ENG-PLATE-01",
            name=spec.name,
            part_type="plate",
            length=length,
            width=width,
            height=thickness,
            material=str(values.get("material", "Aluminum 6061-T6")),
            corner_radius=float(values.get("corner_radius", 0.0) or 0.0) or None,
            holes=_holes(values),
        )

    def validate(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        try:
            part = self._part(spec)
        except (KeyError, TypeError, ValueError) as exc:
            return {"status": "failed", "errors": [str(exc)]}
        errors: list[str] = []
        for hole in part.holes:
            if hole.x >= (part.length or 0) or hole.y >= (part.width or 0):
                errors.append("plate hole center exceeds plate boundary")
            if hole.diameter >= min(part.length or 0, part.width or 0):
                errors.append("plate hole diameter exceeds plate envelope")
        return {"status": "passed" if not errors else "failed", "errors": errors}

    def build_geometry(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        part = self._part(spec)
        try:
            import cadquery as cq  # type: ignore
        except Exception:
            return {
                "backend": "fallback",
                "shape": "plate",
                "length": part.length,
                "width": part.width,
                "height": part.height,
                "hole_count": len(part.holes),
            }
        return {
            "backend": "cadquery",
            "native": build_plate(cq, part),
            "shape": "plate",
            "length": part.length,
            "width": part.width,
            "height": part.height,
            "hole_count": len(part.holes),
        }

    def build_drawing(self, spec: EngineeringObjectSpec, state: dict[str, Any]) -> dict[str, Any]:
        return {"status": "completed", "views": ["top", "front", "side"]}

    def get_bom(self, spec: EngineeringObjectSpec) -> list[dict[str, Any]]:
        values = {**spec.parameters, **spec.requirements}
        return [
            {
                "item": 1,
                "part_number": "ENG-PLATE-01",
                "description": spec.name,
                "qty": 1,
                "material": str(values.get("material", "Aluminum 6061-T6")),
            }
        ]
