from __future__ import annotations

from app.engineering.schemas import (
    AdapterGenerationResult,
    AdapterPlateSpec,
    CouplingSpec,
    InterfaceComparison,
    MechanicalInterface,
)


def _value(value: float | int | None, default: float) -> float:
    return float(value if value is not None else default)


def generate_mechanical_adapter(
    source: MechanicalInterface,
    target: MechanicalInterface,
    comparison: InterfaceComparison,
) -> AdapterGenerationResult:
    """Create deterministic adapter and coupling specifications for a mismatch."""

    if not comparison.adapter_required:
        return AdapterGenerationResult(required=False, provenance=comparison.provenance)

    source_face_w = _value(source.face_width_mm, 42.0)
    source_face_h = _value(source.face_height_mm, 42.0)
    target_face_w = _value(target.face_width_mm, 60.0)
    target_face_h = _value(target.face_height_mm, 60.0)
    width = max(source_face_w, target_face_w) + 16.0
    height = max(source_face_h, target_face_h) + 16.0
    plate = AdapterPlateSpec(
        thickness_mm=10.0,
        width_mm=width,
        height_mm=height,
        target_pilot_diameter_mm=_value(target.pilot_diameter_mm, 50.0),
        source_pilot_diameter_mm=_value(source.pilot_diameter_mm, 22.0),
        target_bolt_circle_diameter_mm=_value(target.bolt_circle_diameter_mm, 60.0),
        source_bolt_circle_diameter_mm=_value(source.bolt_circle_diameter_mm, 31.0),
        target_bolt_count=int(target.bolt_count or 4),
        source_bolt_count=int(source.bolt_count or 4),
        target_bolt_diameter_mm=_value(target.bolt_diameter_mm, 5.0),
        source_bolt_diameter_mm=_value(source.bolt_diameter_mm, 3.4),
    )
    coupling = CouplingSpec(
        length_mm=max(30.0, _value(source.shaft_length_mm, 20.0) + 10.0),
        outer_diameter_mm=max(20.0, _value(target.shaft_diameter_mm, 10.0) * 2.0),
        motor_bore_diameter_mm=_value(source.shaft_diameter_mm, 5.0),
        driven_bore_diameter_mm=_value(target.shaft_diameter_mm, 10.0),
        motor_shaft_length_mm=_value(source.shaft_length_mm, 20.0),
        driven_shaft_length_mm=_value(target.shaft_length_mm, 20.0),
    )
    warnings: list[str] = []
    if source.shaft_diameter_mm and target.shaft_diameter_mm and source.shaft_diameter_mm != target.shaft_diameter_mm:
        warnings.append("轴径不一致，已生成阶梯孔柔性联轴器规格；实际选型仍需检查扭矩、间隙和轴伸长度。")
    if source.bolt_count != target.bolt_count:
        warnings.append("电机和夹爪孔数不同，适配板将使用两套独立孔阵列。")
    provenance = list(comparison.provenance)
    provenance.append(
        {
            "conclusion": "mechanical adapter specification generated",
            "status": "COMPUTED",
            "source": "deterministic_adapter_generator",
            "evidence": [],
            "details": {
                "adapter_plate": plate.model_dump(mode="json"),
                "coupling": coupling.model_dump(mode="json"),
            },
        }
    )
    return AdapterGenerationResult(
        required=True,
        adapter_plate=plate,
        coupling=coupling,
        warnings=warnings,
        provenance=provenance,
    )
