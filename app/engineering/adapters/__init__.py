"""Optional engineering backends.

The core application stays usable on a small Python installation.  Adapters
detect optional CAD, dynamics and solver programs and return an explicit
status instead of pretending that an unavailable solver produced a result.
"""

from app.engineering.adapters.adapter import generate_mechanical_adapter
from app.engineering.adapters.freecad import write_assembly_recipe
from app.engineering.adapters.fem import run_fem_adapter
from app.engineering.adapters.motor import import_motor_step, motor_step_status

__all__ = [
    "import_motor_step",
    "motor_step_status",
    "generate_mechanical_adapter",
    "run_fem_adapter",
    "write_assembly_recipe",
]
