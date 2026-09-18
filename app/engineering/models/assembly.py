from __future__ import annotations

from typing import Literal

from app.engineering.models.object import EngineeringObjectSpec


class AssemblyObject(EngineeringObjectSpec):
    object_type: Literal["assembly"] = "assembly"
