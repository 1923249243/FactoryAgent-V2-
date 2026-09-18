from __future__ import annotations

from html import escape
from math import cos, radians, sin

from app.drawing.cad.parts.common import variant_part
from app.drawing.drawing.bom import generate_bom
from app.drawing.drawing.dimension import dimension_labels
from app.drawing.drawing.orthographic import primary_part, view_labels
from app.drawing.schemas import DrawingSpec, PartSpec


NAVY = "#102E4A"
BLUE = "#326FA8"
LINE = "#62778B"
GRID = "#B7C8D8"
METAL = "#A8B2BA"
METAL_DARK = "#697781"
PAPER = "#F4F7FA"


def _text(x: float, y: float, value: str, size: int = 14, fill: str = NAVY, weight: str = "400", anchor: str = "start") -> str:
    return (
        f'<text x="{x:g}" y="{y:g}" fill="{fill}" font-family="Arial,Segoe UI,sans-serif" '
        f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>'
    )


def _line(x1: float, y1: float, x2: float, y2: float, stroke: str = LINE, width: float = 1.3, dash: str = "") -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" stroke="{stroke}" stroke-width="{width:g}"{dash_attr}/>'


def _rect(x: float, y: float, w: float, h: float, stroke: str = GRID, fill: str = "none", width: float = 1.0, rx: float = 0) -> str:
    return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx:g}" stroke="{stroke}" stroke-width="{width:g}" fill="{fill}"/>'


def _polygon(points: list[tuple[float, float]], fill: str, stroke: str = METAL_DARK, width: float = 1.2) -> str:
    value = " ".join(f"{x:g},{y:g}" for x, y in points)
    return f'<polygon points="{value}" fill="{fill}" stroke="{stroke}" stroke-width="{width:g}"/>'


def _circle(cx: float, cy: float, radius: float, stroke: str = NAVY, fill: str = "none", width: float = 1.4, dash: str = "") -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<circle cx="{cx:g}" cy="{cy:g}" r="{radius:g}" stroke="{stroke}" stroke-width="{width:g}" fill="{fill}"{dash_attr}/>'


def _ellipse(cx: float, cy: float, rx: float, ry: float, stroke: str = NAVY, fill: str = "none", width: float = 1.2) -> str:
    return f'<ellipse cx="{cx:g}" cy="{cy:g}" rx="{rx:g}" ry="{ry:g}" stroke="{stroke}" stroke-width="{width:g}" fill="{fill}"/>'


def _iso_point(x: float, y: float, z: float, origin: tuple[float, float], scale: float) -> tuple[float, float]:
    return (
        origin[0] + (x - y) * 0.78 * scale,
        origin[1] + (x + y) * 0.34 * scale - z * 0.78 * scale,
    )


def _iso_box(origin: tuple[float, float], length: float, width: float, height: float, scale: float, fill: str = METAL) -> str:
    p000 = _iso_point(0, 0, 0, origin, scale)
    p100 = _iso_point(length, 0, 0, origin, scale)
    p110 = _iso_point(length, width, 0, origin, scale)
    p010 = _iso_point(0, width, 0, origin, scale)
    p001 = _iso_point(0, 0, height, origin, scale)
    p101 = _iso_point(length, 0, height, origin, scale)
    p111 = _iso_point(length, width, height, origin, scale)
    p011 = _iso_point(0, width, height, origin, scale)
    return "".join(
        [
            _polygon([p010, p110, p111, p011], "#D0D6DB"),
            _polygon([p000, p100, p110, p010], "#87949D"),
            _polygon([p000, p100, p101, p001], fill),
            _polygon([p001, p101, p111, p011], "#C5CDD2"),
        ]
    )


def _draw_iso_part(part: PartSpec, origin: tuple[float, float], scale: float) -> str:
    if part.part_type == "flange":
        diameter = part.outer_diameter or part.length or 120
        thick = part.height or 15
        center = _iso_point(diameter / 2, diameter / 2, thick, origin, scale)
        body = _iso_box(origin, diameter, diameter, thick, scale, "#AAB4BA")
        body += _ellipse(center[0], center[1], diameter * 0.34 * scale, diameter * 0.16 * scale, stroke="#52626D", width=1.3)
        body += _ellipse(center[0], center[1] - thick * 0.78 * scale, diameter * 0.21 * scale, diameter * 0.10 * scale, stroke="#3E505D", width=1.1)
        if part.inner_diameter:
            body += _ellipse(center[0], center[1], part.inner_diameter * 0.34 * scale, part.inner_diameter * 0.16 * scale, stroke=NAVY, width=1.2)
        return body
    if part.part_type == "shaft":
        length = part.length or 120
        diameter = part.outer_diameter or part.width or 30
        return _iso_box(origin, length, diameter, diameter, scale, "#A7B0B7")
    return _iso_box(
        origin,
        part.length or 160,
        part.width or 100,
        part.height or 50,
        scale,
        "#A8B2B8",
    )


