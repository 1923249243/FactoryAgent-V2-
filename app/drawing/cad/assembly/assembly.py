from app.drawing.cad.engine import PartGeometry


def assembly_components(parts: list[PartGeometry]) -> list[PartGeometry]:
    """Return assembled instances; transforms are already applied by the engine."""

    return parts
