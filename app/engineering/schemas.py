from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.engineering.models.object import EngineeringObjectSpec


class MotorSpec(BaseModel):
    """Mechanical and performance fields needed for a first fit check.

    The default is deliberately labelled as a concept motor. It is not a
    manufacturer part number and must not be presented as a real selection.
    """

    model: str = Field(default="CONCEPT-SERVO-80", min_length=1, max_length=100)
    manufacturer: str = Field(default="Concept", min_length=1, max_length=100)
    verified: bool = False
    source: str = Field(default="concept-demo", min_length=1, max_length=120)
    shaft_diameter_mm: float = Field(default=8.0, gt=0, le=200)
    shaft_length_mm: float = Field(default=20.0, gt=0, le=500)
    pilot_diameter_mm: float = Field(default=50.0, gt=0, le=500)
    bolt_circle_diameter_mm: float = Field(default=60.0, gt=0, le=500)
    bolt_hole_diameter_mm: float = Field(default=5.0, gt=0, le=100)
    body_diameter_mm: float = Field(default=80.0, gt=0, le=1000)
    body_length_mm: float = Field(default=100.0, gt=0, le=2000)
    rated_torque_nm: float = Field(default=2.0, gt=0, le=100000)
    max_rpm: float = Field(default=3000.0, gt=0, le=1000000)
    step_path: str | None = Field(default=None, max_length=500)
    face_width_mm: float = Field(default=60.0, gt=0, le=3000)
    face_height_mm: float = Field(default=60.0, gt=0, le=3000)
    bolt_count: int = Field(default=4, ge=1, le=64)
    catalog_id: str | None = Field(default=None, max_length=120)
    datasheet_url: str | None = Field(default=None, max_length=2000)
    step_url: str | None = Field(default=None, max_length=2000)
    max_rpm_source: str = Field(default="concept-assumption", max_length=200)
    rated_torque_source: str = Field(default="concept-assumption", max_length=200)
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class MechanicalInterface(BaseModel):
    """A reusable mechanical mating-interface contract."""

    interface_type: str = Field(default="motor_flange", min_length=1, max_length=100)
    shaft_diameter_mm: float | None = Field(default=None, gt=0, le=2000)
    shaft_length_mm: float | None = Field(default=None, gt=0, le=5000)
    pilot_diameter_mm: float | None = Field(default=None, gt=0, le=5000)
    face_width_mm: float | None = Field(default=None, gt=0, le=5000)
    face_height_mm: float | None = Field(default=None, gt=0, le=5000)
    bolt_circle_diameter_mm: float | None = Field(default=None, gt=0, le=5000)
    bolt_count: int | None = Field(default=None, ge=1, le=64)
    bolt_diameter_mm: float | None = Field(default=None, gt=0, le=500)
    pattern: str = Field(default="bolt_circle", max_length=80)
    source: str = Field(default="user_input", max_length=160)
    verified: bool = False
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class InterfaceIssue(BaseModel):
    parameter: str
    source: Any = None
    target: Any = None
    tolerance: float | None = None
    severity: Literal["error", "warning"] = "error"
    adapter_supported: bool = True


class InterfaceComparison(BaseModel):
    status: Literal["COMPUTED", "VERIFIED", "REVIEW_REQUIRED"] = "COMPUTED"
    compatible: bool
    adapter_required: bool
    issues: list[InterfaceIssue] = Field(default_factory=list)
    source_interface: MechanicalInterface
    target_interface: MechanicalInterface
    provenance: list[dict[str, Any]] = Field(default_factory=list)


class AdapterPlateSpec(BaseModel):
    part_number: str = "ENG-ADAPTER-PLATE-01"
    name: str = "Motor Adapter Plate"
    thickness_mm: float = Field(gt=0)
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    target_pilot_diameter_mm: float = Field(gt=0)
    source_pilot_diameter_mm: float = Field(gt=0)
    target_bolt_circle_diameter_mm: float = Field(gt=0)
    source_bolt_circle_diameter_mm: float = Field(gt=0)
    target_bolt_count: int = Field(ge=1)
    source_bolt_count: int = Field(ge=1)
    target_bolt_diameter_mm: float = Field(gt=0)
    source_bolt_diameter_mm: float = Field(gt=0)


class CouplingSpec(BaseModel):
    part_number: str = "ENG-COUPLING-01"
    name: str = "Flexible Coupling"
    length_mm: float = Field(gt=0)
    outer_diameter_mm: float = Field(gt=0)
    motor_bore_diameter_mm: float = Field(gt=0)
    driven_bore_diameter_mm: float = Field(gt=0)
    motor_shaft_length_mm: float = Field(gt=0)
    driven_shaft_length_mm: float = Field(gt=0)
    source: str = "parametric_adapter"


class AdapterGenerationResult(BaseModel):
    status: Literal["COMPUTED", "REVIEW_REQUIRED"] = "COMPUTED"
    required: bool
    adapter_plate: AdapterPlateSpec | None = None
    coupling: CouplingSpec | None = None
    warnings: list[str] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    kind: str
    reference: str
    path: str | None = None
    sha256: str | None = None
    note: str | None = None


