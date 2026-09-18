from __future__ import annotations

from typing import Literal

from app.engineering.models.object import EngineeringObjectSpec


class MechanismObject(EngineeringObjectSpec):
    object_type: Literal["mechanism"] = "mechanism"
