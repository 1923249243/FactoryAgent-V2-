from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MotorImportResult:
    """Result of importing a user/manufacturer supplied motor STEP file."""

    status: str
    path: str | None = None
    shape: Any | None = None
    message: str | None = None

    @property
    def imported(self) -> bool:
        return self.shape is not None and self.status == "imported"


def _cadquery() -> Any | None:
    try:
        import cadquery as cq  # type: ignore
    except Exception:
        return None
    return cq


def _shape_center(workplane: Any) -> tuple[float, float, float] | None:
    """Return the bounding-box center without depending on a CQ version."""

    try:
        box = workplane.val().BoundingBox()
        return (
            (float(box.xmin) + float(box.xmax)) / 2.0,
            (float(box.ymin) + float(box.ymax)) / 2.0,
            (float(box.zmin) + float(box.zmax)) / 2.0,
        )
    except Exception:
        return None


def import_motor_step(
    step_path: str | None,
    *,
    target_center: tuple[float, float, float] | None = None,
) -> MotorImportResult:
    """Import a real STEP motor when CadQuery and the file are available.

    The imported B-rep is deliberately kept as supplied.  When a target
    center is provided only a translation is applied; orientation and mating
    faces remain visible for a later, human-controlled assembly check.
    """

    if not step_path:
        return MotorImportResult(status="not_provided", message="motor STEP path was not provided")
    path = Path(step_path)
    if not path.is_file():
        return MotorImportResult(
            status="missing",
            path=str(path),
            message="motor STEP path does not point to a readable file",
        )
    cq = _cadquery()
    if cq is None:
        return MotorImportResult(
            status="cadquery_unavailable",
            path=str(path),
            message="CadQuery is not installed; STEP import was not attempted",
        )
    try:
        imported = cq.importers.importStep(str(path))
        if target_center is not None:
            center = _shape_center(imported)
            if center is not None:
                dx = target_center[0] - center[0]
                dy = target_center[1] - center[1]
                dz = target_center[2] - center[2]
                imported = imported.translate((dx, dy, dz))
        return MotorImportResult(status="imported", path=str(path), shape=imported)
    except Exception as exc:
        return MotorImportResult(
            status="import_failed",
            path=str(path),
            message=f"STEP import failed: {exc}",
        )


def motor_step_status(step_path: str | None) -> dict[str, Any]:
    """Return serializable import information without retaining native shapes."""

    result = import_motor_step(step_path)
    return {
        "status": result.status,
        "path": result.path,
        "imported": result.imported,
        "message": result.message,
    }
