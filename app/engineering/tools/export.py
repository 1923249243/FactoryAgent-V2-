from __future__ import annotations

import json
import struct
import zlib
from html import escape
from pathlib import Path
from typing import Any

from app.engineering.adapters.freecad import write_assembly_recipe
from app.engineering.models.object import EngineeringObjectSpec
from app.engineering.templates.base import EngineeringTemplate


def _fallback_step(path: Path, spec: EngineeringObjectSpec) -> None:
    title = spec.name.replace("'", "")
    path.write_text(
        "\n".join(
            [
                "ISO-10303-21;",
                "HEADER;",
                "FILE_DESCRIPTION(('FACTORYAGENT ENGINEERING FALLBACK'),'2;1');",
                "FILE_NAME('model.step','2026-01-01T00:00:00',('FactoryAgent'),('FactoryAgent'),'FactoryAgent Engineering Agent','FactoryAgent','');",
                "FILE_SCHEMA(('AUTOMOTIVE_DESIGN_CC2'));",
                "ENDSEC;",
                "DATA;",
                f"#1=PRODUCT('{title}','{title}','Engineering template fallback; install requirements-drawing.txt for B-rep export',());",
                "#2=APPLICATION_CONTEXT('mechanical design');",
                "#3=PRODUCT_CONTEXT('',#2,'mechanical');",
                "ENDSEC;",
                "END-ISO-10303-21;",
                "",
            ]
        ),
        encoding="ascii",
        errors="ignore",
    )


def _fallback_stl(path: Path, spec: EngineeringObjectSpec) -> None:
    path.write_text(
        "\n".join(
            [
                "solid factoryagent_engineering",
                "  facet normal 0 0 1",
                "    outer loop",
                "      vertex 0 0 0",
                "      vertex 1 0 0",
                "      vertex 0 1 0",
                "    endloop",
                "  endfacet",
                "endsolid factoryagent_engineering",
                "",
            ]
        ),
        encoding="ascii",
    )


def _dimensions(geometry: dict[str, Any]) -> tuple[float, float, float]:
    native = geometry.get("native")
    if native is not None:
        try:
            box = native.BoundingBox()
            return float(box.xlen), float(box.ylen), float(box.zlen)
        except Exception:
            try:
                box = native.val().BoundingBox()
                return float(box.xlen), float(box.ylen), float(box.zlen)
            except Exception:
                pass
    diameter = geometry.get("outer_diameter") or geometry.get("diameter")
    length = geometry.get("length") or diameter or 180.0
    width = geometry.get("width") or diameter or 120.0
    height = geometry.get("height") or geometry.get("thickness") or 12.0
    return float(length), float(width), float(height)


def _drawing_svg(spec: EngineeringObjectSpec, geometry: dict[str, Any]) -> str:
    label = escape(spec.name)
    template = escape(spec.template)
    shape = escape(str(geometry.get("shape", "engineering_object")))
    length, width, height = _dimensions(geometry)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000">
  <rect width="1600" height="1000" fill="#F3F6F9"/>
  <rect x="28" y="28" width="1544" height="944" fill="none" stroke="#B8C7D4" stroke-width="2"/>
  <text x="70" y="86" fill="#102D49" font-size="46" font-family="Arial" font-weight="700">ENGINEERING OBJECT</text>
  <text x="70" y="126" fill="#586A79" font-size="24" font-family="Arial">{label} · {template}</text>
  <text x="70" y="166" fill="#60798E" font-size="15" font-family="Arial" letter-spacing="3">PARAMETRIC CAD · DETERMINISTIC PIPELINE</text>
  <rect x="80" y="230" width="900" height="440" rx="16" fill="#E8EDF1" stroke="#B8C7D4" stroke-width="2"/>
  <rect x="170" y="320" width="720" height="220" rx="12" fill="#AEB8BF" stroke="#454D55" stroke-width="5"/>
  <circle cx="530" cy="430" r="74" fill="#D7DDE2" stroke="#454D55" stroke-width="5"/>
  <circle cx="530" cy="430" r="28" fill="#F3F6F9" stroke="#60798E" stroke-width="3"/>
  <text x="530" y="610" text-anchor="middle" fill="#102D49" font-size="32" font-family="Arial" font-weight="700">{shape}</text>
  <text x="1040" y="250" fill="#102D49" font-size="25" font-family="Arial" font-weight="700">PARAMETERS</text>
  <line x1="1040" y1="270" x2="1510" y2="270" stroke="#B8C7D4"/>
  <text x="1040" y="320" fill="#586A79" font-size="21" font-family="Arial">LENGTH</text><text x="1460" y="320" text-anchor="end" fill="#102D49" font-size="21" font-family="Arial">{length:g} mm</text>
  <text x="1040" y="365" fill="#586A79" font-size="21" font-family="Arial">WIDTH</text><text x="1460" y="365" text-anchor="end" fill="#102D49" font-size="21" font-family="Arial">{width:g} mm</text>
  <text x="1040" y="410" fill="#586A79" font-size="21" font-family="Arial">HEIGHT</text><text x="1460" y="410" text-anchor="end" fill="#102D49" font-size="21" font-family="Arial">{height:g} mm</text>
  <text x="70" y="750" fill="#102D49" font-size="23" font-family="Arial" font-weight="700">ORTHOGRAPHIC VIEWS</text>
  <rect x="80" y="775" width="280" height="140" fill="none" stroke="#B8C7D4"/>
  <rect x="410" y="775" width="280" height="140" fill="none" stroke="#B8C7D4"/>
  <rect x="740" y="775" width="280" height="140" fill="none" stroke="#B8C7D4"/>
  <path d="M125 850h190 M220 805v90 M455 850h190 M540 815v70 M785 850h190 M880 825v50" stroke="#454D55" stroke-width="3"/>
  <text x="220" y="945" text-anchor="middle" fill="#60798E" font-size="16" font-family="Arial">TOP VIEW</text>
  <text x="550" y="945" text-anchor="middle" fill="#60798E" font-size="16" font-family="Arial">FRONT VIEW</text>
  <text x="880" y="945" text-anchor="middle" fill="#60798E" font-size="16" font-family="Arial">SIDE VIEW</text>
  <text x="1040" y="750" fill="#102D49" font-size="23" font-family="Arial" font-weight="700">OUTPUTS</text>
  <text x="1040" y="795" fill="#586A79" font-size="19" font-family="Arial">STEP / STL / SVG / DXF / BOM</text>
  <text x="1040" y="840" fill="#586A79" font-size="19" font-family="Arial">Assembly recipe and solver handoff</text>
  <text x="70" y="950" fill="#60798E" font-size="17" font-family="Arial">FactoryAgent Engineering Agent · dimensions are template/CAD derived</text>
