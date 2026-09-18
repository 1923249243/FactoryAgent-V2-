from __future__ import annotations

from pathlib import Path
from typing import Iterable

from app.drawing.cad.engine import GeometryResult
from app.drawing.cad.parts.common import variant_part
from app.drawing.drawing.svg_renderer import render_drawing_svg
from app.drawing.schemas import DrawingSpec, PartSpec
from app.drawing.sheet.renderer import render_sheet_png, render_sheet_svg


def _write_fallback_step(path: Path, spec: DrawingSpec) -> None:
    """Write a standards-framed fallback when CadQuery is not installed.

    The optional CadQuery extra replaces this manifest with a full B-rep STEP
    file. Keeping a syntactically framed artifact in the base install means a
    demo can still be inspected and upgraded without changing the API.
    """

    title = spec.title.replace("'", "")
    body = [
        "ISO-10303-21;",
        "HEADER;",
        "FILE_DESCRIPTION(('FACTORYAGENT PARAMETRIC CAD FALLBACK'),'2;1');",
        "FILE_NAME('model.step','2026-01-01T00:00:00',('FactoryAgent'),('FactoryAgent'),'FactoryAgent Drawing Agent','FactoryAgent','');",
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN_CC2'));",
        "ENDSEC;",
        "DATA;",
        f"#1=PRODUCT('{title}','{title}','DrawingSpec fallback; install requirements-drawing.txt for B-rep export',());",
        "#2=APPLICATION_CONTEXT('mechanical design');",
        "#3=PRODUCT_CONTEXT('',#2,'mechanical');",
        "ENDSEC;",
        "END-ISO-10303-21;",
    ]
    path.write_text("\n".join(body) + "\n", encoding="ascii", errors="ignore")


def export_step(geometry: GeometryResult, path: str | Path) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if geometry.native is not None and geometry.backend == "cadquery":
        try:
            from cadquery import exporters  # type: ignore

            exporters.export(geometry.native, str(output), exportType="STEP")
            return "cadquery"
        except Exception:
            # Keep the endpoint usable if a platform-specific OCC exporter is
            # present but fails for one shape.
            pass
    _write_fallback_step(output, geometry.spec)
    return "fallback"


def _facet(normal: tuple[float, float, float], points: Iterable[tuple[float, float, float]]) -> str:
    vertices = "\n".join(f"      vertex {x:.6f} {y:.6f} {z:.6f}" for x, y, z in points)
    return f"  facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}\n    outer loop\n{vertices}\n    endloop\n  endfacet\n"


def _box_facets(length: float, width: float, height: float) -> list[str]:
    p000 = (0, 0, 0)
    p100 = (length, 0, 0)
    p110 = (length, width, 0)
    p010 = (0, width, 0)
    p001 = (0, 0, height)
    p101 = (length, 0, height)
    p111 = (length, width, height)
    p011 = (0, width, height)
    return [
        _facet((0, 0, -1), (p000, p110, p100)),
        _facet((0, 0, -1), (p000, p010, p110)),
        _facet((0, 0, 1), (p001, p101, p111)),
        _facet((0, 0, 1), (p001, p111, p011)),
        _facet((0, -1, 0), (p000, p100, p101)),
        _facet((0, -1, 0), (p000, p101, p001)),
        _facet((1, 0, 0), (p100, p110, p111)),
        _facet((1, 0, 0), (p100, p111, p101)),
        _facet((0, 1, 0), (p010, p011, p111)),
        _facet((0, 1, 0), (p010, p111, p110)),
        _facet((-1, 0, 0), (p000, p001, p011)),
        _facet((-1, 0, 0), (p000, p011, p010)),
    ]


def _fallback_stl(spec: DrawingSpec) -> str:
    parts = spec.parts if spec.drawing_type == "part" else [spec.parts[0]]
    facets: list[str] = []
    cursor_x = 0.0
    for part in parts:
        length = part.outer_diameter or part.length or 100.0
        width = part.width or length
        height = part.height or 20.0
        local = _box_facets(length, width, height)
        if cursor_x:
            shifted = []
            for facet in local:
                shifted.append(facet.replace("vertex 0.000000", f"vertex {cursor_x:.6f}", 1))
            facets.extend(shifted)
        else:
            facets.extend(local)
        cursor_x += length + 10
    return "solid factoryagent\n" + "".join(f"{facet}" for facet in facets) + "endsolid factoryagent\n"


