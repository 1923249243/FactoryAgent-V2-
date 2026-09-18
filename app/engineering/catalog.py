from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from app.config import settings
from app.engineering.schemas import EvidenceItem, MotorSpec


ORIENTAL_MOTOR_PRODUCT_URL = (
    "https://catalog.orientalmotor.com/item/42mm-frame-stepper-motors/"
    "42mm-pkp-series-2-phase-bipolar-stepper-motors/pkp243d02b"
)
ORIENTAL_MOTOR_STEP_URL = "https://www.orientalmotor.com/products/CAD-3D/B968-B.zip"
ORIENTAL_MOTOR_DIMENSION_URL = "https://www.orientalmotor.com/products/CAD-3D/B968.zip"
ORIENTAL_MOTOR_DATASHEET_URL = (
    "https://www.orientalmotor.com/products/pdfs/2018-2019/"
    "549%20PKP%20Series%20Catalog.pdf"
)


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _evidence(path: Path | None, kind: str, reference: str, note: str) -> dict[str, Any]:
    return EvidenceItem(
        kind=kind,
        reference=reference,
        path=str(path) if path is not None and path.is_file() else None,
        sha256=_sha256(path) if path is not None else None,
        note=note,
    ).model_dump(mode="json")


def oriental_motor_pkp243d02b() -> MotorSpec:
    root = Path(settings.engineering_evidence_dir)
    step_path = root / "B968-B.step"
    dimension_path = root / "B968.dxf"
    datasheet_path = root / "PKP-series-catalog.pdf"
    evidence = [
        _evidence(
            step_path,
            "manufacturer_step",
            ORIENTAL_MOTOR_STEP_URL,
            "Official Oriental Motor 3D CAD archive for B968-B.",
        ),
        _evidence(
            dimension_path,
            "manufacturer_dxf",
            ORIENTAL_MOTOR_DIMENSION_URL,
            "Official Oriental Motor dimension drawing archive for B968.",
        ),
        _evidence(
            datasheet_path,
            "manufacturer_catalog",
            ORIENTAL_MOTOR_DATASHEET_URL,
            "Official PKP Series catalog PDF.",
        ),
        _evidence(
            None,
            "manufacturer_product_page",
            ORIENTAL_MOTOR_PRODUCT_URL,
            "Official product page with model, frame, shaft and holding-torque data.",
        ),
    ]
    return MotorSpec(
        model="PKP243D02B",
        manufacturer="Oriental Motor",
        verified=True,
        source="official_manufacturer_catalog",
        shaft_diameter_mm=5.0,
        shaft_length_mm=20.0,
        pilot_diameter_mm=22.0,
        bolt_circle_diameter_mm=31.0,
        bolt_hole_diameter_mm=3.4,
        body_diameter_mm=42.0,
        body_length_mm=33.0,
        face_width_mm=42.0,
        face_height_mm=42.0,
        bolt_count=4,
        rated_torque_nm=0.32,
        max_rpm=600.0,
        max_rpm_source="engineering_demo_operating_ceiling_not_manufacturer_maximum",
        rated_torque_source="official_holding_torque_0.32_Nm",
        step_path=str(step_path),
        step_url=ORIENTAL_MOTOR_STEP_URL,
        datasheet_url=ORIENTAL_MOTOR_DATASHEET_URL,
        catalog_id="oriental_motor_pkp243d02b",
        evidence=evidence,
    )


def motor_catalog() -> list[MotorSpec]:
    return [oriental_motor_pkp243d02b()]


def get_catalog_motor(catalog_id: str) -> MotorSpec | None:
    for motor in motor_catalog():
        if motor.catalog_id == catalog_id or motor.model.lower() == catalog_id.lower():
            return motor
    return None


def catalog_payload() -> list[dict[str, Any]]:
    return [motor.model_dump(mode="json") for motor in motor_catalog()]
