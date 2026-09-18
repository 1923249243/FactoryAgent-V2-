"""Deterministic PX-2100 engineering sheet renderer.

The sheet is intentionally rendered from ``DrawingSpec`` (and, when
available, the CadQuery bounding box) rather than from an image model.  The
same dimensions and component instances therefore continue to drive the CAD
exports, orthographic views, callouts, exploded view, and BOM.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from math import cos, hypot, radians, sin
import os
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any
import xml.etree.ElementTree as ET

from app.drawing.cad.parts.common import variant_part
from app.drawing.drawing.bom import generate_bom
from app.drawing.schemas import DrawingSpec, PartSpec
from app.drawing.sheet.layout import (
    BOM_PANEL,
    EXPLODED_PANEL,
    FEATURE_PANEL,
    FRONT_PANEL,
    MAIN_PANEL,
    PANELS,
    SHEET_HEIGHT,
    SHEET_WIDTH,
    SIDE_PANEL,
    TOP_PANEL,
    panel_bboxes,
)
from app.drawing.sheet.themes import DEFAULT_THEME, EngineeringTheme

if TYPE_CHECKING:
    from app.drawing.cad.engine import GeometryResult


Point = tuple[float, float]
WorldPoint = tuple[float, float, float]

# Product-board camera coefficients. Keeping these in one place makes the
# hero render wider than the orthographic views while retaining an engineering
# isometric feel and the same projection for SVG and PNG.
ISO_HORIZONTAL = 0.90
ISO_DEPTH = 0.30
ISO_VERTICAL = 0.58


@dataclass
class SceneItem:
    index: int
    part: PartSpec
    position: WorldPoint
    dimensions: tuple[float, float, float]
    axis: str
    number: int
    instance_id: str
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)


@dataclass
class IsoScene:
    items: list[SceneItem]
    origin: Point
    scale: float
    bounds: tuple[float, float, float, float]
    target: tuple[float, float, float, float]

    def project(self, point: WorldPoint) -> Point:
        return (
            self.origin[0] + (point[0] - point[1]) * ISO_HORIZONTAL * self.scale,
            self.origin[1] + (point[0] + point[1]) * ISO_DEPTH * self.scale - point[2] * ISO_VERTICAL * self.scale,
        )


@dataclass(frozen=True)
class SheetMetrics:
    length: float
    width: float
    height: float
    shaft_diameter: float
    mounting_length: float
    mounting_width: float
    source: str


def _svg_text(
    x: float,
    y: float,
    value: str,
    size: int,
    fill: str,
    weight: str = "400",
    anchor: str = "start",
    letter_spacing: float = 0,
) -> str:
    spacing = f' letter-spacing="{letter_spacing:g}px"' if letter_spacing else ""
    return (
        f'<text x="{x:g}" y="{y:g}" fill="{fill}" font-family="Arial,Segoe UI,sans-serif" '
        f'font-size="{size}px" font-weight="{weight}" text-anchor="{anchor}"{spacing}>'
        f"{escape(str(value))}</text>"
    )


def _svg_line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    stroke: str,
    width: float = 1.2,
    dash: str = "",
    opacity: float = 1.0,
) -> str:
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:g}" y1="{y1:g}" x2="{x2:g}" y2="{y2:g}" '
        f'stroke="{stroke}" stroke-width="{width:g}" opacity="{opacity:g}"{dash_attr}/>'
    )


def _svg_rect(
    x: float,
    y: float,
    width: float,
    height: float,
    stroke: str = "none",
    fill: str = "none",
    stroke_width: float = 1.0,
    rx: float = 0,
    opacity: float = 1.0,
) -> str:
    return (
        f'<rect x="{x:g}" y="{y:g}" width="{width:g}" height="{height:g}" rx="{rx:g}" '
        f'stroke="{stroke}" stroke-width="{stroke_width:g}" fill="{fill}" opacity="{opacity:g}"/>'
    )


def _svg_polygon(points: list[Point], fill: str, stroke: str, width: float = 1.0, opacity: float = 1.0) -> str:
    value = " ".join(f"{x:g},{y:g}" for x, y in points)
    return f'<polygon points="{value}" fill="{fill}" stroke="{stroke}" stroke-width="{width:g}" opacity="{opacity:g}"/>'


def _svg_polyline(points: list[Point], stroke: str, width: float = 1.0, fill: str = "none", opacity: float = 1.0) -> str:
    value = " ".join(f"{x:g},{y:g}" for x, y in points)
    return f'<polyline points="{value}" fill="{fill}" stroke="{stroke}" stroke-width="{width:g}" opacity="{opacity:g}"/>'


def _svg_ellipse(cx: float, cy: float, rx: float, ry: float, fill: str, stroke: str, width: float = 1.0, opacity: float = 1.0) -> str:
    return f'<ellipse cx="{cx:g}" cy="{cy:g}" rx="{rx:g}" ry="{ry:g}" fill="{fill}" stroke="{stroke}" stroke-width="{width:g}" opacity="{opacity:g}"/>'


def _svg_circle(cx: float, cy: float, radius: float, fill: str, stroke: str, width: float = 1.0) -> str:
    return f'<circle cx="{cx:g}" cy="{cy:g}" r="{radius:g}" fill="{fill}" stroke="{stroke}" stroke-width="{width:g}"/>'


def _fmt(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _part_dimensions(part: PartSpec) -> tuple[float, float, float]:
    if part.part_type in {"flange", "bearing", "gear"}:
        diameter = part.outer_diameter or part.length or 120.0
        return (diameter, diameter, part.height or 15.0)
    if part.part_type in {"shaft", "fastener"}:
        diameter = part.outer_diameter or part.width or part.height or 30.0
        # CadQuery extrudes a shaft along local Z.
        return (diameter, diameter, part.length or 120.0)
    return (part.length or 160.0, part.width or 100.0, part.height or 50.0)


def _rotate_dimensions(dimensions: tuple[float, float, float], rotation: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = dimensions
    rx, ry, rz = (abs(value) % 360 for value in rotation)
    if 45 < ry < 135 or 225 < ry < 315:
        x, z = z, x
    if 45 < rx < 135 or 225 < rx < 315:
        y, z = z, y
    if 45 < rz < 135 or 225 < rz < 315:
        x, y = y, x
    return x, y, z


def _part_axis(part: PartSpec, rotation: tuple[float, float, float]) -> str:
    if part.part_type not in {"flange", "shaft", "bearing", "gear"}:
        return "box"
    ry = abs(rotation[1]) % 360
    return "x" if 45 < ry < 135 or 225 < ry < 315 else "z"


def _assembly_items(spec: DrawingSpec, exploded: bool = False, unique: bool = False) -> list[SceneItem]:
    if spec.drawing_type != "assembly" or spec.assembly is None:
        part = spec.parts[0]
        return [SceneItem(0, part, (0.0, 0.0, 0.0), _part_dimensions(part), _part_axis(part, (0, 0, 0)), 1, "part")]

    by_id = {part.part_id: part for part in spec.parts}
    components = list(spec.assembly.components)
    if unique:
        first_by_part: dict[str | None, Any] = {}
        for component in components:
            first_by_part.setdefault(component.part_id, component)
        components = [first_by_part[row["part_number"]] for row in generate_bom(spec)]

    items: list[SceneItem] = []
    cursor = 0.0
    for index, component in enumerate(components):
        part = variant_part(by_id[component.part_id], component.variant)
        rotation = component.rotation
        if exploded and unique:
            # A regular pitch along the main axis makes the instruction-sheet
            # view legible even when source offsets have very different sizes.
            position = (cursor, 0.0, 0.0)
            cursor += max(_part_dimensions(part)) * 1.08 + 105.0
        else:
            base = component.position
            offset = component.exploded_offset if exploded else (0.0, 0.0, 0.0)
            position = (base[0] + offset[0], base[1] + offset[1], base[2] + offset[2])
        number = component.item_number or index + 1
        items.append(
            SceneItem(
                index=index,
                part=part,
                position=position,
                dimensions=_rotate_dimensions(_part_dimensions(part), rotation),
                axis=_part_axis(part, rotation),
                number=number,
                instance_id=component.instance_id,
            )
        )
    return items


def _project_raw(point: WorldPoint) -> Point:
    return ((point[0] - point[1]) * ISO_HORIZONTAL, (point[0] + point[1]) * ISO_DEPTH - point[2] * ISO_VERTICAL)


def _item_raw_points(item: SceneItem) -> list[Point]:
    x, y, z = item.position
    dx, dy, dz = item.dimensions
    return [_project_raw((x + px, y + py, z + pz)) for px in (0, dx) for py in (0, dy) for pz in (0, dz)]


def _raw_bounds(items: list[SceneItem]) -> tuple[float, float, float, float]:
    points = [point for item in items for point in _item_raw_points(item)]
    if not points:
        return (0.0, 0.0, 1.0, 1.0)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _make_scene(spec: DrawingSpec, panel: tuple[int, int, int, int], exploded: bool = False, unique: bool = False) -> IsoScene:
    items = _assembly_items(spec, exploded=exploded, unique=unique)
    raw_min_x, raw_min_y, raw_max_x, raw_max_y = _raw_bounds(items)
    raw_width = max(raw_max_x - raw_min_x, 1.0)
    raw_height = max(raw_max_y - raw_min_y, 1.0)
    target = (panel[0] + 34, panel[1] + 54, panel[2] - 68, panel[3] - 88)
    scale = min(target[2] / raw_width, target[3] / raw_height)
    target_center = (target[0] + target[2] / 2, target[1] + target[3] / 2)
    raw_center = ((raw_min_x + raw_max_x) / 2, (raw_min_y + raw_max_y) / 2)
    origin = (target_center[0] - raw_center[0] * scale, target_center[1] - raw_center[1] * scale)
    scene = IsoScene(items, origin, scale, (raw_min_x, raw_min_y, raw_max_x, raw_max_y), target)
    for item in scene.items:
        screen_points = [scene.project((item.position[0] + px, item.position[1] + py, item.position[2] + pz)) for px in (0, item.dimensions[0]) for py in (0, item.dimensions[1]) for pz in (0, item.dimensions[2])]
        xs = [point[0] for point in screen_points]
        ys = [point[1] for point in screen_points]
        item.bbox = (min(xs), min(ys), max(xs), max(ys))
    return scene


def _scene_item_point(scene: IsoScene, item: SceneItem, x: float, y: float, z: float) -> Point:
    return scene.project((item.position[0] + x, item.position[1] + y, item.position[2] + z))


def _circle_points(scene: IsoScene, center: WorldPoint, radius: float, plane: str = "xy", count: int = 32) -> list[Point]:
    points: list[Point] = []
    for index in range(count):
        theta = 2 * 3.141592653589793 * index / count
        c, s = cos(theta) * radius, sin(theta) * radius
        if plane == "yz":
            point = (center[0], center[1] + c, center[2] + s)
        elif plane == "xz":
            point = (center[0] + c, center[1], center[2] + s)
        else:
            point = (center[0] + c, center[1] + s, center[2])
        points.append(scene.project(point))
    return points


def _radial_points(scene: IsoScene, center: WorldPoint, root_radius: float, tip_radius: float, teeth: int, plane: str) -> list[Point]:
    points: list[Point] = []
    for index in range(teeth):
        base = 2 * 3.141592653589793 * index / teeth
        for offset, radius in ((0.00, root_radius), (0.42, root_radius), (0.52, tip_radius), (0.78, tip_radius)):
            theta = base + 2 * 3.141592653589793 * offset / teeth
            c, s = cos(theta) * radius, sin(theta) * radius
            if plane == "yz":
                point = (center[0], center[1] + c, center[2] + s)
            elif plane == "xz":
                point = (center[0] + c, center[1], center[2] + s)
            else:
                point = (center[0] + c, center[1] + s, center[2])
            points.append(scene.project(point))
    return points


def _item_corners(scene: IsoScene, item: SceneItem) -> tuple[Point, ...]:
    return tuple(_scene_item_point(scene, item, x, y, z) for x, y, z in ((0, 0, 0), (item.dimensions[0], 0, 0), (item.dimensions[0], item.dimensions[1], 0), (0, item.dimensions[1], 0), (0, 0, item.dimensions[2]), (item.dimensions[0], 0, item.dimensions[2]), (item.dimensions[0], item.dimensions[1], item.dimensions[2]), (0, item.dimensions[1], item.dimensions[2])))


def _draw_pil_box(draw: Any, scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> None:
    p000, p100, p110, p010, p001, p101, p111, p011 = _item_corners(scene, item)
    # Draw the bottom/side faces first, then the bright top face.
    draw.polygon([p000, p100, p110, p010], fill=theme.cad_dark, outline=theme.cad_dark)
    draw.polygon([p000, p010, p011, p001], fill=theme.metal_mid, outline=theme.cad_dark)
    draw.polygon([p000, p100, p101, p001], fill=theme.metal, outline=theme.cad_dark)
    draw.polygon([p010, p110, p111, p011], fill=theme.cad_light, outline=theme.cad_dark)
    draw.polygon([p001, p101, p111, p011], fill=theme.metal_highlight, outline=theme.cad_dark)
    draw.line([p001, p101, p111, p011, p001], fill=theme.cad_dark, width=1)
    draw.line([p001, p101], fill="#FFFFFF", width=1)


def _draw_pil_housing(draw: Any, scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> None:
    _draw_pil_box(draw, scene, item, theme)
    dx, dy, dz = item.dimensions
    if item.part.part_type not in {"housing", "bracket"}:
        return
    # Use the top face for the enclosure opening so an isolated housing is
    # recognizable as a machined gearbox shell, not as a flat tray. The
    # geometry itself still comes from CadQuery; these are deterministic
    # engineering-render details derived from the same dimensions.
    x0, x1 = dx * 0.16, dx * 0.84
    y0, y1 = dy * 0.16, dy * 0.84
    opening = [
        _scene_item_point(scene, item, x0, y0, dz + 0.5),
        _scene_item_point(scene, item, x1, y0, dz + 0.5),
        _scene_item_point(scene, item, x1, y1, dz + 0.5),
        _scene_item_point(scene, item, x0, y1, dz + 0.5),
    ]
    draw.polygon(opening, fill=theme.cavity, outline=theme.cad_dark)
    draw.line([opening[0], opening[1]], fill=theme.metal_highlight, width=1)

    # Raised inspection cover and its four visible fastener seats.
    if "lower" not in item.part.name.lower():
        cover_x0, cover_x1 = dx * 0.31, dx * 0.69
        cover_y0, cover_y1 = dy * 0.30, dy * 0.70
        cover = [
            _scene_item_point(scene, item, cover_x0, cover_y0, dz + 3.5),
            _scene_item_point(scene, item, cover_x1, cover_y0, dz + 3.5),
            _scene_item_point(scene, item, cover_x1, cover_y1, dz + 3.5),
            _scene_item_point(scene, item, cover_x0, cover_y1, dz + 3.5),
        ]
        draw.polygon(cover, fill=theme.metal_highlight, outline=theme.cad_dark)
        for px in (cover_x0 + dx * 0.025, cover_x1 - dx * 0.025):
            for py in (cover_y0 + dy * 0.025, cover_y1 - dy * 0.025):
                draw.polygon(_circle_points(scene, (item.position[0] + px, item.position[1] + py, item.position[2] + dz + 4), max(min(dx, dy) * 0.018, 2.0), "xy", 10), fill=theme.metal_mid, outline=theme.cad_dark)

    # Bearing seat on the right-hand side and three raised ribs on the front
    # wall give the enclosure a clear mechanical identity in the hero view.
    bore = item.part.bearing_bore_diameter or min(dy, dz) * 0.66
    bore_center = (item.position[0] + dx + 0.6, item.position[1] + dy * 0.50, item.position[2] + dz * 0.52)
    bore_ring = _circle_points(scene, bore_center, bore * 0.50, "yz", 28)
    draw.polygon(bore_ring, fill=theme.cad_dark, outline=theme.cad_dark)
    bore_inner = _circle_points(scene, bore_center, bore * 0.36, "yz", 28)
    draw.polygon(bore_inner, fill=theme.cavity, outline=theme.metal_highlight)
    for rib_x in (dx * 0.22, dx * 0.50, dx * 0.78):
        draw.line(
            [
                _scene_item_point(scene, item, rib_x, -0.8, dz * 0.14),
                _scene_item_point(scene, item, rib_x, -0.8, dz * 0.86),
            ],
            fill=theme.cad_dark,
            width=2,
        )

    # Housing split line / machined edge and shallow mounting feet.
    seam = [_scene_item_point(scene, item, 0, 0, dz * 0.12), _scene_item_point(scene, item, dx, 0, dz * 0.12)]
    draw.line(seam, fill=theme.cad_dark, width=1)
    if "upper" not in item.part.name.lower():
        foot_length = dx * 0.78
        foot_width = max(dy * 0.12, 24.0)
        foot_height = max(dz * 0.12, 7.0)
        for foot_y in (-foot_width * 0.70, dy - foot_width * 0.30):
            foot = SceneItem(
                index=item.index,
                part=item.part,
                position=(item.position[0] + dx * 0.11, item.position[1] + foot_y, item.position[2] - foot_height * 0.45),
                dimensions=(foot_length, foot_width, foot_height),
                axis="box",
                number=item.number,
                instance_id=item.instance_id,
            )
            _draw_pil_box(draw, scene, foot, theme)


def _draw_pil_flange(draw: Any, scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> None:
    _draw_pil_box(draw, scene, item, theme)
    dx, dy, dz = item.dimensions
    diameter = item.part.outer_diameter or item.part.length or max(dy, dz)
    radius = diameter / 2
    if item.axis == "x":
        center = (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2)
        plane = "yz"
        inner_radius = (item.part.inner_diameter or 0) / 2
    else:
        center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz)
        plane = "xy"
        inner_radius = (item.part.inner_diameter or 0) / 2
    outer = _circle_points(scene, center, radius, plane)
    draw.polygon(outer, fill=theme.metal_highlight, outline=theme.cad_dark)
    if inner_radius:
        inner = _circle_points(scene, center, inner_radius, plane)
        draw.polygon(inner, fill=theme.cavity, outline=theme.cad_dark)
        inner2 = _circle_points(scene, center, inner_radius * 0.72, plane)
        draw.line(inner2 + [inner2[0]], fill=theme.cad_dark, width=1)
    for hole in item.part.holes[:8]:
        if item.axis == "z":
            hole_center = (item.position[0] + hole.x, item.position[1] + hole.y, item.position[2] + dz + 0.5)
            draw.polygon(_circle_points(scene, hole_center, hole.diameter / 2, "xy", 16), fill=theme.cavity, outline=theme.cad_dark)
        else:
            # The output/motor flanges are mounted on an X-normal face after
            # the component's Y-rotation. Reuse the source hole coordinates
            # on that face so the bolt pattern remains visible in the hero.
            hole_center = (item.position[0] + dx + 0.5, item.position[1] + hole.y, item.position[2] + hole.x)
            draw.polygon(_circle_points(scene, hole_center, hole.diameter / 2, "yz", 16), fill=theme.cavity, outline=theme.cad_dark)


def _draw_pil_bearing(draw: Any, scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> None:
    _draw_pil_box(draw, scene, item, theme)
    dx, dy, dz = item.dimensions
    outer = item.part.outer_diameter or max(dy, dz)
    inner = item.part.inner_diameter or outer * 0.5
    if item.axis == "x":
        center = (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2)
        plane = "yz"
    else:
        center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz)
        plane = "xy"
    output_face = _circle_points(scene, center, outer / 2, plane)
    draw.polygon(output_face, fill=theme.metal_mid, outline=theme.cad_dark)
    bore = _circle_points(scene, center, inner / 2, plane)
    draw.polygon(bore, fill=theme.cavity, outline=theme.cad_dark)
    track_radius = (outer + inner) / 4
    roller_radius = max((outer - inner) * 0.095, 2.0)
    for index in range(8):
        theta = 2 * 3.141592653589793 * index / 8
        c, s = cos(theta) * track_radius, sin(theta) * track_radius
        if plane == "yz":
            roller_center = (center[0] + 0.5, center[1] + c, center[2] + s)
        else:
            roller_center = (center[0] + c, center[1] + s, center[2] + 0.5)
        draw.polygon(_circle_points(scene, roller_center, roller_radius, plane, 12), fill=theme.metal_highlight, outline=theme.cad_dark)
    draw.line(bore[: max(2, len(bore) // 2)], fill="#FFFFFF", width=1)


def _draw_pil_gear(draw: Any, scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> None:
    dx, dy, dz = item.dimensions
    diameter = item.part.gear_diameter or item.part.outer_diameter or max(dy, dz)
    teeth = item.part.gear_teeth or 24
    root_radius = diameter * 0.44
    tip_radius = diameter * 0.50
    if item.axis == "x":
        back_center = (item.position[0], item.position[1] + dy / 2, item.position[2] + dz / 2)
        front_center = (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2)
        plane = "yz"
    else:
        back_center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2])
        front_center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz)
        plane = "xy"
    back = _radial_points(scene, back_center, root_radius, tip_radius, teeth, plane)
    front = _radial_points(scene, front_center, root_radius, tip_radius, teeth, plane)
    for index in range(0, len(front), 2):
        next_index = (index + 1) % len(front)
        draw.polygon([back[index], back[next_index], front[next_index], front[index]], fill=theme.cad_dark, outline=theme.cad_dark)
    draw.polygon(front, fill=theme.metal_mid, outline=theme.cad_dark)
    bore_radius = (item.part.inner_diameter or diameter * 0.24) / 2
    draw.polygon(_circle_points(scene, front_center, bore_radius, plane), fill=theme.cavity, outline=theme.cad_dark)
    hub_radius = max(bore_radius * 1.55, diameter * 0.15)
    draw.polygon(_circle_points(scene, front_center, hub_radius, plane), fill=theme.metal, outline=theme.cad_dark)
    draw.polygon(_circle_points(scene, front_center, bore_radius, plane), fill=theme.cavity, outline=theme.cad_dark)


def _draw_pil_motor(draw: Any, scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> None:
    _draw_pil_box(draw, scene, item, theme)
    dx, dy, dz = item.dimensions
    center = (item.position[0], item.position[1] + dy / 2, item.position[2] + dz / 2)
    flange_radius = (item.part.outer_diameter or min(dy, dz) * 0.55) / 2
    draw.polygon(_circle_points(scene, center, flange_radius, "yz"), fill=theme.metal_mid, outline=theme.cad_dark)
    draw.polygon(_circle_points(scene, (center[0] - 10, center[1], center[2]), flange_radius * 0.45, "yz"), fill=theme.cavity, outline=theme.cad_dark)
    shaft = _circle_points(scene, (center[0] - 28, center[1], center[2]), flange_radius * 0.25, "yz")
    draw.polygon(shaft, fill=theme.metal_highlight, outline=theme.cad_dark)
    terminal = [
        _scene_item_point(scene, item, dx * 0.27, dy * 0.62, dz),
        _scene_item_point(scene, item, dx * 0.49, dy * 0.62, dz),
        _scene_item_point(scene, item, dx * 0.49, dy * 0.90, dz),
        _scene_item_point(scene, item, dx * 0.27, dy * 0.90, dz),
    ]
    draw.polygon(terminal, fill=theme.cad_dark, outline=theme.metal_highlight)
    for index in range(1, 5):
        x = dx * (0.12 + index * 0.14)
        draw.line([_scene_item_point(scene, item, x, 0, dz * 0.10), _scene_item_point(scene, item, x, 0, dz * 0.90)], fill=theme.cad_dark, width=1)


def _draw_pil_fastener(draw: Any, scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> None:
    _draw_pil_shaft(draw, scene, item, theme)
    dx, dy, dz = item.dimensions
    center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz)
    draw.polygon(_radial_points(scene, center, min(dx, dy) * 0.66, min(dx, dy) * 0.82, 6, "xy"), fill=theme.metal_mid, outline=theme.cad_dark)


def _draw_pil_shaft(draw: Any, scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> None:
    sections = [(section.length, section.diameter) for section in item.part.shaft_sections]
    if sections:
        cursor = 0.0
        for section_length, section_diameter in sections:
            if item.axis == "x":
                position = (item.position[0] + cursor, item.position[1], item.position[2])
                dimensions = (section_length, section_diameter, section_diameter)
            else:
                position = (item.position[0], item.position[1], item.position[2] + cursor)
                dimensions = (section_diameter, section_diameter, section_length)
            segment = SceneItem(item.index, item.part, position, dimensions, item.axis, item.number, item.instance_id)
            _draw_pil_box(draw, scene, segment, theme)
            cursor += section_length
    else:
        _draw_pil_box(draw, scene, item, theme)
    dx, dy, dz = item.dimensions
    if item.axis == "x":
        cap = _circle_points(scene, (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2), min(dy, dz) / 2, "yz")
    else:
        cap = _circle_points(scene, (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz), min(dx, dy) / 2, "xy")
    draw.polygon(cap, fill=theme.metal_highlight, outline=theme.cad_dark)
    draw.line(cap[: max(2, len(cap) // 2)], fill="#FFFFFF", width=1)


def _draw_pil_item(draw: Any, scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> None:
    if item.part.part_type == "flange":
        _draw_pil_flange(draw, scene, item, theme)
    elif item.part.part_type == "bearing":
        _draw_pil_bearing(draw, scene, item, theme)
    elif item.part.part_type == "gear":
        _draw_pil_gear(draw, scene, item, theme)
    elif item.part.part_type == "shaft":
        _draw_pil_shaft(draw, scene, item, theme)
    elif item.part.part_type == "motor":
        _draw_pil_motor(draw, scene, item, theme)
    elif item.part.part_type == "fastener":
        _draw_pil_fastener(draw, scene, item, theme)
    elif item.part.part_type in {"housing", "bracket"}:
        _draw_pil_housing(draw, scene, item, theme)
    else:
        _draw_pil_box(draw, scene, item, theme)
    if item.part.name == "Servo Motor":
        dx, dy, dz = item.dimensions
        cap = _circle_points(scene, (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2), min(dy, dz) * 0.34, "yz")
        draw.polygon(cap, fill=theme.cad_dark, outline=theme.metal_highlight)


def _render_pil_scene(image: Any, scene: IsoScene, theme: EngineeringTheme) -> None:
    from PIL import Image, ImageDraw, ImageFilter

    shadow_layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    for item in scene.items:
        x0, y0, x1, y1 = item.bbox
        shadow_draw.ellipse((x0 + 8, y1 - 10, x1 + 12, y1 + 8), fill=(70, 85, 96, 34))
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(5))
    image.paste(shadow_layer, (0, 0), shadow_layer)
    draw = ImageDraw.Draw(image)
    # Lower objects are drawn first to create a readable assembly depth order.
    for item in sorted(scene.items, key=lambda value: (value.position[2], value.position[0] + value.position[1])):
        _draw_pil_item(draw, scene, item, theme)


def _svg_defs(theme: EngineeringTheme) -> str:
    return (
        "<defs>"
        f'<linearGradient id="metalTop" x1="0" y1="0" x2="0.8" y2="1">'
        f'<stop offset="0" stop-color="{theme.metal_highlight}"/><stop offset="0.55" stop-color="{theme.cad_light}"/><stop offset="1" stop-color="{theme.metal}"/></linearGradient>'
        f'<linearGradient id="metalSide" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{theme.metal}"/><stop offset="1" stop-color="{theme.metal_mid}"/></linearGradient>'
        f'<filter id="softShadow" x="-20%" y="-20%" width="140%" height="160%"><feGaussianBlur stdDeviation="4"/></filter>'
        "</defs>"
    )


def _svg_item_corners(scene: IsoScene, item: SceneItem) -> tuple[Point, ...]:
    return _item_corners(scene, item)


def _svg_box(scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> str:
    p000, p100, p110, p010, p001, p101, p111, p011 = _svg_item_corners(scene, item)
    return "".join(
        [
            _svg_polygon([p000, p100, p110, p010], theme.cad_dark, theme.cad_dark),
            _svg_polygon([p000, p010, p011, p001], theme.metal_mid, theme.cad_dark),
            _svg_polygon([p000, p100, p101, p001], "url(#metalSide)", theme.cad_dark),
            _svg_polygon([p010, p110, p111, p011], theme.cad_light, theme.cad_dark),
            _svg_polygon([p001, p101, p111, p011], "url(#metalTop)", theme.cad_dark),
            _svg_polyline([p001, p101, p111, p011, p001], theme.cad_dark, 1.0),
            _svg_line(p001[0], p001[1], p101[0], p101[1], "#FFFFFF", 1.0),
        ]
    )


def _svg_housing(scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> str:
    output = [_svg_box(scene, item, theme)]
    if item.part.part_type not in {"housing", "bracket"}:
        return "".join(output)
    dx, dy, dz = item.dimensions
    x0, x1 = dx * 0.16, dx * 0.84
    y0, y1 = dy * 0.16, dy * 0.84
    opening = [_scene_item_point(scene, item, x0, y0, dz + 0.5), _scene_item_point(scene, item, x1, y0, dz + 0.5), _scene_item_point(scene, item, x1, y1, dz + 0.5), _scene_item_point(scene, item, x0, y1, dz + 0.5)]
    output.append(_svg_polygon(opening, theme.cavity, theme.cad_dark, 1.0))
    output.append(_svg_line(opening[0][0], opening[0][1], opening[1][0], opening[1][1], "#FFFFFF", 1.0))
    if "lower" not in item.part.name.lower():
        cover_x0, cover_x1 = dx * 0.31, dx * 0.69
        cover_y0, cover_y1 = dy * 0.30, dy * 0.70
        cover = [_scene_item_point(scene, item, cover_x0, cover_y0, dz + 3.5), _scene_item_point(scene, item, cover_x1, cover_y0, dz + 3.5), _scene_item_point(scene, item, cover_x1, cover_y1, dz + 3.5), _scene_item_point(scene, item, cover_x0, cover_y1, dz + 3.5)]
        output.append(_svg_polygon(cover, theme.metal_highlight, theme.cad_dark, 1.0))
        for px in (cover_x0 + dx * 0.025, cover_x1 - dx * 0.025):
            for py in (cover_y0 + dy * 0.025, cover_y1 - dy * 0.025):
                output.append(_svg_polygon(_circle_points(scene, (item.position[0] + px, item.position[1] + py, item.position[2] + dz + 4), max(min(dx, dy) * 0.018, 2.0), "xy", 10), theme.metal_mid, theme.cad_dark, 0.6))
    bore = item.part.bearing_bore_diameter or min(dy, dz) * 0.66
    bore_center = (item.position[0] + dx + 0.6, item.position[1] + dy * 0.50, item.position[2] + dz * 0.52)
    output.append(_svg_polygon(_circle_points(scene, bore_center, bore * 0.50, "yz", 28), theme.cad_dark, theme.cad_dark, 1.0))
    output.append(_svg_polygon(_circle_points(scene, bore_center, bore * 0.36, "yz", 28), theme.cavity, theme.metal_highlight, 0.8))
    for rib_x in (dx * 0.22, dx * 0.50, dx * 0.78):
        p0 = _scene_item_point(scene, item, rib_x, -0.8, dz * 0.14)
        p1 = _scene_item_point(scene, item, rib_x, -0.8, dz * 0.86)
        output.append(_svg_line(p0[0], p0[1], p1[0], p1[1], theme.cad_dark, 1.5))
    seam = [_scene_item_point(scene, item, 0, 0, dz * 0.12), _scene_item_point(scene, item, dx, 0, dz * 0.12)]
    output.append(_svg_line(seam[0][0], seam[0][1], seam[1][0], seam[1][1], theme.cad_dark, 1.0))
    return "".join(output)


def _svg_flange(scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> str:
    output = [_svg_box(scene, item, theme)]
    dx, dy, dz = item.dimensions
    diameter = item.part.outer_diameter or item.part.length or max(dy, dz)
    radius = diameter / 2
    if item.axis == "x":
        center = (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2)
        plane = "yz"
    else:
        center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz)
        plane = "xy"
    outer = _circle_points(scene, center, radius, plane)
    output.append(_svg_polygon(outer, "url(#metalTop)", theme.cad_dark, 1.0))
    inner_radius = (item.part.inner_diameter or 0) / 2
    if inner_radius:
        inner = _circle_points(scene, center, inner_radius, plane)
        output.append(_svg_polygon(inner, theme.cavity, theme.cad_dark, 1.0))
    if item.axis == "z":
        for hole in item.part.holes[:8]:
            hole_center = (item.position[0] + hole.x, item.position[1] + hole.y, item.position[2] + dz + 0.5)
            output.append(_svg_polygon(_circle_points(scene, hole_center, hole.diameter / 2, "xy", 16), theme.cavity, theme.cad_dark, 0.8))
    else:
        for hole in item.part.holes[:8]:
            hole_center = (item.position[0] + dx + 0.5, item.position[1] + hole.y, item.position[2] + hole.x)
            output.append(_svg_polygon(_circle_points(scene, hole_center, hole.diameter / 2, "yz", 16), theme.cavity, theme.cad_dark, 0.8))
    return "".join(output)


def _svg_shaft(scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> str:
    output: list[str] = []
    sections = [(section.length, section.diameter) for section in item.part.shaft_sections]
    if sections:
        cursor = 0.0
        for section_length, section_diameter in sections:
            if item.axis == "x":
                position = (item.position[0] + cursor, item.position[1], item.position[2])
                dimensions = (section_length, section_diameter, section_diameter)
            else:
                position = (item.position[0], item.position[1], item.position[2] + cursor)
                dimensions = (section_diameter, section_diameter, section_length)
            segment = SceneItem(item.index, item.part, position, dimensions, item.axis, item.number, item.instance_id)
            output.append(_svg_box(scene, segment, theme))
            cursor += section_length
    else:
        output.append(_svg_box(scene, item, theme))
    dx, dy, dz = item.dimensions
    if item.axis == "x":
        center = (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2)
        radius = min(dy, dz) / 2
        plane = "yz"
    else:
        center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz)
        radius = min(dx, dy) / 2
        plane = "xy"
    output.append(_svg_polygon(_circle_points(scene, center, radius, plane), "url(#metalTop)", theme.cad_dark, 1.0))
    return "".join(output)


def _svg_bearing(scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> str:
    output = [_svg_box(scene, item, theme)]
    dx, dy, dz = item.dimensions
    outer = item.part.outer_diameter or max(dy, dz)
    inner = item.part.inner_diameter or outer * 0.5
    if item.axis == "x":
        center = (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2)
        plane = "yz"
    else:
        center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz)
        plane = "xy"
    output.append(_svg_polygon(_circle_points(scene, center, outer / 2, plane), theme.metal_mid, theme.cad_dark, 1.0))
    output.append(_svg_polygon(_circle_points(scene, center, inner / 2, plane), theme.cavity, theme.cad_dark, 1.0))
    track_radius = (outer + inner) / 4
    roller_radius = max((outer - inner) * 0.095, 2.0)
    for index in range(8):
        theta = 2 * 3.141592653589793 * index / 8
        c, s = cos(theta) * track_radius, sin(theta) * track_radius
        roller_center = (center[0] + (0.5 if plane == "yz" else c), center[1] + (c if plane == "yz" else s), center[2] + (s if plane == "yz" else 0.5))
        output.append(_svg_polygon(_circle_points(scene, roller_center, roller_radius, plane, 12), theme.metal_highlight, theme.cad_dark, 0.7))
    return "".join(output)


def _svg_gear(scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> str:
    dx, dy, dz = item.dimensions
    diameter = item.part.gear_diameter or item.part.outer_diameter or max(dy, dz)
    teeth = item.part.gear_teeth or 24
    root_radius, tip_radius = diameter * 0.44, diameter * 0.50
    if item.axis == "x":
        back_center = (item.position[0], item.position[1] + dy / 2, item.position[2] + dz / 2)
        front_center = (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2)
        plane = "yz"
    else:
        back_center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2])
        front_center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz)
        plane = "xy"
    back = _radial_points(scene, back_center, root_radius, tip_radius, teeth, plane)
    front = _radial_points(scene, front_center, root_radius, tip_radius, teeth, plane)
    output: list[str] = []
    for index in range(0, len(front), 2):
        next_index = (index + 1) % len(front)
        output.append(_svg_polygon([back[index], back[next_index], front[next_index], front[index]], theme.cad_dark, theme.cad_dark, 0.7))
    output.append(_svg_polygon(front, theme.metal_mid, theme.cad_dark, 1.0))
    bore_radius = (item.part.inner_diameter or diameter * 0.24) / 2
    output.append(_svg_polygon(_circle_points(scene, front_center, max(bore_radius * 1.55, diameter * 0.15), plane), theme.metal, theme.cad_dark, 0.8))
    output.append(_svg_polygon(_circle_points(scene, front_center, bore_radius, plane), theme.cavity, theme.cad_dark, 1.0))
    return "".join(output)


def _svg_motor(scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> str:
    output = [_svg_box(scene, item, theme)]
    dx, dy, dz = item.dimensions
    center = (item.position[0], item.position[1] + dy / 2, item.position[2] + dz / 2)
    flange_radius = (item.part.outer_diameter or min(dy, dz) * 0.55) / 2
    output.append(_svg_polygon(_circle_points(scene, center, flange_radius, "yz"), theme.metal_mid, theme.cad_dark, 1.0))
    output.append(_svg_polygon(_circle_points(scene, (center[0] - 10, center[1], center[2]), flange_radius * 0.45, "yz"), theme.cavity, theme.cad_dark, 1.0))
    terminal = [_scene_item_point(scene, item, dx * 0.27, dy * 0.62, dz), _scene_item_point(scene, item, dx * 0.49, dy * 0.62, dz), _scene_item_point(scene, item, dx * 0.49, dy * 0.90, dz), _scene_item_point(scene, item, dx * 0.27, dy * 0.90, dz)]
    output.append(_svg_polygon(terminal, theme.cad_dark, theme.metal_highlight, 1.0))
    for index in range(1, 5):
        xx = dx * (0.12 + index * 0.14)
        output.append(_svg_line(*_scene_item_point(scene, item, xx, 0, dz * 0.10), *_scene_item_point(scene, item, xx, 0, dz * 0.90), theme.cad_dark, 1.0))
    return "".join(output)


def _svg_fastener(scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> str:
    output = [_svg_shaft(scene, item, theme)]
    dx, dy, dz = item.dimensions
    center = (item.position[0] + dx / 2, item.position[1] + dy / 2, item.position[2] + dz)
    output.append(_svg_polygon(_radial_points(scene, center, min(dx, dy) * 0.66, min(dx, dy) * 0.82, 6, "xy"), theme.metal_mid, theme.cad_dark, 0.8))
    return "".join(output)


def _svg_item(scene: IsoScene, item: SceneItem, theme: EngineeringTheme) -> str:
    if item.part.part_type == "flange":
        output = _svg_flange(scene, item, theme)
    elif item.part.part_type == "bearing":
        output = _svg_bearing(scene, item, theme)
    elif item.part.part_type == "gear":
        output = _svg_gear(scene, item, theme)
    elif item.part.part_type == "shaft":
        output = _svg_shaft(scene, item, theme)
    elif item.part.part_type == "motor":
        output = _svg_motor(scene, item, theme)
    elif item.part.part_type == "fastener":
        output = _svg_fastener(scene, item, theme)
    elif item.part.part_type in {"housing", "bracket"}:
        output = _svg_housing(scene, item, theme)
    else:
        output = _svg_box(scene, item, theme)
    if item.part.name == "Servo Motor":
        dx, dy, dz = item.dimensions
        center = (item.position[0] + dx, item.position[1] + dy / 2, item.position[2] + dz / 2)
        output += _svg_polygon(_circle_points(scene, center, min(dy, dz) * 0.34, "yz"), theme.cad_dark, theme.metal_highlight, 1.0)
    return output


def _render_svg_scene(scene: IsoScene, theme: EngineeringTheme) -> str:
    output = []
    for item in sorted(scene.items, key=lambda value: (value.position[2], value.position[0] + value.position[1])):
        x0, y0, x1, y1 = item.bbox
        output.append(_svg_ellipse((x0 + x1) / 2 + 8, y1 - 1, max((x1 - x0) * 0.42, 8), 5, theme.shadow, "none", 0, 0.28))
    output.append('<g filter="url(#softShadow)">')
    for item in sorted(scene.items, key=lambda value: (value.position[2], value.position[0] + value.position[1])):
        output.append(_svg_item(scene, item, theme))
    output.append("</g>")
    return "".join(output)


def _bbox_from_native(geometry: GeometryResult | None) -> tuple[float, float, float, float, float, float] | None:
    if geometry is None or geometry.native is None:
        return None
    try:
        box = geometry.native.BoundingBox()
        return (float(box.xmin), float(box.ymin), float(box.zmin), float(box.xmax), float(box.ymax), float(box.zmax))
    except Exception:
        return None


def _world_axis_bounds(items: list[SceneItem], axes: tuple[int, int]) -> tuple[float, float, float, float]:
    values: list[tuple[float, float]] = []
    for item in items:
        values.append((item.position[axes[0]], item.position[axes[0]] + item.dimensions[axes[0]]))
        values.append((item.position[axes[1]], item.position[axes[1]] + item.dimensions[axes[1]]))
    if not values:
        return (0, 0, 1, 1)
    first = [value[0] for value in values[::2]]
    second = [value[1] for value in values[::2]]
    first2 = [value[0] for value in values[1::2]]
    second2 = [value[1] for value in values[1::2]]
    return min(first), min(first2), max(second), max(second2)


def _metrics(spec: DrawingSpec, geometry: GeometryResult | None) -> SheetMetrics:
    native = _bbox_from_native(geometry)
    items = _assembly_items(spec)
    fallback = _world_axis_bounds(items, (0, 1))
    if native is not None:
        length = native[3] - native[0]
        width = native[4] - native[1]
        height = native[5] - native[2]
        source = "CadQuery BoundingBox"
    else:
        length = fallback[2] - fallback[0]
        width = fallback[3] - fallback[1]
        height = max(item.position[2] + item.dimensions[2] for item in items) - min(item.position[2] for item in items)
        source = "DrawingSpec bounds"
    shaft = next((item for item in spec.parts if item.part_type == "shaft"), None)
    shaft_diameter = (shaft.outer_diameter or shaft.width or shaft.height) if shaft else 0.0
    base = next((item for item in spec.parts if item.name.lower() == "mounting base"), None)
    if base is None:
        base = spec.parts[0]
    mounting_length = base.length or base.outer_diameter or 0.0
    mounting_width = base.width or base.outer_diameter or 0.0
    return SheetMetrics(length, width, height, shaft_diameter, mounting_length, mounting_width, source)


def _metadata(part: PartSpec) -> list[tuple[str, str]]:
    return [
        ("PART", part.name.upper()),
        ("LENGTH", f"{_fmt(part.length or part.outer_diameter or 0)} mm"),
        ("WIDTH", f"{_fmt(part.width or part.outer_diameter or 0)} mm"),
        ("HEIGHT", f"{_fmt(part.height or 0)} mm"),
        ("MATERIAL", part.material),
        ("PROCESS", "Concept"),
        ("TOLERANCE", "N/A"),
        ("SURFACE FINISH", "Demo"),
    ]


def _key_part(spec: DrawingSpec) -> PartSpec:
    if spec.drawing_type == "assembly":
        return next((part for part in spec.parts if part.name == "Main Housing Upper"), spec.parts[0])
    return spec.parts[0]


def _short(value: str, length: int) -> str:
    value = str(value)
    return value if len(value) <= length else value[: max(1, length - 1)] + "…"


def _callouts(spec: DrawingSpec, scene: IsoScene) -> list[tuple[str, str, Point, Point]]:
    panel_x, panel_y, panel_w, panel_h = MAIN_PANEL
    by_instance = {item.instance_id: item for item in scene.items}
    if spec.drawing_type == "assembly":
        by_part_id = {part.part_id: part for part in spec.parts}
        shaft = next((part for part in spec.parts if part.part_type == "shaft"), None)
        upper = next((part for part in spec.parts if part.name == "Main Housing Upper"), None)
        adapter = by_part_id.get(next((item.part.part_id for item in scene.items if item.instance_id == "motor-adapter"), None))
        base = next((part for part in spec.parts if part.name.lower() == "mounting base"), None)
        motor = next((part for part in spec.parts if part.part_type == "motor"), None)
        shaft_label = f"Ø{_fmt(shaft.outer_diameter or shaft.width or 0)} stepped alloy shaft" if shaft else "Stepped alloy shaft"
        housing_label = f"{_fmt(upper.length or 0)} × {_fmt(upper.width or 0)} mm ribbed enclosure" if upper else "Ribbed gearbox enclosure"
        adapter_label = f"Ø{_fmt(adapter.outer_diameter or adapter.length or 0)} adapter / bore" if adapter else "Adapter flange / bore"
        base_label = f"{_fmt(base.length or 0)} × {_fmt(base.width or 0)} mm platform" if base else "Mounting platform"
        motor_label = f"{motor.material} / finned body" if motor else "IEC motor package"
        definitions = [
            ("output-shaft", "Output Shaft", shaft_label, (panel_x + 64, panel_y + 72)),
            ("housing-upper", "Upper Housing", housing_label, (panel_x + 290, panel_y + 70)),
            ("motor-adapter", "Motor Interface", adapter_label, (panel_x + 650, panel_y + 72)),
            ("mounting-base", "Mounting Base", base_label, (panel_x + 66, panel_y + panel_h - 46)),
            ("servo-motor", "Servo Motor", motor_label, (panel_x + 690, panel_y + panel_h - 46)),
        ]
        output: list[tuple[str, str, Point, Point]] = []
        for instance_id, label, description, text_point in definitions:
            item = by_instance.get(instance_id)
            if item is None:
                continue
            x0, y0, x1, y1 = item.bbox
            output.append((label, description, ((x0 + x1) / 2, (y0 + y1) / 2), text_point))
        return output
    item = scene.items[0]
    x0, y0, x1, y1 = item.bbox
    return [("Primary Workpiece", item.part.name, ((x0 + x1) / 2, (y0 + y1) / 2), (panel_x + 66, panel_y + 72))]


def _leader_points(anchor: Point, text_point: Point) -> list[Point]:
    ax, ay = anchor
    tx, ty = text_point
    end_x = tx - 10 if tx <= ax else tx + 10
    # Keep the leader above the label baseline so it never cuts through the
    # blue callout title or its gray description.
    elbow_y = ty - 10
    mid_x = ax + (end_x - ax) * 0.55
    return [anchor, (mid_x, elbow_y), (end_x, elbow_y), (end_x, ty - 5)]


def _draw_pil_callouts(draw: Any, callouts: list[tuple[str, str, Point, Point]], theme: EngineeringTheme) -> None:
    for label, description, anchor, text_point in callouts:
        points = _leader_points(anchor, text_point)
        draw.line(points, fill=theme.accent_color, width=2)
        draw.ellipse((anchor[0] - 3, anchor[1] - 3, anchor[0] + 3, anchor[1] + 3), fill=theme.accent_color)
        _draw_pil_text(draw, text_point, label, theme.typography.H3, theme.accent_color, bold=True)
        _draw_pil_text(draw, (text_point[0], text_point[1] + 16), description, theme.typography.Caption, theme.body_text)


def _draw_svg_callouts(callouts: list[tuple[str, str, Point, Point]], theme: EngineeringTheme) -> str:
    output: list[str] = []
    for label, description, anchor, text_point in callouts:
        points = _leader_points(anchor, text_point)
        output.append(_svg_polyline(points, theme.accent_color, 1.5))
        output.append(_svg_circle(anchor[0], anchor[1], 3, theme.accent_color, theme.accent_color, 0))
        output.append(_svg_text(text_point[0], text_point[1], label, theme.typography.H3, theme.accent_color, "700"))
        output.append(_svg_text(text_point[0], text_point[1] + 16, description, theme.typography.Caption, theme.body_text))
    return "".join(output)


def _font(size: int):
    try:
        from PIL import ImageFont
    except Exception:
        return None
    candidates = [
        os.environ.get("FACTORYAGENT_FONT", ""),
        "/mnt/c/Windows/Fonts/arial.ttf",
        "/mnt/c/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _draw_pil_text(draw: Any, xy: tuple[float, float], text: str, size: int, fill: str, anchor: str = "la", bold: bool = False) -> None:
    font = _font(max(int(size) + (1 if bold else 0), 1))
    if font is not None:
        draw.text(xy, str(text), font=font, fill=fill, anchor=anchor)


def _draw_pil_panel(draw: Any, panel: tuple[int, int, int, int], theme: EngineeringTheme) -> None:
    x, y, w, h = panel
    draw.rectangle((x, y, x + w, y + h), outline=theme.border_color, width=1)


def _arrow(draw: Any, point: Point, direction: int, color: str) -> None:
    x, y = point
    draw.polygon([(x, y), (x + direction * 7, y - 3), (x + direction * 7, y + 3)], fill=color)


def _dimension_pil(draw: Any, x1: float, y1: float, x2: float, y2: float, label: str, theme: EngineeringTheme, vertical: bool = False) -> None:
    draw.line((x1, y1, x2, y2), fill=theme.dimension_color, width=1)
    if vertical:
        _arrow(draw, (x1, y1), 1, theme.dimension_color)
        _arrow(draw, (x2, y2), -1, theme.dimension_color)
        _draw_pil_text(draw, (x1 + 8, (y1 + y2) / 2), label, theme.typography.Dimension, theme.dimension_color, anchor="lm")
    else:
        _arrow(draw, (x1, y1), 1, theme.dimension_color)
        _arrow(draw, (x2, y2), -1, theme.dimension_color)
        _draw_pil_text(draw, ((x1 + x2) / 2, y1 - 7), label, theme.typography.Dimension, theme.dimension_color, anchor="ms")


def _dimension_svg(x1: float, y1: float, x2: float, y2: float, label: str, theme: EngineeringTheme, vertical: bool = False) -> str:
    output = [_svg_line(x1, y1, x2, y2, theme.dimension_color, 1.0)]
    if vertical:
        output.append(_svg_polygon([(x1, y1), (x1 - 4, y1 + 8), (x1 + 4, y1 + 8)], theme.dimension_color, theme.dimension_color, 0.5))
        output.append(_svg_polygon([(x2, y2), (x2 - 4, y2 - 8), (x2 + 4, y2 - 8)], theme.dimension_color, theme.dimension_color, 0.5))
        output.append(_svg_text(x1 + 8, (y1 + y2) / 2, label, theme.typography.Dimension, theme.dimension_color))
    else:
        output.append(_svg_polygon([(x1, y1), (x1 + 8, y1 - 4), (x1 + 8, y1 + 4)], theme.dimension_color, theme.dimension_color, 0.5))
        output.append(_svg_polygon([(x2, y2), (x2 - 8, y2 - 4), (x2 - 8, y2 + 4)], theme.dimension_color, theme.dimension_color, 0.5))
        output.append(_svg_text((x1 + x2) / 2, y1 - 7, label, theme.typography.Dimension, theme.dimension_color, anchor="middle"))
    return "".join(output)


def _dashed_line_pil(draw: Any, start: Point, end: Point, fill: str, width: int = 1, dash: float = 5, gap: float = 4) -> None:
    """Draw a small center/hidden line with Pillow's primitive API."""

    x0, y0 = start
    x1, y1 = end
    length = hypot(x1 - x0, y1 - y0)
    if length <= 0:
        return
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    cursor = 0.0
    while cursor < length:
        end_cursor = min(cursor + dash, length)
        draw.line(
            (x0 + ux * cursor, y0 + uy * cursor, x0 + ux * end_cursor, y0 + uy * end_cursor),
            fill=fill,
            width=width,
        )
        cursor += dash + gap