class ProvenanceRecord(BaseModel):
    conclusion: str
    status: Literal["VERIFIED", "COMPUTED", "REVIEW_REQUIRED"]
    source: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class GripperDesignRequest(BaseModel):
    """Requirements for the deterministic RG-80 concept gripper demo."""

    name: str = Field(default="RG-80 Concept Gripper", min_length=1, max_length=160)
    payload_kg: float = Field(default=8.0, gt=0, le=10000)
    workpiece_diameter_mm: float = Field(default=60.0, gt=0, le=2000)
    opening_min_mm: float = Field(default=0.0, ge=0, le=2000)
    opening_max_mm: float = Field(default=80.0, gt=0, le=2000)
    close_time_s: float = Field(default=0.8, gt=0, le=600)
    friction_coefficient: float = Field(default=0.2, gt=0, le=2)
    safety_factor: float = Field(default=2.0, ge=1, le=20)
    screw_lead_mm: float = Field(default=4.0, gt=0, le=200)
    screw_efficiency: float = Field(default=0.75, gt=0, le=1)
    transmission_ratio: float = Field(default=1.0, gt=0, le=1000)
    transmission_efficiency: float = Field(default=0.9, gt=0, le=1)
    allowed_motor_body_diameter_mm: float = Field(default=100.0, gt=0, le=3000)
    allowed_motor_body_length_mm: float = Field(default=140.0, gt=0, le=3000)
    interface_shaft_diameter_mm: float = Field(default=8.0, gt=0, le=500)
    interface_pilot_diameter_mm: float = Field(default=50.0, gt=0, le=1000)
    interface_bolt_circle_diameter_mm: float = Field(default=60.0, gt=0, le=2000)
    interface_bolt_hole_diameter_mm: float = Field(default=5.0, gt=0, le=500)
    interface_face_width_mm: float = Field(default=60.0, gt=0, le=3000)
    interface_face_height_mm: float = Field(default=60.0, gt=0, le=3000)
    interface_bolt_count: int = Field(default=4, ge=1, le=64)
    motor: MotorSpec = Field(default_factory=MotorSpec)


class InterfaceCheck(BaseModel):
    name: str
    expected: float
    actual: float
    tolerance: float
    passed: bool
    note: str


class CalculationResult(BaseModel):
    gravity_m_s2: float
    required_total_normal_force_n: float
    required_per_jaw_force_n: float
    opening_speed_mm_s: float
    screw_speed_rpm: float
    screw_torque_nm: float
    required_motor_torque_nm: float
    required_motor_power_w: float
    motor_torque_margin: float
    motor_speed_margin_rpm: float


class CompatibilityResult(BaseModel):
    compatible: bool
    verified_real_part: bool
    checks: list[InterfaceCheck]
    warnings: list[str] = Field(default_factory=list)
    adapter_required: bool = False
    issues: list[dict[str, Any]] = Field(default_factory=list)
    source_interface: dict[str, Any] = Field(default_factory=dict)
    target_interface: dict[str, Any] = Field(default_factory=dict)
    provenance: list[dict[str, Any]] = Field(default_factory=list)


class MotionSample(BaseModel):
    index: int
    phase: Literal["OPEN", "MOVE", "HALF_OPEN", "CLOSED"]
    time_s: float
    opening_mm: float
    left_jaw_x_mm: float
    right_jaw_x_mm: float
    workpiece_contact: bool
    structural_collision: bool


class SimulationResult(BaseModel):
    status: Literal["pass", "review", "fail"]
    motion_type: str = "synchronized_prismatic_jaws"
    samples: list[MotionSample]
    max_opening_speed_mm_s: float
    required_screw_speed_rpm: float
    motor_speed_sufficient: bool
    workpiece_contact_at_closed: bool
    structural_collisions: list[str] = Field(default_factory=list)
    interferences: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    solver_backend: str = "deterministic_swept_kinematic"
    solver_available: bool = True
    continuous_collision_checked: bool = False
    swept_min_clearance_mm: float | None = None
    collision_events: list[dict[str, Any]] = Field(default_factory=list)
    dynamics_check: dict[str, Any] = Field(default_factory=dict)


class FEMResult(BaseModel):
    """FEM handoff/result envelope with an explicit no-solver boundary."""

    status: Literal["completed", "review_required", "failed"]
    solver_backend: str
    solver_available: bool
    input_mesh_provided: bool = False
    analysis_plan: str | None = None
    calculix_template: str | None = None
    analytic_precheck: dict[str, Any] = Field(default_factory=dict)
    solver_result: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class EngineeringReport(BaseModel):
    design_id: str
    status: Literal["pass", "review", "fail"]
    agent_version: str = "V4.0-foundation"
    design_type: str = "gripper"
    model_name: str
    cad_backend: str
    requirements: GripperDesignRequest
    calculations: CalculationResult
    compatibility: CompatibilityResult
    simulation: SimulationResult
    assumptions: list[str] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EngineeringDesignRequest(BaseModel):
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    spec: EngineeringObjectSpec | None = None
    requested_capabilities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_prompt_or_spec(self) -> "EngineeringDesignRequest":
        if self.prompt is None and self.spec is None:
            raise ValueError("prompt or spec is required")
        return self


class EngineeringRevisionRequest(BaseModel):
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    spec: EngineeringObjectSpec | None = None
    patch: dict[str, Any] | None = None
    requested_capabilities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_revision_input(self) -> "EngineeringRevisionRequest":
        if self.prompt is None and self.spec is None and self.patch is None:
            raise ValueError("prompt, spec or patch is required")
        return self


class EngineeringSimulationRequest(BaseModel):
    requested_capabilities: list[str] = Field(
        default_factory=lambda: ["kinematics", "interference"]
    )