</svg>
'''


def _write_png(path: Path, spec: EngineeringObjectSpec, geometry: dict[str, Any]) -> None:
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception:
        # Keep the artifact contract intact in the minimal installation.  It
        # is a valid 1600x1000 PNG background, not a claimed raster render;
        # installing Pillow enables the full engineering sheet renderer below.
        width, height = 1600, 1000
        row = b"\x00" + bytes((243, 246, 249)) * width
        compressed = zlib.compress(row * height, 9)

        def chunk(kind: bytes, data: bytes) -> bytes:
            return (
                struct.pack(">I", len(data))
                + kind
                + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
            )

        path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", compressed)
            + chunk(b"IEND", b"")
        )
        return
    image = Image.new("RGB", (1600, 1000), "#F3F6F9")
    draw = ImageDraw.Draw(image)
    try:
        h1 = ImageFont.truetype("arial.ttf", 46)
        h2 = ImageFont.truetype("arial.ttf", 25)
        body = ImageFont.truetype("arial.ttf", 20)
    except OSError:
        h1 = h2 = body = ImageFont.load_default()
    length, width, height = _dimensions(geometry)
    draw.rectangle((28, 28, 1572, 972), outline="#B8C7D4", width=2)
    draw.text((70, 58), "ENGINEERING OBJECT", fill="#102D49", font=h1)
    draw.text((70, 116), f"{spec.name} · {spec.template}", fill="#586A79", font=h2)
    draw.text((70, 230), "PARAMETRIC CAD / DETERMINISTIC PIPELINE", fill="#60798E", font=body)
    draw.rounded_rectangle((80, 270, 980, 670), radius=16, fill="#E8EDF1", outline="#B8C7D4", width=2)
    draw.rounded_rectangle((170, 360, 890, 580), radius=12, fill="#AEB8BF", outline="#454D55", width=5)
    draw.ellipse((456, 356, 604, 504), fill="#D7DDE2", outline="#454D55", width=5)
    draw.ellipse((502, 402, 558, 458), fill="#F3F6F9", outline="#60798E", width=3)
    draw.text((1040, 250), "PARAMETERS", fill="#102D49", font=h2)
    for index, (label, value) in enumerate(
        (("LENGTH", length), ("WIDTH", width), ("HEIGHT", height))
    ):
        y = 315 + index * 48
        draw.text((1040, y), label, fill="#586A79", font=body)
        draw.text((1460, y), f"{value:g} mm", fill="#102D49", font=body, anchor="ra")
    draw.text((70, 750), "ORTHOGRAPHIC VIEWS", fill="#102D49", font=h2)
    for x, label in ((80, "TOP VIEW"), (410, "FRONT VIEW"), (740, "SIDE VIEW")):
        draw.rectangle((x, 790, x + 280, 920), outline="#B8C7D4", width=2)
        draw.line((x + 45, 855, x + 235, 855), fill="#454D55", width=3)
        draw.line((x + 140, 810, x + 140, 900), fill="#454D55", width=3)
        draw.text((x + 140, 940), label, fill="#60798E", font=body, anchor="ma")
    draw.text((1040, 750), "OUTPUTS", fill="#102D49", font=h2)
    draw.text((1040, 800), "STEP / STL / SVG / DXF / BOM", fill="#586A79", font=body)
    image.save(path, format="PNG")


def _write_dxf(path: Path, geometry: dict[str, Any]) -> None:
    length, width, height = _dimensions(geometry)
    try:
        import ezdxf  # type: ignore

        document = ezdxf.new("R2010")
        modelspace = document.modelspace()
        modelspace.add_lwpolyline(
            [(0, 0), (length, 0), (length, width), (0, width), (0, 0)],
            dxfattribs={"layer": "OUTLINE"},
        )
        modelspace.add_lwpolyline(
            [
                (0, width + 30),
                (length, width + 30),
                (length, width + 30 + height),
                (0, width + 30 + height),
                (0, width + 30),
            ],
            dxfattribs={"layer": "SIDE_VIEW"},
        )
        diameter = geometry.get("outer_diameter")
        if diameter:
            modelspace.add_circle(
                (length / 2.0, width / 2.0),
                float(diameter) / 2.0,
                dxfattribs={"layer": "CENTER_FEATURE"},
            )
        document.saveas(path)
        return
    except Exception:
        pass
    path.write_text(
        "0\nSECTION\n2\nHEADER\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n"
        "0\nLWPOLYLINE\n8\nOUTLINE\n90\n4\n"
        f"10\n0\n20\n0\n10\n{length}\n20\n0\n10\n{length}\n20\n{width}\n10\n0\n20\n{width}\n"
        "0\nENDSEC\n0\nEOF\n",
        encoding="ascii",
    )


def _write_bom(path: Path, template: EngineeringTemplate, spec: EngineeringObjectSpec) -> None:
    path.write_text(
        json.dumps(template.get_bom(spec), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _state_provenance(state: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in state.values():
        if not isinstance(value, dict):
            continue
        stage_records = value.get("provenance", [])
        if not isinstance(stage_records, list):
            continue
        for record in stage_records:
            if not isinstance(record, dict):
                continue
            key = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records


def write_provenance(
    path: str | Path,
    *,
    engineering_id: str,
    template: str,
    verification_status: str,
    records: list[dict[str, Any]],
) -> None:
    """Persist the evidence ledger next to the generated CAD artifacts."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "format": "factoryagent.provenance.v1",
                "engineering_id": engineering_id,
                "template": template,
                "verification_status": verification_status,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def run(
    template: EngineeringTemplate,
    spec: EngineeringObjectSpec,
    state: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, str]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    geometry = state.get("geometry", {})
    native = geometry.get("native")
    step_path = directory / "model.step"
    stl_path = directory / "model.stl"
    drawing_path = directory / "drawing.svg"
    sheet_path = directory / "sheet.svg"
    png_path = directory / "sheet.png"
    dxf_path = directory / "drawing.dxf"
    bom_path = directory / "bom.json"
    provenance_path = directory / "provenance.json"

    if native is not None:
        from cadquery import exporters  # type: ignore

        exporters.export(native, str(step_path), exportType="STEP")
        exporters.export(native, str(stl_path), exportType="STL", tolerance=0.01, angularTolerance=0.1)
        backend = "cadquery"
    else:
        _fallback_step(step_path, spec)
        _fallback_stl(stl_path, spec)
        backend = "fallback"
    svg = _drawing_svg(spec, geometry)
    drawing_path.write_text(svg, encoding="utf-8")
    sheet_path.write_text(svg, encoding="utf-8")
    _write_png(png_path, spec, geometry)
    _write_dxf(dxf_path, geometry)
    _write_bom(bom_path, template, spec)
    write_provenance(
        provenance_path,
        engineering_id=str(state.get("_engineering_id", "unknown")),
        template=template.name,
        verification_status="COMPUTED",
        records=_state_provenance(state),
    )

    outputs: dict[str, str] = {
        "step": str(step_path),
        "stl": str(stl_path),
        "drawing": str(drawing_path),
        "sheet": str(sheet_path),
        "png": str(png_path),
        "dxf": str(dxf_path),
        "bom": str(bom_path),
        "provenance": str(provenance_path),
        "backend": backend,
    }

    assembly = state.get("assembly")
    if isinstance(assembly, dict) and assembly.get("status") not in {None, "skipped", "unsupported"}:
        recipe = write_assembly_recipe(directory, model_path=step_path, assembly=assembly)
        outputs.update(
            {
                "assembly_constraints": str(recipe["constraints"]),
                "freecad_recipe": str(recipe["recipe"]),
            }
        )
        if Path(str(recipe["fcstd"])).is_file():
            outputs["fcstd"] = str(recipe["fcstd"])

    fem_result = state.get("fem")
    if isinstance(fem_result, dict) and fem_result.get("analysis_plan"):
        outputs["fem_plan"] = str(fem_result["analysis_plan"])
    if isinstance(fem_result, dict) and fem_result.get("calculix_template"):
        outputs["fem_template"] = str(fem_result["calculix_template"])
    return outputs