def _ortho_circle(item: SceneItem, axes: tuple[int, int]) -> tuple[tuple[float, float], float] | None:
    """Return the screen-plane center/radius for an end-on round component."""

    if item.axis == "x" and axes == (1, 2):
        return ((item.position[1] + item.dimensions[1] / 2, item.position[2] + item.dimensions[2] / 2), min(item.dimensions[1], item.dimensions[2]) / 2)
    if item.axis == "z" and axes == (0, 1):
        return ((item.position[0] + item.dimensions[0] / 2, item.position[1] + item.dimensions[1] / 2), min(item.dimensions[0], item.dimensions[1]) / 2)
    return None


def _draw_ortho_details_pil(draw: Any, item: SceneItem, axes: tuple[int, int], transform: Any, theme: EngineeringTheme) -> None:
    h0, v0, h1, v1 = _axis_item_rect(item, *axes)
    p0, p1 = transform((h0, v0)), transform((h1, v1))
    circle = _ortho_circle(item, axes)
    if circle and item.part.part_type in {"flange", "bearing", "gear"}:
        (center_h, center_v), radius = circle
        center = transform((center_h, center_v))
        screen_radius = abs(transform((center_h + radius, center_v))[0] - center[0])
        draw.ellipse((center[0] - screen_radius, center[1] - screen_radius, center[0] + screen_radius, center[1] + screen_radius), outline=theme.cad_dark, width=1)
        inner = item.part.inner_diameter
        if inner:
            inner_radius = screen_radius * inner / max(item.part.outer_diameter or item.part.gear_diameter or radius * 2, 1)
            draw.ellipse((center[0] - inner_radius, center[1] - inner_radius, center[0] + inner_radius, center[1] + inner_radius), outline=theme.dimension_color, width=1)
        cross = max(min(screen_radius * 0.45, 12), 4)
        _dashed_line_pil(draw, (center[0] - cross, center[1]), (center[0] + cross, center[1]), theme.dimension_color)
        _dashed_line_pil(draw, (center[0], center[1] - cross), (center[0], center[1] + cross), theme.dimension_color)
        if item.part.part_type == "flange":
            bolt_circle = item.part.bolt_circle_diameter or (item.part.outer_diameter or radius * 2) * 0.72
            hole_radius = screen_radius * bolt_circle / max(item.part.outer_diameter or radius * 2, 1)
            for index in range(8):
                angle = 2 * 3.141592653589793 * index / 8
                hx = center[0] + cos(angle) * hole_radius
                hy = center[1] + sin(angle) * hole_radius
                hole_size = max(screen_radius * 0.045, 2)
                draw.ellipse((hx - hole_size, hy - hole_size, hx + hole_size, hy + hole_size), outline=theme.dimension_color, width=1)
    elif item.part.part_type == "shaft":
        _dashed_line_pil(draw, (p0[0], (p0[1] + p1[1]) / 2), (p1[0], (p0[1] + p1[1]) / 2), theme.dimension_color)
        _dashed_line_pil(draw, ((p0[0] + p1[0]) / 2, p0[1]), ((p0[0] + p1[0]) / 2, p1[1]), theme.dimension_color)
    elif item.part.part_type in {"housing", "bracket"}:
        inset_h = (h1 - h0) * 0.14
        inset_v = (v1 - v0) * 0.18
        inner0 = transform((h0 + inset_h, v0 + inset_v))
        inner1 = transform((h1 - inset_h, v1 - inset_v))
        _dashed_line_pil(draw, (inner0[0], inner0[1]), (inner1[0], inner0[1]), theme.dimension_color)
        _dashed_line_pil(draw, (inner1[0], inner0[1]), (inner1[0], inner1[1]), theme.dimension_color)
        _dashed_line_pil(draw, (inner1[0], inner1[1]), (inner0[0], inner1[1]), theme.dimension_color)
        _dashed_line_pil(draw, (inner0[0], inner1[1]), (inner0[0], inner0[1]), theme.dimension_color)


