from __future__ import annotations

from typing import Any

from app.engineering.calculator import check_motor_interface, calculate_requirements
from app.engineering.cad import build_rg80_compound
from app.engineering.adapters.adapter import generate_mechanical_adapter
from app.engineering.adapters.fem import run_fem_adapter
from app.engineering.adapters.motor import motor_step_status
from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.schemas import GripperDesignRequest
from app.engineering.simulation import simulate_gripper_continuous
from app.engineering.templates.base import EngineeringTemplate
from app.engineering.tools.interfaces import compare_interfaces, gripper_input_interface, motor_interface


def _value(values: dict[str, Any], *names: str, default: Any) -> Any:
    for name in names:
        if name in values and values[name] is not None:
            return values[name]
    return default


def request_from_spec(spec: EngineeringObjectSpec) -> GripperDesignRequest:
    values = {**spec.parameters, **spec.requirements}
    motor = values.get("motor", {})
    if not isinstance(motor, dict):
        motor = {}
    return GripperDesignRequest(
        name=spec.name,
        payload_kg=float(_value(values, "payload_kg", "workpiece_mass", "mass", default=8.0)),
        workpiece_diameter_mm=float(
            _value(values, "workpiece_diameter_mm", "workpiece_diameter", "diameter", default=60.0)
        ),
        opening_min_mm=float(_value(values, "opening_min_mm", "min_opening", default=0.0)),
        opening_max_mm=float(_value(values, "opening_max_mm", "max_opening", default=80.0)),
        close_time_s=float(_value(values, "close_time_s", "open_time", "closing_time", default=0.8)),
        friction_coefficient=float(_value(values, "friction_coefficient", "friction", default=0.2)),
        safety_factor=float(_value(values, "safety_factor", default=2.0)),
        screw_lead_mm=float(_value(values, "screw_lead_mm", "screw_lead", default=4.0)),
        screw_efficiency=float(_value(values, "screw_efficiency", default=0.75)),
        transmission_ratio=float(_value(values, "transmission_ratio", default=1.0)),
        transmission_efficiency=float(_value(values, "transmission_efficiency", default=0.9)),
        allowed_motor_body_diameter_mm=float(
            _value(values, "allowed_motor_body_diameter_mm", default=100.0)
        ),
        allowed_motor_body_length_mm=float(
            _value(values, "allowed_motor_body_length_mm", default=140.0)
        ),
        interface_shaft_diameter_mm=float(
            _value(values, "interface_shaft_diameter_mm", default=8.0)
        ),
        interface_pilot_diameter_mm=float(
            _value(values, "interface_pilot_diameter_mm", default=50.0)
        ),
        interface_bolt_circle_diameter_mm=float(
            _value(values, "interface_bolt_circle_diameter_mm", default=60.0)
        ),
        interface_bolt_hole_diameter_mm=float(
            _value(values, "interface_bolt_hole_diameter_mm", default=5.0)
        ),
        interface_face_width_mm=float(
            _value(values, "interface_face_width_mm", default=60.0)
        ),
        interface_face_height_mm=float(
            _value(values, "interface_face_height_mm", default=60.0)
        ),
        interface_bolt_count=int(
            _value(values, "interface_bolt_count", default=4)
        ),
        motor=motor,
    )


def _adapter_for_request(request: GripperDesignRequest):
    source = motor_interface(request.motor)
    target = gripper_input_interface(request)
    comparison = compare_interfaces(source, target)
    return generate_mechanical_adapter(source, target, comparison)


def _component_manifest(
    request: GripperDesignRequest,
    adapter: Any,
) -> list[str]:
    """Return logical assembly components used by geometry, recipe and BOM."""

    components = [
        "base",
        "guide_rail_left",
        "guide_rail_right",
        "left_jaw",
        "right_jaw",
        "drive_screw",
        "drive_gears",
    ]
    if adapter.required:
        components.extend(["motor_adapter_plate", "flexible_coupling"])
    else:
        components.append("motor_adapter")
    components.append(request.motor.model if request.motor.step_path else "concept_motor")
    return components


