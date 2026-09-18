from pydantic import ValidationError

from app.drawing.schemas import DrawingSpec, PartSpec


class DrawingValidationError(ValueError):
    """A user-facing validation error raised before any geometry is built."""


def validate_drawing_spec(spec: DrawingSpec) -> DrawingSpec:
    """Apply domain constraints that are more specific than Pydantic types."""

    try:
        part_ids = [part.part_id for part in spec.parts]
        if len(part_ids) != len(set(part_ids)):
            raise DrawingValidationError("Part ID 必须唯一。")

        for part in spec.parts:
            if part.part_type == "plate":
                if not all(value is not None for value in (part.length, part.width, part.height)):
                    raise DrawingValidationError("安装板必须提供长、宽、厚度。")
                assert part.length is not None and part.width is not None
                for hole in part.holes:
                    if hole.x <= hole.diameter / 2 or hole.x >= part.length - hole.diameter / 2:
                        raise DrawingValidationError(
                            f"孔中心位置超过板材边界：X={hole.x:g}mm，"
                            f"建议将 X 坐标调整到 ({hole.diameter / 2:g}, "
                            f"{part.length - hole.diameter / 2:g})。"
                        )
                    if hole.y <= hole.diameter / 2 or hole.y >= part.width - hole.diameter / 2:
                        raise DrawingValidationError(
                            f"孔中心位置超过板材边界：Y={hole.y:g}mm，"
                            f"建议将 Y 坐标调整到 ({hole.diameter / 2:g}, "
                            f"{part.width - hole.diameter / 2:g})。"
                        )
                    if hole.diameter >= min(part.length, part.width):
                        raise DrawingValidationError("孔径必须小于工件的最小平面尺寸。")

            if part.part_type == "flange":
                outer = part.outer_diameter or part.length
                thickness = part.height or part.width
                inner = part.inner_diameter or 0
                if outer is None or thickness is None:
                    raise DrawingValidationError("法兰必须提供外径和厚度。")
                if inner >= outer:
                    raise DrawingValidationError("法兰中心孔必须小于外径。")
                for hole in part.holes:
                    radius = (part.bolt_circle_diameter or outer * 0.72) / 2
                    if radius + hole.diameter / 2 >= outer / 2:
                        raise DrawingValidationError("法兰螺栓孔超出外圆边界。")

            if part.part_type in {"shaft", "bracket", "housing"}:
                if not any(value is not None for value in (part.length, part.width, part.height)):
                    raise DrawingValidationError(f"{part.name} 缺少有效尺寸。")

        if spec.drawing_type == "assembly":
            if spec.assembly is None:
                raise DrawingValidationError("装配图必须包含 assembly 定义。")
            known_ids = {part.part_id for part in spec.parts}
            for component in spec.assembly.components:
                if component.part_id not in known_ids:
                    raise DrawingValidationError(
                        f"装配组件 {component.instance_id} 引用了不存在的 Part ID "
                        f"{component.part_id}。"
                    )
    except DrawingValidationError:
        raise
    except (AssertionError, TypeError) as exc:
        raise DrawingValidationError(f"DrawingSpec 参数不完整：{exc}") from exc

    return spec


def validate_payload(payload: dict) -> DrawingSpec:
    try:
        spec = DrawingSpec.model_validate(payload)
    except ValidationError as exc:
        message = exc.errors()[0].get("msg", "DrawingSpec 校验失败")
        raise DrawingValidationError(message) from exc
    return validate_drawing_spec(spec)