def _axis_item_rect(item: SceneItem, horizontal_axis: int, vertical_axis: int) -> tuple[float, float, float, float]:
    h0 = item.position[horizontal_axis]
    h1 = h0 + item.dimensions[horizontal_axis]
    v0 = item.position[vertical_axis]
    v1 = v0 + item.dimensions[vertical_axis]
    return h0, v0, h1, v1


def _ortho_geometry(items: list[SceneItem], horizontal_axis: int, vertical_axis: int) -> tuple[float, float, float, float]:
    rects = [_axis_item_rect(item, horizontal_axis, vertical_axis) for item in items]
    return min(rect[0] for rect in rects), min(rect[1] for rect in rects), max(rect[2] for rect in rects), max(rect[3] for rect in rects)


def _ortho_transform(bounds: tuple[float, float, float, float], viewport: tuple[float, float, float, float]):
    min_h, min_v, max_h, max_v = bounds
    x, y, w, h = viewport
    scale = min((w - 18) / max(max_h - min_h, 1), (h - 18) / max(max_v - min_v, 1))
    ox = x + (w - (max_h - min_h) * scale) / 2 - min_h * scale
    oy = y + (h - (max_v - min_v) * scale) / 2 + max_v * scale
    return lambda hv: (ox + hv[0] * scale, oy - hv[1] * scale), scale


