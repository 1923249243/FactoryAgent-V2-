from collections import OrderedDict

from app.drawing.schemas import DrawingSpec, PartSpec


def _row(part: PartSpec, item: int, quantity: int) -> dict:
    return {
        "item": item,
        "part_number": part.part_id,
        "description": part.name,
        "qty": quantity,
        "material": part.material,
    }


def generate_bom(spec: DrawingSpec) -> list[dict]:
    """Generate BOM from assembly components, never from model prose."""

    by_id = {part.part_id: part for part in spec.parts}
    if spec.drawing_type != "assembly" or spec.assembly is None:
        return [_row(spec.parts[0], 1, 1)]

    quantities: OrderedDict[str, int] = OrderedDict()
    for component in spec.assembly.components:
        quantities[component.part_id] = quantities.get(component.part_id, 0) + 1

    return [
        _row(by_id[part_id], index, quantity)
        for index, (part_id, quantity) in enumerate(quantities.items(), start=1)
    ]