def _draw_top(part: PartSpec, x: float, y: float, w: float, h: float) -> str:
    length = part.length or 160
    width = part.width or 100
    if part.part_type == "flange":
        diameter = part.outer_diameter or length
        radius = min(w, h) * 0.38
        cx, cy = x + w / 2, y + h / 2
        content = _circle(cx, cy, radius, stroke=LINE, width=1.6)
        if part.inner_diameter:
            content += _circle(cx, cy, radius * part.inner_diameter / diameter, stroke=BLUE, width=1.4)
        for hole in part.holes:
            hx = cx + (hole.x - diameter / 2) / diameter * radius * 2
            hy = cy + (hole.y - diameter / 2) / diameter * radius * 2
            content += _circle(hx, hy, radius * hole.diameter / diameter, stroke=BLUE, width=1.0)
        return content
    sx = min((w - 28) / length, (h - 24) / width)
    rw, rh = length * sx, width * sx
    rx, ry = x + (w - rw) / 2, y + (h - rh) / 2
    content = _rect(rx, ry, rw, rh, stroke=LINE, width=1.3)
    for hole in part.holes:
        content += _circle(rx + hole.x * sx, ry + (width - hole.y) * sx, max(2.5, hole.diameter * sx / 2), stroke=BLUE, width=1.0)
    return content


def _draw_front(part: PartSpec, x: float, y: float, w: float, h: float) -> str:
    length = part.length or 160
    height = part.height or 50
    sx = min((w - 30) / length, (h - 24) / height)
    rw, rh = length * sx, height * sx
    return _rect(x + (w - rw) / 2, y + (h - rh) / 2, rw, rh, stroke=LINE, width=1.2)


def render_drawing_svg(spec: DrawingSpec, width: int = 1200, height: int = 760, exploded: bool = False) -> str:
    """Render a deterministic orthographic/iso drawing SVG."""

    part = primary_part(spec)
    labels = view_labels(part)
    output: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>',
        _rect(12, 12, width - 24, height - 24, stroke=GRID, width=1.2),
        _text(34, 52, spec.title, 30, NAVY, "700"),
        _text(36, 79, "PARAMETRIC PART & ASSEMBLY GENERATOR", 13, NAVY, "600"),
        _text(width - 36, 50, f"REV {spec.revision:02d}", 13, BLUE, "600", "end"),
        _line(34, 98, width - 34, 98, GRID),
    ]

    if spec.drawing_type == "assembly" and spec.assembly:
        output.append(_text(40, 130, "ISOMETRIC ASSEMBLY / EXPLODED" if exploded else "ISOMETRIC ASSEMBLY", 12, BLUE, "700"))
        for index, component in enumerate(spec.assembly.components):
            component_part = variant_part(next(item for item in spec.parts if item.part_id == component.part_id), component.variant)
            offset = component.exploded_offset if exploded else (0, 0, 0)
            pos = (component.position[0] + offset[0], component.position[1] + offset[1], component.position[2] + offset[2])
            scale = 0.48 if component_part.part_type != "plate" else 0.28
            origin = (360 + pos[0] * 0.5 + index * 3, 430 + pos[1] * 0.12 - pos[2] * 0.3)
            output.append(_draw_iso_part(component_part, origin, scale))
            if exploded:
                output.append(_circle(origin[0], origin[1] - 20, 12, stroke=BLUE, width=1.2))
                output.append(_text(origin[0], origin[1] - 16, str(index + 1), 10, BLUE, "700", "middle"))
    else:
        output.append(_text(40, 130, "ISOMETRIC CAD VIEW", 12, BLUE, "700"))
        output.append(_draw_iso_part(part, (460, 500), 1.85 if part.part_type == "plate" else 1.1))

    output.extend(
        [
            _rect(30, 155, 760, 410, stroke=GRID),
            _text(54, 190, "GEOMETRY / ISOMETRIC", 11, BLUE, "700"),
            _rect(820, 155, 345, 410, stroke=GRID),
            _text(842, 190, "PARAMETERS", 11, BLUE, "700"),
            _text(842, 222, f"TYPE     {part.part_type.upper()}", 13, NAVY),
            _text(842, 250, f"MATERIAL {part.material}", 13, NAVY),
        ]
    )
    y = 288
    for label in dimension_labels(part):
        output.append(_text(842, y, label, 12, LINE))
        y += 26
    output.append(_line(842, y + 2, 1142, y + 2, GRID))
    y += 34
    output.append(_text(842, y, "VALIDATED / DETERMINISTIC", 11, BLUE, "700"))
    output.append(_text(842, y + 26, "LLM -> JSON -> CAD -> DRAWING", 11, LINE))

    output.extend(
        [
            _rect(30, 590, 360, 140, stroke=GRID),
            _text(48, 615, labels[0], 11, BLUE, "700"),
            _draw_top(part, 48, 628, 324, 88),
            _rect(410, 590, 360, 140, stroke=GRID),
            _text(428, 615, labels[1], 11, BLUE, "700"),
            _draw_front(part, 428, 628, 324, 88),
            _rect(790, 590, 375, 140, stroke=GRID),
            _text(808, 615, labels[2], 11, BLUE, "700"),
            _draw_front(part, 808, 628, 339, 88),
            _text(34, height - 25, "FACTORY AGENT  /  DRAWING AGENT V3  /  PORTFOLIO DEMO", 10, LINE),
            _text(width - 34, height - 25, "MM  ·  REVISION CONTROLLED", 10, LINE, "400", "end"),
            "</svg>",
        ]
    )
    return "".join(output)