def _draw_ortho_pil(draw: Any, panel: tuple[int, int, int, int], label: str, items: list[SceneItem], axes: tuple[int, int], dimension_label: str, theme: EngineeringTheme, vertical_label: str | None = None) -> None:
    x, y, w, h = panel
    _draw_pil_text(draw, (x + 20, y + 30), label, theme.typography.H3, theme.accent_color, bold=True)
    viewport = (x + 18, y + 52, w - 36, h - 118)
    bounds = _ortho_geometry(items, *axes)
    transform, scale = _ortho_transform(bounds, viewport)
    for item in items:
        h0, v0, h1, v1 = _axis_item_rect(item, *axes)
        p0, p1 = transform((h0, v0)), transform((h1, v1))
        color = theme.cad_dark if item.part.name == "Mounting Base" else theme.line_color
        width = 2 if item.part.name in {"Mounting Base", "Main Housing Lower", "Main Housing Upper"} else 1
        draw.rectangle((p0[0], p1[1], p1[0], p0[1]), outline=color, width=width)
        if item.part.part_type == "flange" and axes == (0, 1):
            cx, cy = transform(((h0 + h1) / 2, (v0 + v1) / 2))
            radius = min(abs(p1[0] - p0[0]), abs(p0[1] - p1[1])) * 0.36
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=theme.dimension_color, width=1)
        _draw_ortho_details_pil(draw, item, axes, transform, theme)
    center_h = (bounds[0] + bounds[2]) / 2
    center_v = (bounds[1] + bounds[3]) / 2
    p_start, p_end = transform((bounds[0], center_v)), transform((bounds[2], center_v))
    draw.line((p_start[0], p_start[1], p_end[0], p_end[1]), fill=theme.border_color, width=1)
    dim_y = y + h - 40
    draw.line((p_start[0], p_start[1], p_start[0], dim_y - 8), fill=theme.border_color, width=1)
    draw.line((p_end[0], p_end[1], p_end[0], dim_y - 8), fill=theme.border_color, width=1)
    _dimension_pil(draw, p_start[0], dim_y, p_end[0], dim_y, dimension_label, theme)
    if vertical_label:
        vx = x + w - 22
        top, bottom = transform((center_h, bounds[3])), transform((center_h, bounds[1]))
        draw.line((top[0], top[1], vx - 6, top[1]), fill=theme.border_color, width=1)
        draw.line((bottom[0], bottom[1], vx - 6, bottom[1]), fill=theme.border_color, width=1)
        _dimension_pil(draw, vx, top[1], vx, bottom[1], vertical_label, theme, vertical=True)
    _draw_pil_text(draw, (x + 20, y + h - 12), f"ORTHO / SCALE 1:{max(1, round(1 / max(scale, 0.001)))}", theme.typography.Caption, theme.body_text)