def export_stl(geometry: GeometryResult, path: str | Path) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if geometry.native is not None and geometry.backend == "cadquery":
        try:
            from cadquery import exporters  # type: ignore

            exporters.export(
                geometry.native,
                str(output),
                exportType="STL",
                tolerance=0.01,
                angularTolerance=0.1,
            )
            return "cadquery"
        except Exception:
            pass
    output.write_text(_fallback_stl(geometry.spec), encoding="ascii")
    return "fallback"


def _add_part_to_dxf(msp, part: PartSpec, x_offset: float = 0.0, y_offset: float = 0.0) -> None:
    if part.part_type == "flange":
        diameter = part.outer_diameter or part.length or 120
        center = (x_offset + diameter / 2, y_offset + diameter / 2)
        msp.add_circle(center, diameter / 2)
        if part.inner_diameter:
            msp.add_circle(center, part.inner_diameter / 2)
        for hole in part.holes:
            msp.add_circle((x_offset + hole.x, y_offset + hole.y), hole.diameter / 2)
        return
    length = part.length or 160
    width = part.width or 100
    msp.add_lwpolyline(
        [
            (x_offset, y_offset),
            (x_offset + length, y_offset),
            (x_offset + length, y_offset + width),
            (x_offset, y_offset + width),
        ],
        close=True,
    )
    for hole in part.holes:
        msp.add_circle((x_offset + hole.x, y_offset + hole.y), hole.diameter / 2)


def _write_fallback_dxf(path: Path, spec: DrawingSpec) -> None:
    # ASCII R12 entities are intentionally simple and are readable by common
    # CAD viewers even when ezdxf is not installed.
    part = spec.parts[0]
    length = part.length or 160
    width = part.width or 100
    lines = [
        "0", "SECTION", "2", "HEADER", "0", "ENDSEC",
        "0", "SECTION", "2", "ENTITIES",
        "0", "LWPOLYLINE", "8", "0", "90", "4", "70", "1",
    ]
    for x, y in ((0, 0), (length, 0), (length, width), (0, width)):
        lines.extend(["10", f"{x:g}", "20", f"{y:g}"])
    lines.extend(["0", "ENDSEC", "0", "EOF", ""])
    path.write_text("\n".join(lines), encoding="ascii")


def export_dxf(geometry: GeometryResult, path: str | Path) -> str:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        import ezdxf  # type: ignore
    except Exception:
        _write_fallback_dxf(output, geometry.spec)
        return "fallback"

    try:
        doc = ezdxf.new("R2010")
        msp = doc.modelspace()
        if geometry.spec.drawing_type == "assembly" and geometry.spec.assembly:
            by_id = {part.part_id: part for part in geometry.spec.parts}
            for index, component in enumerate(geometry.spec.assembly.components):
                part = variant_part(by_id[component.part_id], component.variant)
                _add_part_to_dxf(msp, part, component.position[0] + index * 12, component.position[1])
                msp.add_text(str(index + 1), dxfattribs={"height": 6}).set_placement((component.position[0] + index * 12, component.position[1]))
        else:
            _add_part_to_dxf(msp, geometry.spec.parts[0])
        doc.saveas(output)
        return "ezdxf"
    except Exception:
        _write_fallback_dxf(output, geometry.spec)
        return "fallback"


def export_svg(spec: DrawingSpec, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_drawing_svg(spec), encoding="utf-8")


def export_sheet(
    spec: DrawingSpec,
    svg_path: str | Path,
    png_path: str | Path,
    geometry: GeometryResult | None = None,
) -> dict[str, str | bool]:
    svg_output = Path(svg_path)
    png_output = Path(png_path)
    svg_output.parent.mkdir(parents=True, exist_ok=True)
    svg_output.write_text(render_sheet_svg(spec, geometry=geometry), encoding="utf-8")
    png_available = render_sheet_png(spec, png_output, geometry=geometry)
    return {"svg": str(svg_output), "png": str(png_output), "png_renderer": png_available}
