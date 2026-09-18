from __future__ import annotations

from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.templates.base import EngineeringTemplate


def run(
    template: EngineeringTemplate,
    spec: EngineeringObjectSpec,
    state: dict,
) -> dict:
    return template.check_interference(spec, state)