def _draw_ortho_details_svg(output: list[str], item: SceneItem, axes: tuple[int, int], transform: Any, theme: EngineeringTheme) -> None:
    h0, v0, h1, v1 = _axis_item_rect(item, *axes)
    p0, p1 = transform((h0, v0)), transform((h1, v1))
    circle = _ortho_circle(item, axes)
    if circle and item.part.part_type in {"flange", "bearing", "gear"}:
        (center_h, center_v), radius = circle
        center = transform((center_h, center_v))
        screen_radius = abs(transform((center_h + radius, center_v))[0] - center[0])
        output.append(_svg_circle(center[0], center[1], max(screen_radius, 1), "none", theme.cad_dark, 1))
        inner = item.part.inner_diameter
        if inner:
            inner_radius = screen_radius * inner / max(item.part.outer_diameter or item.part.gear_diameter or radius * 2, 1)
            output.append(_svg_circle(center[0], center[1], max(inner_radius, 1), "none", theme.dimension_color, 1))
        cross = max(min(screen_radius * 0.45, 12), 4)
        output.append(_svg_line(center[0] - cross, center[1], center[0] + cross, center[1], theme.dimension_color, 0.8, "5 4"))
        output.append(_svg_line(center[0], center[1] - cross, center[0], center[1] + cross, theme.dimension_color, 0.8, "5 4"))
        if item.part.part_type == "flange":
            bolt_circle = item.part.bolt_circle_diameter or (item.part.outer_diameter or radius * 2) * 0.72
            hole_radius = screen_radius * bolt_circle / max(item.part.outer_diameter or radius * 2, 1)
            for index in range(8):
                angle = 2 * 3.141592653589793 * index / 8
                hx = center[0] + cos(angle) * hole_radius
                hy = center[1] + sin(angle) * hole_radius
                output.append(_svg_circle(hx, hy, max(screen_radius * 0.045, 1.5), "none", theme.dimension_color, 0.8))
    elif item.part.part_type == "shaft":
        output.append(_svg_line(p0[0], (p0[1] + p1[1]) / 2, p1[0], (p0[1] + p1[1]) / 2, theme.dimension_color, 0.8, "5 4"))
        output.append(_svg_line((p0[0] + p1[0]) / 2, p0[1], (p0[0] + p1[0]) / 2, p1[1], theme.dimension_color, 0.8, "5 4"))
    elif item.part.part_type in {"housing", "bracket"}:
        inset_h = (h1 - h0) * 0.14
        inset_v = (v1 - v0) * 0.18
        inner0 = transform((h0 + inset_h, v0 + inset_v))
        inner1 = transform((h1 - inset_h, v1 - inset_v))
        output.append(_svg_line(inner0[0], inner0[1], inner1[0], inner0[1], theme.dimension_color, 0.8, "5 4"))
        output.append(_svg_line(inner1[0], inner0[1], inner1[0], inner1[1], theme.dimension_color, 0.8, "5 4"))
        output.append(_svg_line(inner1[0], inner1[1], inner0[0], inner1[1], theme.dimension_color, 0.8, "5 4"))
        output.append(_svg_line(inner0[0], inner1[1], inner0[0], inner0[1], theme.dimension_color, 0.8, "5 4"))


