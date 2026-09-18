from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.config import settings
from app.engineering.catalog import get_catalog_motor
from app.engineering.models.object import EngineeringObjectSpec


class PlannerResult(BaseModel):
    status: Literal["planned", "unsupported", "review_required"]
    spec: EngineeringObjectSpec | None = None
    requested_capabilities: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _numbers(text: str) -> list[float]:
    return [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]


def _number_after(text: str, labels: tuple[str, ...], default: float) -> float:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[:：]?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return default


class EngineeringPlanner:
    """Deterministic planner; an LLM can later provide the same spec contract."""

    def plan(self, prompt: str, use_llm: bool | None = None) -> PlannerResult:
        if use_llm is None:
            use_llm = settings.engineering_planner_llm
        if use_llm:
            llm_result = self._plan_with_llm(prompt)
            if llm_result is not None:
                return llm_result
        return self._plan_deterministic(prompt)

    @staticmethod
    def _plan_with_llm(prompt: str) -> PlannerResult | None:
        try:
            from app.agent.llm import _request_completion, llm_available

            if not llm_available():
                return None
            content = _request_completion(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是通用机械工程任务规划器。只输出 JSON。"
                            "字段为 object_type(part/assembly/mechanism)、template、name、"
                            "requirements、parameters、requested_capabilities。"
                            "只选择已知模板 plate、flange、parallel_gripper；"
                            "不要输出 CAD、Python 或仿真数值。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                response_format={"type": "json_object"},
            )
            if not content:
                return None
            candidate = content.strip()
            start, end = candidate.find("{"), candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start : end + 1]
            payload = json.loads(candidate)
            spec_payload = payload.get("spec", payload)
            spec = EngineeringObjectSpec.model_validate(
                {
                    "object_type": spec_payload["object_type"],
                    "template": spec_payload["template"],
                    "name": spec_payload.get("name", "Planned Engineering Object"),
                    "units": spec_payload.get("units", "mm"),
                    "parameters": spec_payload.get("parameters", {}),
                    "requirements": spec_payload.get("requirements", {}),
                    "metadata": spec_payload.get("metadata", {}),
                }
            )
            requested = payload.get("requested_capabilities", [])
            if not isinstance(requested, list):
                requested = []
            return PlannerResult(
                status="planned",
                spec=spec,
                requested_capabilities=[str(item) for item in requested],
            )
        except Exception:
            # The deterministic planner is the contract-preserving fallback.
            return None

    def _plan_deterministic(self, prompt: str) -> PlannerResult:
        text = prompt.strip()
        normalized = text.lower()
        if not text:
            return PlannerResult(status="unsupported", errors=["empty engineering prompt"])

        if "六轴机器人" in text or "6轴机器人" in text or "six-axis robot" in normalized:
            return PlannerResult(
                status="unsupported",
                errors=["no registered template for six-axis robot"],
            )

        if any(token in text for token in ("夹爪", "夹持", "gripper")):
            diameter = _number_after(text, ("直径", "diameter"), 60.0)
            mass = _number_after(text, ("质量", "重量", "mass", "payload"), 8.0)
            opening = _number_after(text, ("最大开口", "开口", "opening"), max(80.0, diameter + 20.0))
            close_time = _number_after(text, ("开合时间", "open_time", "close_time"), 0.8)
            requested = [
                "geometry",
                "selection",
                "assembly",
                "kinematics",
                "interference",
                "fem",
                "drawing",
                "export",
            ]
            if "疲劳" in text or "fatigue" in normalized:
                requested.append("fatigue")
            catalog_motor = None
            if any(
                token in text
                for token in ("PKP243D02B", "Oriental Motor", "东方马达", "真实电机")
            ):
                catalog_motor = get_catalog_motor("oriental_motor_pkp243d02b")
            requirements = {
                "workpiece_type": "cylinder",
                "workpiece_diameter": diameter,
                "workpiece_mass": mass,
                "max_opening": opening,
                "close_time_s": close_time,
            }
            if catalog_motor is not None:
                requirements["motor"] = catalog_motor.model_dump(mode="json")
            return PlannerResult(
                status="planned" if "fatigue" not in requested else "review_required",
                spec=EngineeringObjectSpec(
                    object_type="mechanism",
                    template="parallel_gripper",
                    name=(
                        "PKP243D02B Real-Motor Parallel Gripper"
                        if catalog_motor is not None
                        else "Parallel Gripper"
                    ),
                    requirements=requirements,
                    metadata={"preset": "RG80Preset"},
                ),
                requested_capabilities=requested,
                warnings=(
                    ["fatigue capability requires a solver and is review_required"]
                    if "fatigue" in requested
                    else []
                ),
            )

        if any(token in text for token in ("安装板", "plate")):
            values = _numbers(text)
            length, width, thickness = (values + [180.0, 120.0, 12.0])[:3]
            hole_diameter = _number_after(text, ("Ø", "孔径", "hole"), 10.0)
            margin = _number_after(text, ("边缘", "margin"), 15.0)
            holes = [
                {"x": margin, "y": margin, "diameter": hole_diameter},
                {"x": length - margin, "y": margin, "diameter": hole_diameter},
                {"x": length - margin, "y": width - margin, "diameter": hole_diameter},
                {"x": margin, "y": width - margin, "diameter": hole_diameter},
            ]
            return PlannerResult(
                status="planned",
                spec=EngineeringObjectSpec(
                    object_type="part",
                    template="plate",
                    name="Parametric Mounting Plate",
                    parameters={
                        "length": length,
                        "width": width,
                        "thickness": thickness,
                        "holes": holes,
                    },
                ),
                requested_capabilities=["geometry", "drawing", "export"],
            )

        if "法兰" in text or "flange" in normalized:
            outer = _number_after(text, ("外径", "outer_diameter", "diameter"), 120.0)
            inner = _number_after(text, ("内孔", "内径", "inner_diameter"), 50.0)
            count_match = re.search(r"(\d+)\s*个", text)
            count = int(count_match.group(1)) if count_match else 6
            bolt_diameter = _number_after(text, ("Ø", "孔径", "bolt_diameter"), 8.0)
            return PlannerResult(
                status="planned",
                spec=EngineeringObjectSpec(
                    object_type="part",
                    template="flange",
                    name="Parametric Flange",
                    parameters={
                        "outer_diameter": outer,
                        "inner_diameter": inner,
                        "thickness": 15.0,
                        "bolt_circle": outer * 0.75,
                        "bolt_count": count,
                        "bolt_diameter": bolt_diameter,
                    },
                ),
                requested_capabilities=["geometry", "drawing", "export"],
            )

        return PlannerResult(
            status="unsupported",
            errors=["no registered engineering template matched the prompt"],
        )
