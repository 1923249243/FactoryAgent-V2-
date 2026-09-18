from app.drawing.cad.engine import PartGeometry


def exploded_components(parts: list[PartGeometry]) -> list[PartGeometry]:
    """Return component instances with deterministic exploded offsets."""

    return [
        PartGeometry(
            part=item.part,
            native=item.native,
            position=item.exploded_position,
            rotation=item.rotation,
            exploded_position=item.exploded_position,
            variant=item.variant,
        )
        for item in parts
    ]
