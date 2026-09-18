from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


EngineeringObjectType = Literal["part", "assembly", "mechanism"]


class EngineeringObjectSpec(BaseModel):
    """Serializable, template-neutral engineering design contract."""

    object_type: EngineeringObjectType
    template: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    units: Literal["mm"] = "mm"
    parameters: dict[str, Any] = Field(default_factory=dict)
    requirements: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
