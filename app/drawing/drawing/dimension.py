from app.drawing.drawing.orthographic import dimensions
from app.drawing.schemas import PartSpec


def dimension_labels(part: PartSpec) -> list[str]:
    data = dimensions(part)
    labels: list[str] = []
    for key, value in data.items():
        if value:
            labels.append(f"{key.replace('_', ' ').upper()}  {value:g} mm")
    if part.holes:
        labels.append(f"HOLES  Ø{part.holes[0].diameter:g}  QTY {len(part.holes)}")
    return labels
