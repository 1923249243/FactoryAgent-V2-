from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def freecad_command() -> str | None:
    """Find a FreeCAD command-line executable when it is installed."""

    for name in ("FreeCADCmd", "freecadcmd", "FreeCAD", "freecad"):
        command = shutil.which(name)
        if command:
            return command
    return None


def freecad_available() -> bool:
    try:
        import FreeCAD  # type: ignore  # noqa: F401

        return True
    except Exception:
        return freecad_command() is not None


def _script_payload(model_path: str, constraints: dict[str, Any], output_path: str) -> str:
    model_literal = repr(model_path)
    output_literal = repr(output_path)
    constraints_literal = repr(json.dumps(constraints, ensure_ascii=False, indent=2))
    return f'''"""FactoryAgent generated FreeCAD assembly recipe.

Open this script with FreeCAD's Python console or run it with FreeCADCmd.
The geometry is imported from the same STEP exported by the Engineering Agent.
Joint definitions are stored as named properties so they can be promoted to
Assembly4/A2plus constraints in a FreeCAD installation with that workbench.
"""
import FreeCAD as App
import Part

MODEL_PATH = {model_literal}
OUTPUT_PATH = {output_literal}
CONSTRAINTS_JSON = {constraints_literal}

doc = App.newDocument("FactoryAgentAssembly")
shape = Part.read(MODEL_PATH)
geometry = doc.addObject("PartDesign::Feature", "ParametricGeometry")
geometry.Label = "FactoryAgent exported geometry"
geometry.Shape = shape
metadata = doc.addObject("App::FeaturePython", "AssemblyConstraintRecipe")
metadata.Label = "Assembly constraints (recipe)"
metadata.addProperty("App::PropertyString", "ConstraintJSON", "FactoryAgent")
metadata.ConstraintJSON = CONSTRAINTS_JSON
doc.recompute()
doc.saveAs(OUTPUT_PATH)
'''


def write_assembly_recipe(
    directory: str | Path,
    *,
    model_path: str | Path,
    assembly: dict[str, Any],
) -> dict[str, Any]:
    """Write a portable FreeCAD recipe and serializable joint definition.

    A recipe is useful even when FreeCAD is not installed on the API host: a
    designer can open the generated script on a workstation with FreeCAD.
    """

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    constraints_path = directory / "assembly_constraints.json"
    script_path = directory / "freecad_assembly.py"
    fcstd_path = directory / "assembly.FCStd"
    constraints_path.write_text(
        json.dumps(assembly, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    script_path.write_text(
        _script_payload(str(Path(model_path).resolve()), assembly, str(fcstd_path.resolve())),
        encoding="utf-8",
    )
    command = freecad_command()
    return {
        "status": "recipe_ready",
        "backend": "freecad_recipe",
        "freecad_available": freecad_available(),
        "freecad_command": command,
        "constraints": str(constraints_path),
        "recipe": str(script_path),
        "fcstd": str(fcstd_path),
        "message": (
            "FreeCAD recipe generated; run freecad_assembly.py in FreeCAD to create FCStd."
            if command is None
            else "FreeCAD detected; recipe is ready for native execution."
        ),
    }