def _draw_ortho_svg(output: list[str], panel: tuple[int, int, int, int], label: str, items: list[SceneItem], axes: tuple[int, int], dimension_label: str, theme: EngineeringTheme, vertical_label: str | None = None) -> None:
    x, y, w, h = panel
    output.append(_svg_text(x + 20, y + 30, label, theme.typography.H3, theme.accent_color, "700"))
    viewport = (x + 18, y + 52, w - 36, h - 118)
    bounds = _ortho_geometry(items, *axes)
    transform, scale = _ortho_transform(bounds, viewport)
    for item in items:
        h0, v0, h1, v1 = _axis_item_rect(item, *axes)
        p0, p1 = transform((h0, v0)), transform((h1, v1))
        color = theme.cad_dark if item.part.name == "Mounting Base" else theme.line_color
        width = 2 if item.part.name in {"Mounting Base", "Main Housing Lower", "Main Housing Upper"} else 1
        output.append(_svg_rect(p0[0], p1[1], max(p1[0] - p0[0], 1), max(p0[1] - p1[1], 1), color, "none", width))
        if item.part.part_type == "flange" and axes == (0, 1):
            cx, cy = transform(((h0 + h1) / 2, (v0 + v1) / 2))
            radius = min(abs(p1[0] - p0[0]), abs(p0[1] - p1[1])) * 0.36
            output.append(_svg_circle(cx, cy, max(radius, 2), "none", theme.dimension_color, 1))
        _draw_ortho_details_svg(output, item, axes, transform, theme)
    center_v = (bounds[1] + bounds[3]) / 2
    p_start, p_end = transform((bounds[0], center_v)), transform((bounds[2], center_v))
    output.append(_svg_line(p_start[0], p_start[1], p_end[0], p_end[1], theme.border_color, 1))
    dim_y = y + h - 40
    output.append(_svg_line(p_start[0], p_start[1], p_start[0], dim_y - 8, theme.border_color, 1))
    output.append(_svg_line(p_end[0], p_end[1], p_end[0], dim_y - 8, theme.border_color, 1))
    output.append(_dimension_svg(p_start[0], dim_y, p_end[0], dim_y, dimension_label, theme))
    if vertical_label:
        vx = x + w - 22
        top, bottom = transform(((bounds[0] + bounds[2]) / 2, bounds[3])), transform(((bounds[0] + bounds[2]) / 2, bounds[1]))
        output.append(_svg_line(top[0], top[1], vx - 6, top[1], theme.border_color, 1))
        output.append(_svg_line(bottom[0], bottom[1], vx - 6, bottom[1], theme.border_color, 1))
        output.append(_dimension_svg(vx, top[1], vx, bottom[1], vertical_label, theme, vertical=True))
    output.append(_svg_text(x + 20, y + h - 12, f"ORTHO / SCALE 1:{max(1, round(1 / max(scale, 0.001)))}", theme.typography.Caption, theme.body_text))


def _bom_layout(spec: DrawingSpec) -> tuple[list[dict], float, int]:
    rows = generate_bom(spec)
    usable = BOM_PANEL[3] - 54
    row_height = max(10.0, min(18.0, usable / (len(rows) + 1)))
    font_size = max(7, min(10, int(row_height - 2)))
    return rows, row_height, font_size


def _draw_bom_pil(draw: Any, spec: DrawingSpec, theme: EngineeringTheme) -> None:
    x, y, w, h = BOM_PANEL
    _draw_pil_text(draw, (x + 20, y + 30), "BILL OF MATERIALS", theme.typography.H3, theme.accent_color, bold=True)
    rows, row_height, font_size = _bom_layout(spec)
    left = x + 12
    right = x + w - 12
    table_y = y + 42
    header_h = 18
    draw.rectangle((left, table_y, right, table_y + header_h), fill=theme.cad_light, outline=theme.border_color, width=1)
    columns = [left + 4, left + 38, left + 142, left + 306, left + 354]
    headers = [("ITEM", columns[0], "la"), ("PART NUMBER", columns[1], "la"), ("DESCRIPTION", columns[2], "la"), ("QTY", columns[3], "mm"), ("MATERIAL", columns[4], "la")]
    for text, cx, anchor in headers:
        _draw_pil_text(draw, (cx, table_y + header_h / 2), text, font_size, theme.title_color, anchor=anchor, bold=True)
    for index, row in enumerate(rows):
        row_y = table_y + header_h + index * row_height
        draw.line((left, row_y + row_height, right, row_y + row_height), fill=theme.border_color, width=1)
        _draw_pil_text(draw, (columns[0], row_y + row_height / 2), str(row["item"]), font_size, theme.title_color, anchor="lm")
        _draw_pil_text(draw, (columns[1], row_y + row_height / 2), _short(str(row["part_number"]), 14), font_size, theme.body_text, anchor="lm")
        _draw_pil_text(draw, (columns[2], row_y + row_height / 2), _short(str(row["description"]), 23), font_size, theme.body_text, anchor="lm")
        _draw_pil_text(draw, (columns[3], row_y + row_height / 2), str(row["qty"]), font_size, theme.title_color, anchor="mm", bold=True)
        _draw_pil_text(draw, (columns[4], row_y + row_height / 2), _short(str(row["material"]), 23), font_size, theme.body_text, anchor="lm")
    draw.line((left, table_y, left, table_y + header_h + len(rows) * row_height), fill=theme.border_color, width=1)
    draw.line((right, table_y, right, table_y + header_h + len(rows) * row_height), fill=theme.border_color, width=1)


