"""Fixed, inspectable grid for the 1600 x 1000 engineering sheet."""

from __future__ import annotations

from dataclasses import dataclass


SHEET_WIDTH = 1600
SHEET_HEIGHT = 1000
SAFE_MARGIN = 28
GRID_GAP = 16

# The upper band is deliberately reserved for the hero assembly and the key
# workpiece. The lower band is split into orthographic views on the left and
# an exploded view/BOM stack on the right.
MAIN_PANEL = (28, 142, 1000, 410)
FEATURE_PANEL = (1044, 142, 528, 410)

TOP_PANEL = (28, 570, 620, 402)
FRONT_PANEL = (664, 570, 174, 402)
SIDE_PANEL = (854, 570, 174, 402)
EXPLODED_PANEL = (1044, 570, 528, 190)
BOM_PANEL = (1044, 776, 528, 196)

# Kept as a compatibility name for callers that imported the V3 constant.
# V3.1 uses a compact footer instead of a large workflow panel so the lower
# band can follow the requested orthographic/exploded/BOM grid.
WORKFLOW_PANEL = (28, 950, 1000, 22)


@dataclass(frozen=True)
class Panel:
    name: str
    x: int
    y: int
    width: int
    height: int

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)


PANELS = (
    Panel("main", *MAIN_PANEL),
    Panel("feature", *FEATURE_PANEL),
    Panel("top", *TOP_PANEL),
    Panel("front", *FRONT_PANEL),
    Panel("side", *SIDE_PANEL),
    Panel("exploded", *EXPLODED_PANEL),
    Panel("bom", *BOM_PANEL),
)


def panel_bboxes() -> dict[str, tuple[int, int, int, int]]:
    """Return the public panel map used by validation and smoke reports."""

    return {panel.name: panel.bbox for panel in PANELS}


def _within_canvas(panel: Panel) -> bool:
    return (
        panel.x >= SAFE_MARGIN
        and panel.y >= 0
        and panel.x + panel.width <= SHEET_WIDTH - SAFE_MARGIN
        and panel.y + panel.height <= SHEET_HEIGHT - SAFE_MARGIN
        and panel.width > 0
        and panel.height > 0
    )


def validate_grid() -> None:
    """Fail early if a future layout edit leaves the fixed grid invalid."""

    if any(not _within_canvas(panel) for panel in PANELS):
        raise ValueError("sheet panel is outside the safe canvas")

    left = [Panel("top", *TOP_PANEL), Panel("front", *FRONT_PANEL), Panel("side", *SIDE_PANEL)]
    for index, first in enumerate(left):
        for second in left[index + 1 :]:
            if first.x + first.width > second.x and second.x + second.width > first.x:
                raise ValueError("orthographic panels overlap")
    if EXPLODED_PANEL[1] + EXPLODED_PANEL[3] >= BOM_PANEL[1]:
        raise ValueError("exploded and BOM panels need a positive gap")


validate_grid()
