from __future__ import annotations

from typing import Any


def pybullet_available() -> bool:
    try:
        import pybullet  # type: ignore  # noqa: F401
    except Exception:
        return False
    return True


def run_optional_pybullet_check(request: Any, samples: list[Any]) -> dict[str, Any]:
    """Run a lightweight rigid-body clearance check when PyBullet is present.

    The deterministic swept check remains the source of truth for the default
    installation.  This optional adapter deliberately uses simple box
    proxies; it does not claim contact dynamics or motor/controller fidelity.
    """

    if not pybullet_available():
        return {
            "status": "not_available",
            "backend": "deterministic_swept_kinematic",
            "available": False,
            "checked_samples": 0,
        }
    try:
        import pybullet as p  # type: ignore

        client = p.connect(p.DIRECT)
        try:
            half = max(float(request.opening_max_mm) / 2.0, 1.0)
            jaw_shape = p.createCollisionShape(p.GEOM_BOX, halfExtents=[15, 21, 14])
            left = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=jaw_shape)
            right = p.createMultiBody(baseMass=0, baseCollisionShapeIndex=jaw_shape)
            collisions: list[dict[str, Any]] = []
            for sample in samples:
                p.resetBasePositionAndOrientation(
                    left, [-float(sample.opening_mm) / 2.0 - 15.0, 0, 42], [0, 0, 0, 1]
                )
                p.resetBasePositionAndOrientation(
                    right, [float(sample.opening_mm) / 2.0 + 15.0, 0, 42], [0, 0, 0, 1]
                )
                if p.getClosestPoints(left, right, distance=0.0):
                    collisions.append({"sample": sample.index, "reason": "jaw_proxy_overlap"})
            return {
                "status": "fail" if collisions else "pass",
                "backend": "pybullet_proxy",
                "available": True,
                "checked_samples": len(samples),
                "collisions": collisions,
            }
        finally:
            p.disconnect(client)
    except Exception as exc:
        return {
            "status": "review_required",
            "backend": "pybullet_proxy",
            "available": True,
            "checked_samples": 0,
            "error": str(exc),
        }
