from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.drawing.cad.engine import build_geometry
from app.drawing.cad.exporters import export_dxf, export_sheet, export_step, export_stl, export_svg
from app.drawing.drawing.bom import generate_bom
from app.drawing.parser import apply_revision_prompt, parse_drawing_prompt
from app.drawing.schemas import DrawingSpec
from app.drawing.storage import artifact_names, artifact_path, drawing_dir, list_drawing_ids, load_json, load_spec_payload, save_json
from app.drawing.validator import DrawingValidationError, validate_drawing_spec


class DrawingNotFoundError(FileNotFoundError):
    pass


def _drawing_id() -> str:
    return f"DRW-{uuid4().hex[:8].upper()}"


def _outputs(drawing_id: str) -> dict[str, str]:
    directory = drawing_dir(drawing_id)
    return {key: str(directory / filename) for key, filename in artifact_names().items()}


def _generate(drawing_id: str, spec: DrawingSpec) -> dict:
    directory = drawing_dir(drawing_id)
    directory.mkdir(parents=True, exist_ok=True)
    validate_drawing_spec(spec)
    geometry = build_geometry(spec)
    step_backend = export_step(geometry, directory / "model.step")
    stl_backend = export_stl(geometry, directory / "model.stl")
    dxf_backend = export_dxf(geometry, directory / "drawing.dxf")
    export_svg(spec, directory / "drawing.svg")
    sheet_status = export_sheet(spec, directory / "sheet.svg", directory / "sheet.png", geometry=geometry)
    bom = generate_bom(spec)
    save_json(directory / "bom.json", bom)
    save_json(directory / "spec.json", spec.model_dump(mode="json"))
    save_json(directory / f"spec_v{spec.revision}.json", spec.model_dump(mode="json"))
    manifest = {
        "drawing_id": drawing_id,
        "status": "completed",
        "revision": spec.revision,
        "drawing_type": spec.drawing_type,
        "backend": geometry.backend,
        "exporters": {
            "step": step_backend,
            "stl": stl_backend,
            "dxf": dxf_backend,
            "sheet_png": sheet_status["png_renderer"],
        },
        "outputs": _outputs(drawing_id),
        "bom": bom,
    }
    save_json(directory / "manifest.json", manifest)
    return manifest | {"spec": spec.model_dump(mode="json")}


def create_drawing(prompt: str, spec: DrawingSpec | None = None) -> dict:
    if spec is None:
        # Import lazily so the base maintenance app remains usable even when
        # the optional drawing stack is not installed.
        try:
            from app.agent.llm import parse_design_intent

            spec = parse_design_intent(prompt)
        except Exception:
            spec = None
    drawing_spec = spec or parse_drawing_prompt(prompt)
    drawing_id = _drawing_id()
    return _generate(drawing_id, drawing_spec)


def get_drawing(drawing_id: str) -> dict:
    try:
        directory = drawing_dir(drawing_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.exists():
            raise DrawingNotFoundError(drawing_id)
        manifest = load_json(manifest_path)
        manifest["spec"] = load_spec_payload(drawing_id)
        manifest["outputs"] = _outputs(drawing_id)
        manifest["bom"] = load_json(directory / "bom.json")
        return manifest
    except (FileNotFoundError, ValueError) as exc:
        raise DrawingNotFoundError(drawing_id) from exc


def revise_drawing(drawing_id: str, prompt: str) -> dict:
    try:
        current = DrawingSpec.model_validate(load_spec_payload(drawing_id))
    except (FileNotFoundError, ValueError) as exc:
        raise DrawingNotFoundError(drawing_id) from exc
    revised = apply_revision_prompt(current, prompt)
    revised.parent_drawing_id = drawing_id
    return _generate(drawing_id, revised)


def latest_drawing_id() -> str | None:
    ids = list_drawing_ids()
    return ids[0] if ids else None


def artifact_file(drawing_id: str, artifact: str) -> Path:
    if artifact not in artifact_names():
        raise DrawingNotFoundError(f"{drawing_id}/{artifact}")
    path = artifact_path(drawing_id, artifact)
    if not path.is_file():
        raise DrawingNotFoundError(f"{drawing_id}/{artifact}")
    return path
