from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.config import settings


_DRAWING_ID = re.compile(r"^DRW-[A-F0-9]{8}$")
_ARTIFACTS = {
    "sheet": "sheet.svg",
    "png": "sheet.png",
    "svg": "drawing.svg",
    "dxf": "drawing.dxf",
    "step": "model.step",
    "stl": "model.stl",
    "bom": "bom.json",
}


def drawings_root() -> Path:
    root = Path(settings.drawings_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def validate_drawing_id(drawing_id: str) -> str:
    if not _DRAWING_ID.fullmatch(drawing_id):
        raise ValueError("invalid drawing id")
    return drawing_id


def drawing_dir(drawing_id: str) -> Path:
    return drawings_root() / validate_drawing_id(drawing_id)


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_path(drawing_id: str, artifact: str) -> Path:
    if artifact not in _ARTIFACTS:
        raise ValueError(f"unsupported drawing artifact: {artifact}")
    return drawing_dir(drawing_id) / _ARTIFACTS[artifact]


def artifact_names() -> dict[str, str]:
    return dict(_ARTIFACTS)


def list_drawing_ids() -> list[str]:
    return sorted(
        (item.name for item in drawings_root().iterdir() if item.is_dir() and _DRAWING_ID.fullmatch(item.name)),
        reverse=True,
    )


def load_spec_payload(drawing_id: str) -> dict[str, Any]:
    path = drawing_dir(drawing_id) / "spec.json"
    if not path.exists():
        raise FileNotFoundError(drawing_id)
    return load_json(path)
