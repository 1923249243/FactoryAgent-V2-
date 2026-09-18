from __future__ import annotations

from pathlib import Path

from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.templates.base import EngineeringTemplate


def run(
    template: EngineeringTemplate,
    spec: EngineeringObjectSpec,
    state: dict,
    output_dir: str | Path,
) -> dict:
    return template.run_fem(spec, state, output_dir)