def _draw_bom_svg(output: list[str], spec: DrawingSpec, theme: EngineeringTheme) -> None:
    x, y, w, h = BOM_PANEL
    _draw = output.append
    _draw(_svg_text(x + 20, y + 30, "BILL OF MATERIALS", theme.typography.H3, theme.accent_color, "700"))
    rows, row_height, font_size = _bom_layout(spec)
    left, right = x + 12, x + w - 12
    table_y, header_h = y + 42, 18
    _draw(_svg_rect(left, table_y, right - left, header_h, theme.border_color, theme.cad_light, 1))
    columns = [left + 4, left + 38, left + 142, left + 306, left + 354]
    headers = [("ITEM", columns[0], "start"), ("PART NUMBER", columns[1], "start"), ("DESCRIPTION", columns[2], "start"), ("QTY", columns[3], "middle"), ("MATERIAL", columns[4], "start")]
    for text, cx, anchor in headers:
        _draw(_svg_text(cx, table_y + 13, text, font_size, theme.title_color, "700", anchor))
    for index, row in enumerate(rows):
        row_y = table_y + header_h + index * row_height
        _draw(_svg_line(left, row_y + row_height, right, row_y + row_height, theme.border_color, 0.7))
        baseline = row_y + row_height * 0.72
        _draw(_svg_text(columns[0], baseline, str(row["item"]), font_size, theme.title_color))
        _draw(_svg_text(columns[1], baseline, _short(str(row["part_number"]), 14), font_size, theme.body_text))
        _draw(_svg_text(columns[2], baseline, _short(str(row["description"]), 23), font_size, theme.body_text))
        _draw(_svg_text(columns[3], baseline, str(row["qty"]), font_size, theme.title_color, "700", "middle"))
        _draw(_svg_text(columns[4], baseline, _short(str(row["material"]), 23), font_size, theme.body_text))
    _draw(_svg_line(left, table_y, left, table_y + header_h + len(rows) * row_height, theme.border_color, 0.7))
    _draw(_svg_line(right, table_y, right, table_y + header_h + len(rows) * row_height, theme.border_color, 0.7))


def _draw_feature_pil(draw: Any, image: Any, spec: DrawingSpec, theme: EngineeringTheme) -> None:
    x, y, w, h = FEATURE_PANEL
    part = _key_part(spec)
    scene = _make_scene(DrawingSpec(title=part.name, drawing_type="part", parts=[part]), (x + 10, y + 42, w - 20, 220))
    _render_pil_scene(image, scene, theme)
    _draw_pil_text(draw, (x + 20, y + 30), "KEY WORKPIECE", theme.typography.H3, theme.accent_color, bold=True)
    metadata = _metadata(part)
    start_y = y + 270
    for index, (key, value) in enumerate(metadata):
        col = 0 if index < 4 else 1
        row = index if index < 4 else index - 4
        xx = x + 20 + col * 250
        yy = start_y + row * 25
        _draw_pil_text(draw, (xx, yy), key, theme.typography.Caption, theme.dimension_color, bold=True)
        _draw_pil_text(draw, (xx, yy + 14), _short(value, 27), theme.typography.Body if key == "PART" else theme.typography.Caption, theme.title_color if key == "PART" else theme.body_text)


def _draw_feature_svg(output: list[str], spec: DrawingSpec, theme: EngineeringTheme) -> None:
    x, y, w, h = FEATURE_PANEL
    part = _key_part(spec)
    scene = _make_scene(DrawingSpec(title=part.name, drawing_type="part", parts=[part]), (x + 10, y + 42, w - 20, 220))
    output.append(_render_svg_scene(scene, theme))
    output.append(_svg_text(x + 20, y + 30, "KEY WORKPIECE", theme.typography.H3, theme.accent_color, "700"))
    for index, (key, value) in enumerate(_metadata(part)):
        col = 0 if index < 4 else 1
        row = index if index < 4 else index - 4
        xx = x + 20 + col * 250
        yy = y + 270 + row * 25
        output.append(_svg_text(xx, yy, key, theme.typography.Caption, theme.dimension_color, "700"))
        output.append(_svg_text(xx, yy + 14, _short(value, 27), theme.typography.Body if key == "PART" else theme.typography.Caption, theme.title_color if key == "PART" else theme.body_text))


def _exploded_slots(spec: DrawingSpec) -> list[IsoScene]:
    """Place major assembly components in deterministic axial slots.

    A single global scale makes the mounting base dominate the small exploded
    panel. Major components therefore get their own bounded slot while
    retaining the same CAD-derived part geometry and a uniform left-to-right
    assembly order. Variant instances are deliberately retained so both
    shafts, both bearings and both gears remain visible and traceable to BOM
    item numbers.
    """

    items = _assembly_items(spec, exploded=True, unique=False)
    if spec.drawing_type == "assembly":
        by_instance = {item.instance_id: item for item in items}
        preferred_order = (
            "output-flange",
            "output-bearing",
            "output-shaft",
            "large-gear",
            "housing-lower",
            "housing-upper",
            "small-gear",
            "input-shaft",
            "input-bearing",
            "motor-adapter",
            "servo-motor",
        )
        items = [by_instance[instance_id] for instance_id in preferred_order if instance_id in by_instance]
    x, y, w, h = EXPLODED_PANEL
    count = max(len(items), 1)
    slot_width = (w - 48) / count
    target_top = y + 52
    target_bottom = y + h - 12
    target_height = target_bottom - target_top
    scenes: list[IsoScene] = []
    for index, item in enumerate(items):
        item.position = (0.0, 0.0, 0.0)
        raw_min_x, raw_min_y, raw_max_x, raw_max_y = _raw_bounds([item])
        raw_width = max(raw_max_x - raw_min_x, 1.0)
        raw_height = max(raw_max_y - raw_min_y, 1.0)
        scale = min(slot_width * 0.72 / raw_width, target_height * 0.60 / raw_height)
        center_x = x + 24 + slot_width * (index + 0.5)
        center_y = target_top + target_height * 0.64
        raw_center = ((raw_min_x + raw_max_x) / 2, (raw_min_y + raw_max_y) / 2)
        origin = (center_x - raw_center[0] * scale, center_y - raw_center[1] * scale)
        scene = IsoScene([item], origin, scale, (raw_min_x, raw_min_y, raw_max_x, raw_max_y), (x + 24 + index * slot_width, target_top, slot_width, target_height))
        points = [_scene_item_point(scene, item, px, py, pz) for px in (0, item.dimensions[0]) for py in (0, item.dimensions[1]) for pz in (0, item.dimensions[2])]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        item.bbox = (min(xs), min(ys), max(xs), max(ys))
        scenes.append(scene)
    return scenes


def _draw_exploded_pil(draw: Any, image: Any, spec: DrawingSpec, theme: EngineeringTheme) -> None:
    x, y, w, h = EXPLODED_PANEL
    _draw_pil_text(draw, (x + 20, y + 30), "EXPLODED VIEW", theme.typography.H3, theme.accent_color, bold=True)
    scenes = _exploded_slots(spec)
    rail_y = y + h - 42
    draw.line((x + 28, rail_y, x + w - 28, rail_y), fill=theme.border_color, width=1)
    _draw_pil_text(draw, (x + w - 28, rail_y + 17), "AXIAL ASSEMBLY", theme.typography.Caption, theme.dimension_color, anchor="ra")
    for scene in scenes:
        _render_pil_scene(image, scene, theme)
        item = scene.items[0]
        x0, y0, x1, _ = item.bbox
        cx = (x0 + x1) / 2
        label_y = max(y + 50, y0 - 17)
        draw.ellipse((cx - 9, label_y - 9, cx + 9, label_y + 9), fill=theme.background, outline=theme.accent_color, width=1)
        _draw_pil_text(draw, (cx, label_y), str(item.number), theme.typography.Caption, theme.accent_color, anchor="mm", bold=True)


def _draw_exploded_svg(output: list[str], spec: DrawingSpec, theme: EngineeringTheme) -> None:
    x, y, w, h = EXPLODED_PANEL
    output.append(_svg_text(x + 20, y + 30, "EXPLODED VIEW", theme.typography.H3, theme.accent_color, "700"))
    rail_y = y + h - 42
    output.append(_svg_line(x + 28, rail_y, x + w - 28, rail_y, theme.border_color, 1.0))
    output.append(_svg_text(x + w - 28, rail_y + 17, "AXIAL ASSEMBLY", theme.typography.Caption, theme.dimension_color, "500", "end"))
    for scene in _exploded_slots(spec):
        output.append(_render_svg_scene(scene, theme))
        item = scene.items[0]
        x0, y0, x1, _ = item.bbox
        cx = (x0 + x1) / 2
        label_y = max(y + 50, y0 - 17)
        output.append(_svg_circle(cx, label_y, 9, theme.background, theme.accent_color, 1))
        output.append(_svg_text(cx, label_y + 3, str(item.number), theme.typography.Caption, theme.accent_color, "700", "middle"))


def _header_svg(spec: DrawingSpec, theme: EngineeringTheme) -> list[str]:
    return [
        _svg_text(32, 68, spec.title, theme.typography.H1, theme.title_color, "700"),
        _svg_text(34, 103, "PART & ASSEMBLY GENERATOR", theme.typography.H2, theme.title_color, "600"),
        _svg_text(36, 128, "DESIGN · MODEL · AUTOMATE", theme.typography.H3, theme.dimension_color, "500", letter_spacing=2.2),
        _svg_text(1518, 47, "REVISION CONTROLLED", theme.typography.Caption, theme.body_text, "600", "end"),
        _svg_text(1518, 68, f"REV {spec.revision:02d}  ·  {spec.units.upper()}", theme.typography.Caption, theme.body_text, "400", "end"),
        _svg_line(1548, 26, 1548, 96, theme.accent_color, 5),
    ]


def _header_pil(draw: Any, spec: DrawingSpec, theme: EngineeringTheme) -> None:
    _draw_pil_text(draw, (32, 20), spec.title, theme.typography.H1, theme.title_color, bold=True)
    _draw_pil_text(draw, (34, 82), "PART & ASSEMBLY GENERATOR", theme.typography.H2, theme.title_color, bold=True)
    _draw_pil_text(draw, (36, 110), "DESIGN · MODEL · AUTOMATE", theme.typography.H3, theme.dimension_color)
    _draw_pil_text(draw, (1518, 38), "REVISION CONTROLLED", theme.typography.Caption, theme.body_text, anchor="ra", bold=True)
    _draw_pil_text(draw, (1518, 59), f"REV {spec.revision:02d}  ·  {spec.units.upper()}", theme.typography.Caption, theme.body_text, anchor="ra")
    draw.line((1548, 26, 1548, 96), fill=theme.accent_color, width=5)


def _validate_svg_markup(markup: str) -> None:
    root = ET.fromstring(markup)
    for element in root.iter():
        for attribute in ("width", "height"):
            value = element.attrib.get(attribute)
            if value is None or value.endswith("%"):
                continue
            try:
                if float(value) < 0:
                    raise ValueError(f"negative SVG {attribute}")
            except ValueError as exc:
                if "negative SVG" in str(exc):
                    raise
        font_size = element.attrib.get("font-size")
        if font_size and font_size.endswith("px") and float(font_size[:-2]) <= 0:
            raise ValueError("SVG font-size must be positive")


