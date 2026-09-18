"""Fetch the public Oriental Motor evidence used by the V4.3 demo.

The repository intentionally does not commit vendor CAD/PDF binaries.  Run
this script when the local evidence bundle is needed for a real STEP import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path

from app.config import settings
from app.engineering.catalog import (
    ORIENTAL_MOTOR_DATASHEET_URL,
    ORIENTAL_MOTOR_DIMENSION_URL,
    ORIENTAL_MOTOR_STEP_URL,
)


def _download(url: str, target: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "FactoryAgent/4.3"})
    with urllib.request.urlopen(request, timeout=90) as response:
        target.write_bytes(response.read())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_member(archive: Path, output: Path, suffix: str) -> None:
    with zipfile.ZipFile(archive) as bundle:
        members = [name for name in bundle.namelist() if name.lower().endswith(suffix)]
        if not members:
            raise RuntimeError(f"no {suffix} member found in {archive.name}")
        output.write_bytes(bundle.read(members[0]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path(settings.engineering_evidence_dir))
    parser.add_argument("--force", action="store_true", help="redownload existing evidence")
    args = parser.parse_args()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    downloads = output_dir / ".downloads"
    downloads.mkdir(exist_ok=True)

    step_archive = downloads / "B968-B.zip"
    dxf_archive = downloads / "B968.zip"
    step_path = output_dir / "B968-B.step"
    dxf_path = output_dir / "B968.dxf"
    catalog_path = output_dir / "PKP-series-catalog.pdf"

    if args.force or not step_path.is_file():
        _download(ORIENTAL_MOTOR_STEP_URL, step_archive)
        _extract_member(step_archive, step_path, ".step")
    if args.force or not dxf_path.is_file():
        _download(ORIENTAL_MOTOR_DIMENSION_URL, dxf_archive)
        _extract_member(dxf_archive, dxf_path, ".dxf")
    if args.force or not catalog_path.is_file():
        _download(ORIENTAL_MOTOR_DATASHEET_URL, catalog_path)

    manifest = {
        "model": "PKP243D02B",
        "sources": {
            "step": ORIENTAL_MOTOR_STEP_URL,
            "dimension_dxf": ORIENTAL_MOTOR_DIMENSION_URL,
            "catalog_pdf": ORIENTAL_MOTOR_DATASHEET_URL,
        },
        "files": {
            path.name: {"path": str(path), "sha256": _sha256(path)}
            for path in (step_path, dxf_path, catalog_path)
        },
    }
    (output_dir / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
