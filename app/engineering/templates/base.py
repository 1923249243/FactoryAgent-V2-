from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.engineering.models.object import EngineeringObjectSpec


class EngineeringTemplate(ABC):
    """Stable interface implemented by parts, assemblies and mechanisms."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def object_type(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def capabilities(self) -> set[str]:
        raise NotImplementedError

    def validate(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        return {"status": "passed", "errors": []}

    def build_geometry(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        return {"status": "unsupported", "capability": "geometry"}

    def build_selection(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        return {"status": "unsupported", "capability": "selection"}

    def build_assembly(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        return {"status": "unsupported", "capability": "assembly"}

    def build_kinematics(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        return {"status": "unsupported", "capability": "kinematics"}

    def check_interference(
        self,
        spec: EngineeringObjectSpec,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        return {"status": "unsupported", "capability": "interference"}

    def run_fem(
        self,
        spec: EngineeringObjectSpec,
        state: dict[str, Any],
        output_dir: str | Path,
    ) -> dict[str, Any]:
        return {"status": "unsupported", "capability": "fem"}

    def build_drawing(
        self,
        spec: EngineeringObjectSpec,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        return {"status": "unsupported", "capability": "drawing"}

    def get_bom(self, spec: EngineeringObjectSpec) -> list[dict[str, Any]]:
        return []

    def default_requirements(self) -> list[str]:
        return []