def sheet_layout_report(spec: DrawingSpec, geometry: GeometryResult | None = None) -> dict[str, Any]:
    rows, row_height, font_size = _bom_layout(spec)
    hero = (MAIN_PANEL[0] + 34, MAIN_PANEL[1] + 54, MAIN_PANEL[2] - 68, MAIN_PANEL[3] - 88)
    exploded_scenes = _exploded_slots(spec)
    slot_width = (EXPLODED_PANEL[2] - 48) / max(len(exploded_scenes), 1)
    exploded_bounds = sorted((scene.items[0].bbox for scene in exploded_scenes), key=lambda bbox: bbox[0])
    exploded_gap = min(
        (right[0] - left[2] for left, right in zip(exploded_bounds, exploded_bounds[1:])),
        default=slot_width,
    )
    return {
        "canvas": {"width": SHEET_WIDTH, "height": SHEET_HEIGHT},
        "panels": panel_bboxes(),
        "hero_bbox": hero,
        "hero_panel_occupancy": round(hero[2] * hero[3] / (MAIN_PANEL[2] * MAIN_PANEL[3]), 3),
        "bom_row_height": round(row_height, 2),
        "bom_font_size": font_size,
        "bom_rows": len(rows),
        "exploded_component_count": len(exploded_scenes),
        "exploded_slot_width": round(slot_width, 2),
        "exploded_min_gap": round(exploded_gap, 2),
        "exploded_bounds": exploded_bounds,
        "fonts": DEFAULT_THEME.typography.as_dict(),
        "dimension_source": _metrics(spec, geometry).source,
    }


def validate_sheet_layout(spec: DrawingSpec, geometry: GeometryResult | None = None) -> dict[str, Any]:
    """Validate the fixed grid before either sheet renderer writes output."""

    report = sheet_layout_report(spec, geometry)
    for name, (x, y, width, height) in report["panels"].items():
        if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > SHEET_WIDTH or y + height > SHEET_HEIGHT:
            raise ValueError(f"panel outside canvas: {name}")
    if report["hero_panel_occupancy"] < 0.45:
        raise ValueError("hero render is too small for the primary panel")
    if report["bom_row_height"] <= report["bom_font_size"]:
        raise ValueError("BOM rows cannot contain the selected font")
    if report["exploded_slot_width"] < 20:
        raise ValueError("exploded view slots are too narrow")
    if report["exploded_min_gap"] <= 0:
        raise ValueError("exploded view parts overlap")
    ex_x, ex_y, ex_w, ex_h = EXPLODED_PANEL
    for x0, y0, x1, y1 in report["exploded_bounds"]:
        if x0 < ex_x or x1 > ex_x + ex_w or y0 < ex_y or y1 > ex_y + ex_h:
            raise ValueError("exploded view part is outside its panel")
    if any(size <= 0 for size in report["fonts"].values()):
        raise ValueError("all sheet typography sizes must be positive")
    return report


def render_sheet_svg(spec: DrawingSpec, theme: EngineeringTheme = DEFAULT_THEME, geometry: GeometryResult | None = None) -> str:
    """Render the 1600 x 1000 vector engineering showcase board."""

    validate_sheet_layout(spec, geometry)
    main_scene = _make_scene(spec, MAIN_PANEL)
    key_part = _key_part(spec)
    metrics = _metrics(spec, geometry)
    items = _assembly_items(spec)
    output: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{SHEET_WIDTH}" height="{SHEET_HEIGHT}" viewBox="0 0 {SHEET_WIDTH} {SHEET_HEIGHT}">',
        _svg_defs(theme),
        _svg_rect(0, 0, SHEET_WIDTH, SHEET_HEIGHT, fill=theme.background),
        _svg_rect(14, 14, SHEET_WIDTH - 28, SHEET_HEIGHT - 28, theme.border_color, "none", 1.2),
        *_header_svg(spec, theme),
    ]
    for panel in PANELS:
        output.append(_svg_rect(panel.x, panel.y, panel.width, panel.height, theme.border_color, "none", 1.0))
    output.extend(
        [
            _svg_text(MAIN_PANEL[0] + 20, MAIN_PANEL[1] + 31, "PRIMARY ASSEMBLY / ISOMETRIC RENDER", theme.typography.H3, theme.accent_color, "700"),
            _svg_text(FEATURE_PANEL[0] + 20, FEATURE_PANEL[1] + 31, "KEY WORKPIECE", theme.typography.H3, theme.accent_color, "700"),
            _render_svg_scene(main_scene, theme),
            _draw_svg_callouts(_callouts(spec, main_scene), theme),
            _svg_text(MAIN_PANEL[0] + 22, MAIN_PANEL[1] + MAIN_PANEL[3] - 20, "CAD MODEL / SAME SOURCE AS STEP · STL · DXF", theme.typography.Caption, theme.body_text, "600"),
        ]
    )
    # Keep the dimension source visible without inventing manufacturing data.
    output.extend(
        [
            _svg_text(MAIN_PANEL[0] + MAIN_PANEL[2] - 20, MAIN_PANEL[1] + MAIN_PANEL[3] - 20, metrics.source.upper(), theme.typography.Caption, theme.dimension_color, "500", "end"),
        ]
    )
    output.append(_render_svg_scene(_make_scene(DrawingSpec(title=key_part.name, drawing_type="part", parts=[key_part]), (FEATURE_PANEL[0] + 10, FEATURE_PANEL[1] + 42, FEATURE_PANEL[2] - 20, 220)), theme))
    for index, (key, value) in enumerate(_metadata(key_part)):
        col = 0 if index < 4 else 1
        row = index if index < 4 else index - 4
        xx = FEATURE_PANEL[0] + 20 + col * 250
        yy = FEATURE_PANEL[1] + 270 + row * 25
        output.append(_svg_text(xx, yy, key, theme.typography.Caption, theme.dimension_color, "700"))
        output.append(_svg_text(xx, yy + 14, _short(value, 27), theme.typography.Body if key == "PART" else theme.typography.Caption, theme.title_color if key == "PART" else theme.body_text))
    _draw_ortho_svg(output, TOP_PANEL, "TOP VIEW", items, (0, 1), f"L {_fmt(metrics.length)} mm", theme, f"W {_fmt(metrics.width)}")
    _draw_ortho_svg(output, FRONT_PANEL, "FRONT VIEW", items, (0, 2), f"L {_fmt(metrics.length)}", theme, f"H {_fmt(metrics.height)}")
    _draw_ortho_svg(output, SIDE_PANEL, "SIDE VIEW", items, (1, 2), f"W {_fmt(metrics.width)}", theme, f"H {_fmt(metrics.height)}")
    output.append(_svg_text(TOP_PANEL[0] + TOP_PANEL[2] - 20, TOP_PANEL[1] + 30, f"SHAFT Ø{_fmt(metrics.shaft_diameter)}  ·  MOUNT {_fmt(metrics.mounting_length)} × {_fmt(metrics.mounting_width)}", theme.typography.Caption, theme.dimension_color, "600", "end"))
    _draw_exploded_svg(output, spec, theme)
    _draw_bom_svg(output, spec, theme)
    output.extend(
        [
            _svg_text(34, 988, "FACTORY AGENT  /  AI-ASSISTED CAD FOR SMARTER MANUFACTURING", theme.typography.Caption, theme.body_text),
            _svg_text(1518, 988, "PX-2100  ·  DETERMINISTIC CAD DATA", theme.typography.Caption, theme.body_text, "400", "end"),
            "</svg>",
        ]
    )
    markup = "".join(output)
    _validate_svg_markup(markup)
    return markup


def render_sheet_png(spec: DrawingSpec, path: str | Path, theme: EngineeringTheme = DEFAULT_THEME, geometry: GeometryResult | None = None) -> bool:
    """Render a supersampled-looking raster companion with Pillow."""

    validate_sheet_layout(spec, geometry)
    try:
        from PIL import Image, ImageDraw
    except Exception:
        Path(path).write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\x0dIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return False

    image = Image.new("RGB", (SHEET_WIDTH, SHEET_HEIGHT), theme.background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((14, 14, SHEET_WIDTH - 14, SHEET_HEIGHT - 14), outline=theme.border_color, width=2)
    _header_pil(draw, spec, theme)
    for panel in PANELS:
        _draw_pil_panel(draw, panel.bbox, theme)

    main_scene = _make_scene(spec, MAIN_PANEL)
    _draw_pil_text(draw, (MAIN_PANEL[0] + 20, MAIN_PANEL[1] + 31), "PRIMARY ASSEMBLY / ISOMETRIC RENDER", theme.typography.H3, theme.accent_color, bold=True)
    _draw_pil_text(draw, (FEATURE_PANEL[0] + 20, FEATURE_PANEL[1] + 31), "KEY WORKPIECE", theme.typography.H3, theme.accent_color, bold=True)
    _render_pil_scene(image, main_scene, theme)
    draw = ImageDraw.Draw(image)
    _draw_pil_callouts(draw, _callouts(spec, main_scene), theme)
    _draw_pil_text(draw, (MAIN_PANEL[0] + 22, MAIN_PANEL[1] + MAIN_PANEL[3] - 20), "CAD MODEL / SAME SOURCE AS STEP · STL · DXF", theme.typography.Caption, theme.body_text, bold=True)
    _draw_pil_text(draw, (MAIN_PANEL[0] + MAIN_PANEL[2] - 20, MAIN_PANEL[1] + MAIN_PANEL[3] - 20), _metrics(spec, geometry).source.upper(), theme.typography.Caption, theme.dimension_color, anchor="ra")

    _draw_feature_pil(draw, image, spec, theme)
    draw = ImageDraw.Draw(image)
    items = _assembly_items(spec)
    metrics = _metrics(spec, geometry)
    _draw_ortho_pil(draw, TOP_PANEL, "TOP VIEW", items, (0, 1), f"L {_fmt(metrics.length)} mm", theme, f"W {_fmt(metrics.width)}")
    _draw_ortho_pil(draw, FRONT_PANEL, "FRONT VIEW", items, (0, 2), f"L {_fmt(metrics.length)}", theme, f"H {_fmt(metrics.height)}")
    _draw_ortho_pil(draw, SIDE_PANEL, "SIDE VIEW", items, (1, 2), f"W {_fmt(metrics.width)}", theme, f"H {_fmt(metrics.height)}")
    _draw_pil_text(draw, (TOP_PANEL[0] + TOP_PANEL[2] - 20, TOP_PANEL[1] + 30), f"SHAFT Ø{_fmt(metrics.shaft_diameter)}  ·  MOUNT {_fmt(metrics.mounting_length)} × {_fmt(metrics.mounting_width)}", theme.typography.Caption, theme.dimension_color, anchor="ra", bold=True)
    _draw_exploded_pil(draw, image, spec, theme)
    draw = ImageDraw.Draw(image)
    _draw_bom_pil(draw, spec, theme)
    _draw_pil_text(draw, (34, 988), "FACTORY AGENT  /  AI-ASSISTED CAD FOR SMARTER MANUFACTURING", theme.typography.Caption, theme.body_text)
    _draw_pil_text(draw, (1518, 988), "PX-2100  ·  DETERMINISTIC CAD DATA", theme.typography.Caption, theme.body_text, anchor="ra")
    image.save(path, format="PNG", optimize=True)
    return True
