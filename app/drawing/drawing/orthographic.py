from app.drawing.schemas import DrawingSpec, PartSpec


def primary_part(spec: DrawingSpec) -> PartSpec:
    return spec.parts[0]


def dimensions(part: PartSpec) -> dict[str, float]:
    if part.part_type == "flange":
        return {
            "outer_diameter": part.outer_diameter or part.length or 0,
            "inner_diameter": part.inner_diameter or 0,
            "thickness": part.height or part.width or 0,
        }
    if part.part_type == "shaft":
        return {
            "length": part.length or 0,
            "diameter": part.outer_diameter or part.width or part.height or 0,
        }
    return {
        "length": part.length or 0,
        "width": part.width or 0,
        "height": part.height or 0,
    }


def view_labels(part: PartSpec) -> tuple[str, str, str]:
    if part.part_type == "flange":
        return "TOP VIEW / PLAN", "FRONT VIEW / THICKNESS", "SECTION / BORE"
    return "TOP VIEW", "FRONT VIEW", "SIDE VIEW"