class ParallelGripperTemplate(EngineeringTemplate):
    """Generic parallel gripper mechanism; RG-80 is its default preset."""

    @property
    def name(self) -> str:
        return "parallel_gripper"

    @property
    def object_type(self) -> str:
        return "mechanism"

    @property
    def capabilities(self) -> set[str]:
        return {
            "geometry",
            "selection",
            "assembly",
            "kinematics",
            "interference",
            "fem",
            "drawing",
            "export",
        }

    def default_requirements(self) -> list[str]:
        return [
            "workpiece_type",
            "workpiece_diameter_mm",
            "payload_kg",
            "opening_max_mm",
            "close_time_s",
        ]

    def validate(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        try:
            request = request_from_spec(spec)
        except Exception as exc:
            return {"status": "failed", "errors": [str(exc)]}
        errors: list[str] = []
        if request.opening_min_mm >= request.opening_max_mm:
            errors.append("gripper opening_min_mm must be smaller than opening_max_mm")
        return {"status": "passed" if not errors else "failed", "errors": errors}

    def build_geometry(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        request = request_from_spec(spec)
        adapter = _adapter_for_request(request)
        native = build_rg80_compound(request, adapter)
        motor_import = motor_step_status(request.motor.step_path)
        components = _component_manifest(
            request,
            adapter,
        )
        return {
            "backend": "cadquery" if native is not None else "fallback",
            "native": native,
            "shape": "parallel_gripper",
            "preset": spec.metadata.get("preset", "RG80Preset"),
            "component_count": len(components),
            "components": components,
            "motor_import": motor_import,
            "adapter": adapter.model_dump(mode="json"),
            "provenance": [
                {
                    "conclusion": "motor STEP geometry imported into assembly",
                    "status": "VERIFIED" if motor_import.get("imported") else "REVIEW_REQUIRED",
                    "source": "cadquery.step_import",
                    "evidence": request.motor.evidence,
                    "details": {
                        "model": request.motor.model,
                        "import_status": motor_import.get("status"),
                    },
                }
            ],
        }

    def build_selection(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        request = request_from_spec(spec)
        calculations = calculate_requirements(request)
        compatibility = check_motor_interface(request)
        adapter = _adapter_for_request(request)
        motor_imported = compatibility.verified_real_part
        performance_review = (
            "not_manufacturer_maximum" in request.motor.max_rpm_source
            or "holding_torque" in request.motor.rated_torque_source
        )
        provenance = list(compatibility.provenance)
        provenance.extend(adapter.provenance)
        provenance.append(
            {
                "conclusion": "motor catalog evidence loaded",
                "status": "VERIFIED" if request.motor.evidence and motor_imported else "REVIEW_REQUIRED",
                "source": request.motor.source,
                "evidence": request.motor.evidence,
                "details": {
                    "model": request.motor.model,
                    "manufacturer": request.motor.manufacturer,
                    "performance_review": performance_review,
                },
            }
        )
        return {
            "selection_status": (
                "verified_geometry"
                if motor_imported and not request.motor.verified
                else "verified_candidate"
                if motor_imported and request.motor.verified
                else "concept"
            ),
            "category": "motor",
            "manufacturer": request.motor.manufacturer,
            "model": request.motor.model,
            "source": request.motor.source,
            "parameters": request.motor.model_dump(mode="json"),
            "compatibility": compatibility.model_dump(mode="json"),
            "calculations": calculations.model_dump(mode="json"),
            "adapter": adapter.model_dump(mode="json"),
            "performance_status": "REVIEW_REQUIRED" if performance_review else "COMPUTED",
            "provenance": provenance,
        }

    def build_assembly(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        request = request_from_spec(spec)
        motor_name = request.motor.model if request.motor.step_path else "concept_motor"
        adapter = _adapter_for_request(request)
        components = _component_manifest(
            request,
            adapter,
        )
        return {
            "status": "completed",
            "component_count": len(components),
            "components": components,
            "adapter_required": adapter.required,
            "adapter": adapter.model_dump(mode="json"),
            "constraints": {
                "status": "recipe_ready",
                "message": (
                    "固定基座、两侧同步移动副、丝杆转动副和电机固定约束已结构化；"
                    "FreeCAD 原生求解需运行导出的 recipe。"
                ),
            },
            "joint_definitions": [
                {
                    "name": "base_fixed",
                    "type": "fixed",
                    "parent": "world",
                    "child": "base",
                },
                {
                    "name": "left_jaw_prismatic",
                    "type": "prismatic",
                    "axis": "X",
                    "range_mm": [0.0, request.opening_max_mm / 2.0],
                    "parent": "base",
                    "child": "left_jaw",
                },
                {
                    "name": "right_jaw_prismatic",
                    "type": "prismatic",
                    "axis": "X",
                    "range_mm": [0.0, request.opening_max_mm / 2.0],
                    "parent": "base",
                    "child": "right_jaw",
                },
                {
                    "name": "drive_screw_revolute",
                    "type": "revolute",
                    "axis": "X",
                    "parent": "base",
                    "child": "drive_screw",
                },
                {
                    "name": "motor_fixed_to_adapter",
                    "type": "fixed",
                    "parent": "motor_adapter_plate" if adapter.required else "motor_adapter",
                    "child": motor_name,
                },
            ],
            "provenance": adapter.provenance,
        }

    def build_kinematics(self, spec: EngineeringObjectSpec) -> dict[str, Any]:
        request = request_from_spec(spec)
        calculations = calculate_requirements(request)
        simulation = simulate_gripper_continuous(request, calculations)
        return {
            "status": simulation.status,
            "motion_type": simulation.motion_type,
            "joint_states": [
                {"name": "left_jaw_prismatic", "axis": "X", "range_mm": [0, request.opening_max_mm / 2]},
                {"name": "right_jaw_prismatic", "axis": "X", "range_mm": [0, request.opening_max_mm / 2]},
            ],
            "component_transforms": [sample.model_dump(mode="json") for sample in simulation.samples],
            "motion_range": [request.opening_min_mm, request.opening_max_mm],
            "expected_contacts": ["workpiece_at_closed"],
            "simulation": simulation.model_dump(mode="json"),
            "provenance": [
                {
                    "conclusion": "continuous gripper kinematics computed",
                    "status": "COMPUTED",
                    "source": simulation.solver_backend,
                    "evidence": [],
                    "details": {
                        "sample_count": len(simulation.samples),
                        "continuous_collision_checked": simulation.continuous_collision_checked,
                    },
                }
            ],
        }

    def run_fem(
        self,
        spec: EngineeringObjectSpec,
        state: dict[str, Any],
        output_dir: str,
    ) -> dict[str, Any]:
        return run_fem_adapter(spec, state, output_dir)

    def check_interference(
        self,
        spec: EngineeringObjectSpec,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        simulation = state.get("kinematics", {}).get("simulation", {})
        return {
            "status": "pass" if not simulation.get("structural_collisions") and not simulation.get("interferences") else "fail",
            "collisions": simulation.get("structural_collisions", []),
            "interferences": simulation.get("interferences", []),
            "expected_contacts": simulation.get("workpiece_contact_at_closed", False),
            "provenance": [
                {
                    "conclusion": "continuous swept collision check",
                    "status": "COMPUTED",
                    "source": simulation.get("solver_backend", "deterministic_swept_kinematic"),
                    "evidence": [],
                    "details": {
                        "sample_count": len(simulation.get("samples", [])),
                        "collision_events": len(simulation.get("collision_events", [])),
                    },
                }
            ],
        }

    def build_drawing(self, spec: EngineeringObjectSpec, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "completed",
            "views": ["top", "front", "side"],
            "motion_phases": ["OPEN", "HALF_OPEN", "CLOSED"],
            "provenance": [
                {
                    "conclusion": "orthographic drawing view set derived from parametric template",
                    "status": "COMPUTED",
                    "source": "deterministic_drawing_summary",
                    "evidence": [],
                    "details": {"view_count": 3},
                }
            ],
        }

    def get_bom(self, spec: EngineeringObjectSpec) -> list[dict[str, Any]]:
        request = request_from_spec(spec)
        adapter = _adapter_for_request(request)
        motor_imported = motor_step_status(request.motor.step_path).get("imported", False)
        component_names = _component_manifest(
            request,
            adapter,
        )
        descriptions = {
            "base": "Base",
            "guide_rail_left": "Guide Rail Left",
            "guide_rail_right": "Guide Rail Right",
            "left_jaw": "Left Jaw",
            "right_jaw": "Right Jaw",
            "drive_screw": "Drive Screw",
            "drive_gears": "Drive Gear Set",
            "motor_adapter_plate": "Motor Adapter Plate",
            "flexible_coupling": "Flexible Coupling",
            "motor_adapter": "Motor Adapter",
            "concept_motor": f"{request.motor.manufacturer} {request.motor.model}",
            request.motor.model: f"{request.motor.manufacturer} {request.motor.model}",
        }
        names = [descriptions[name] for name in component_names]
        source = "official_catalog" if request.motor.evidence else "demo"
        return [
            {
                "item": index,
                "part_number": (
                    "ENG-ADAPTER-PLATE-01"
                    if component_name == "motor_adapter_plate"
                    else "ENG-COUPLING-01"
                    if component_name == "flexible_coupling"
                    else f"ENG-RG80-{index:02d}"
                ),
                "description": name,
                "qty": 1,
                "source": source if component_name in {request.motor.model, "concept_motor"} else "parametric",
                "verification_status": (
                    "VERIFIED"
                    if source == "official_catalog"
                    and component_name == request.motor.model
                    and motor_imported
                    else "REVIEW_REQUIRED"
                    if source == "official_catalog" and component_name == request.motor.model
                    else "COMPUTED"
                ),
            }
            for index, (component_name, name) in enumerate(
                zip(component_names, names),
                start=1,
            )
        ]
