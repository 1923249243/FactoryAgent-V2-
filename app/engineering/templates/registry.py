from __future__ import annotations

from dataclasses import dataclass

from app.engineering.templates.base import EngineeringTemplate


@dataclass(frozen=True)
class TemplateInfo:
    name: str
    object_type: str
    capabilities: tuple[str, ...]


class EngineeringTemplateRegistry:
    def __init__(self) -> None:
        self._templates: dict[tuple[str, str], EngineeringTemplate] = {}

    def register(self, template: EngineeringTemplate) -> None:
        key = (template.object_type, template.name)
        if key in self._templates:
            raise ValueError(f"template already registered: {template.object_type}/{template.name}")
        self._templates[key] = template

    def get(self, object_type: str, template_name: str) -> EngineeringTemplate | None:
        return self._templates.get((object_type, template_name))

    def list_templates(self) -> list[TemplateInfo]:
        return [
            TemplateInfo(
                name=template.name,
                object_type=template.object_type,
                capabilities=tuple(sorted(template.capabilities)),
            )
            for template in sorted(
                self._templates.values(), key=lambda item: (item.object_type, item.name)
            )
        ]

    def list_capabilities(self) -> dict[str, list[str]]:
        return {
            f"{info.object_type}/{info.name}": list(info.capabilities)
            for info in self.list_templates()
        }


def get_default_registry() -> EngineeringTemplateRegistry:
    # Lazy singleton keeps the base maintenance app importable without making
    # template modules part of the maintenance route.
    global _DEFAULT_REGISTRY
    try:
        return _DEFAULT_REGISTRY
    except NameError:
        from app.engineering.templates.mechanism.gripper import ParallelGripperTemplate
        from app.engineering.templates.part.flange import FlangeTemplate
        from app.engineering.templates.part.plate import PlateTemplate

        registry = EngineeringTemplateRegistry()
        registry.register(PlateTemplate())
        registry.register(FlangeTemplate())
        registry.register(ParallelGripperTemplate())
        _DEFAULT_REGISTRY = registry
        return registry


_DEFAULT_REGISTRY: EngineeringTemplateRegistry
