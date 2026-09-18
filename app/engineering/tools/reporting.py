from __future__ import annotations

from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.templates.base import EngineeringTemplate


def bom(template: EngineeringTemplate, spec: EngineeringObjectSpec) -> list[dict]:
    return template.get_bom(spec)
