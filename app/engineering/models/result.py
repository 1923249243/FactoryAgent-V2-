from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class EngineeringResult(BaseModel):
    """Common result envelope for every engineering object template."""

    engineering_id: str
    object_type: str
    template: str
    revision: int = 1
    status: str
    verification_status: str = "COMPUTED"
    capabilities: list[str] = Field(default_factory=list)
    validation: dict[str, Any] = Field(default_factory=dict)
    geometry: dict[str, Any] = Field(default_factory=dict)
    selection: dict[str, Any] = Field(default_factory=dict)
    assembly: dict[str, Any] = Field(default_factory=dict)
    kinematics: dict[str, Any] = Field(default_factory=dict)
    interference: dict[str, Any] = Field(default_factory=dict)
    fem: dict[str, Any] = Field(default_factory=dict)
    drawing: dict[str, Any] = Field(default_factory=dict)
    bom: list[dict[str, Any]] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    unsupported_capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
