"""Natural-language to constrained DrawingSpec parsing.

The LLM may provide a JSON candidate through ``parse_llm_payload``. The
deterministic parser below is deliberately kept as the no-key fallback and as
the safety net for incomplete model responses.
"""

from __future__ import annotations

import math
import re
from copy import deepcopy

from app.drawing.schemas import AssemblyComponent, AssemblySpec, DrawingSpec, HoleSpec, PartSpec, ShaftSection


_NUMBER = r"(\d+(?:\.\d+)?)"


def _number(patterns: list[str], text: str) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            for group in match.groups():
                if group is not None:
                    return float(group)
    return None


def _count(text: str) -> int:
    if any(token in text for token in ("四个", "四孔", "四角", "4个", "4 孔", "4孔")):
        return 4
    if any(token in text for token in ("六个", "六孔", "6个", "6 孔", "6孔")):
        return 6
    match = re.search(r"(\d+)\s*(?:个|只)?\s*(?:通孔|安装孔|螺栓孔|孔)", text)
    return int(match.group(1)) if match else 0


def _material(text: str) -> str:
    if "6082" in text:
        return "Aluminum 6082"
    if "7075" in text:
        return "Aluminum 7075"
    if "6061" in text or "铝" in text:
        return "Aluminum 6061-T6"
    if "不锈钢" in text:
        return "Stainless Steel"
    if "钢" in text:
        return "Alloy Steel"
    match = re.search(r"material\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9 ._-]{2,40})", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else "Aluminum 6061-T6"


def _dimensions(text: str) -> tuple[float | None, float | None, float | None]:
    match = re.search(
        rf"{_NUMBER}\s*[x×*]\s*{_NUMBER}\s*[x×*]\s*{_NUMBER}",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return tuple(float(value) for value in match.groups())  # type: ignore[return-value]

    length = _number([rf"(?:长|长度|length)\s*[:：]?\s*{_NUMBER}"], text)
    width = _number([rf"(?:宽|宽度|width)\s*[:：]?\s*{_NUMBER}"], text)
    height = _number(
        [
            rf"(?:厚|厚度|高度|height|thickness)\s*[:：]?\s*{_NUMBER}",
        ],
        text,
    )
    return length, width, height


def _plate_holes(length: float, width: float, text: str) -> list[HoleSpec]:
    count = _count(text)
    diameter = _number(
        [
            rf"(?:直径|孔径|diameter|dia\.?|[ØøΦφ])\s*[:：]?\s*{_NUMBER}",
            rf"{_NUMBER}\s*mm\s*(?:通孔|孔)",
        ],
        text,
    )
    if not count or diameter is None:
        return []

    offset = _number(
        [
            rf"(?:孔中心)?\s*(?:距离|距)\s*(?:边缘|两边|边)\s*{_NUMBER}",
            rf"(?:边缘|边)\s*{_NUMBER}\s*mm",
        ],
        text,
    ) or min(length, width) * 0.125

    if count == 4:
        positions = [
            (offset, offset),
            (length - offset, offset),
            (length - offset, width - offset),
            (offset, width - offset),
        ]
    else:
        positions = [
            (
                length / 2 + (length * 0.32) * math.cos(2 * math.pi * index / count),
                width / 2 + (width * 0.32) * math.sin(2 * math.pi * index / count),
            )
            for index in range(count)
        ]
    return [HoleSpec(x=x, y=y, diameter=diameter) for x, y in positions]


def _flange_part(text: str) -> PartSpec:
    outer = _number([rf"(?:外径|外圆|outer\s*diameter)\s*[:：]?\s*{_NUMBER}"], text)
    thickness = _number([rf"(?:厚|厚度|thickness)\s*[:：]?\s*{_NUMBER}"], text)
    inner = _number([rf"(?:中心孔|内径|inner\s*diameter|bore)\s*[:：]?\s*{_NUMBER}"], text)
    count = _count(text)
    bolt_diameter = _number(
        [rf"(?:直径|孔径|diameter|dia\.?|[ØøΦφ])\s*[:：]?\s*{_NUMBER}"],
        text,
    )
    outer = outer or 120.0
    thickness = thickness or 15.0
    inner = inner or outer * 0.4
    bolt_diameter = bolt_diameter or 8.0
    bolt_circle = _number(
        [rf"(?:分布圆|螺栓圆|bolt\s*circle)\s*[:：]?\s*{_NUMBER}"],
        text,
    ) or outer * 0.72

    holes: list[HoleSpec] = []
    for index in range(count):
        angle = 2 * math.pi * index / count
        holes.append(
            HoleSpec(
                x=outer / 2 + bolt_circle / 2 * math.cos(angle),
                y=outer / 2 + bolt_circle / 2 * math.sin(angle),
                diameter=bolt_diameter,
            )
        )
    return PartSpec(
        part_id="PART-01",
        name="Parametric Flange",
        part_type="flange",
        length=outer,
        width=outer,
        height=thickness,
        outer_diameter=outer,
        inner_diameter=inner,
        bolt_circle_diameter=bolt_circle,
        material=_material(text),
        holes=holes,
    )


def parse_drawing_prompt(prompt: str) -> DrawingSpec:
    """Parse a common portfolio-demo prompt into a safe DrawingSpec."""

    normalized = prompt.strip()
    if any(token in normalized.lower() for token in ("px-2100", "减速器装配", "装配体", "assembly")):
        return build_px2100_demo()

    lower = normalized.lower()
    if "法兰" in normalized or "flange" in lower:
        part = _flange_part(normalized)
    else:
        length, width, height = _dimensions(normalized)
        part_type = "plate"
        name = "Mounting Plate"
        if "轴" in normalized or "shaft" in lower:
            part_type = "shaft"
            name = "Parametric Shaft"
        elif "支架" in normalized or "bracket" in lower:
            part_type = "bracket"
            name = "Parametric Bracket"
        elif "箱体" in normalized or "housing" in lower:
            part_type = "housing"
            name = "Parametric Housing"

        length = length or 180.0
        width = width or 120.0
        height = height or 12.0
        holes = _plate_holes(length, width, normalized) if part_type == "plate" else []
        diameter = _number(
            [rf"(?:直径|外径|diameter|dia\.?|[ØøΦφ])\s*[:：]?\s*{_NUMBER}"],
            normalized,
        )
        part = PartSpec(
            part_id="PART-01",
            name=name,
            part_type=part_type,  # type: ignore[arg-type]
            length=length,
            width=width,
            height=height,
            outer_diameter=diameter if part_type == "shaft" else None,
            material=_material(normalized),
            holes=holes,
        )

    title = "MOUNTING PLATE" if part.part_type == "plate" else part.name.upper()
    return DrawingSpec(title=title, drawing_type="part", parts=[part])


def parse_llm_payload(payload: dict) -> DrawingSpec:
    """Turn an already-decoded model JSON object into a DrawingSpec."""

    return DrawingSpec.model_validate(payload)


def apply_revision_prompt(spec: DrawingSpec, prompt: str) -> DrawingSpec:
    """Update structured parameters and leave all old revisions untouched."""

    revised = deepcopy(spec)
    revised.revision += 1
    text = prompt.strip()
    part = revised.parts[0]

    new_hole_diameter = _number(
        [
            rf"(?:孔径|直径|孔)\s*(?:从\s*{_NUMBER}\s*)?(?:改成|改为|调整为|变成)\s*{_NUMBER}",
            rf"(?:孔径|直径)\s*{_NUMBER}",
            rf"改(?:成|为)\s*{_NUMBER}\s*mm\s*(?:的)?孔",
        ],
        text,
    )
    # The first pattern has two captures; use the final numeric token for it.
    if any(token in text for token in ("孔径", "直径", "孔")):
        all_numbers = re.findall(r"\d+(?:\.\d+)?", text)
        if all_numbers and any(token in text for token in ("改成", "改为", "调整", "变成")):
            new_hole_diameter = float(all_numbers[-1])
    if new_hole_diameter is not None and part.holes:
        part.holes = [hole.model_copy(update={"diameter": new_hole_diameter}) for hole in part.holes]

    new_thickness = _number(
        [
            rf"(?:厚度|厚|thickness)\s*(?:从\s*{_NUMBER}\s*)?(?:改成|改为|调整为|变成)\s*{_NUMBER}",
            rf"(?:厚度|厚|thickness)\s*{_NUMBER}",
        ],
        text,
    )
    if any(token in text for token in ("厚度", "厚", "thickness")):
        all_numbers = re.findall(r"\d+(?:\.\d+)?", text)
        if all_numbers and any(token in text for token in ("改成", "改为", "调整", "变成")):
            new_thickness = float(all_numbers[-1])
    if new_thickness is not None:
        part.height = new_thickness

    revised.design_notes.append(f"Revision {revised.revision}: {text}")
    return revised


def _bolt_pattern(diameter: float, count: int, hole_diameter: float) -> list[HoleSpec]:
    """Create a centered, deterministic bolt circle for flange geometry."""

    import math

    return [
        HoleSpec(
            x=diameter / 2 + diameter * 0.40 * math.cos(2 * math.pi * index / count),
            y=diameter / 2 + diameter * 0.40 * math.sin(2 * math.pi * index / count),
            diameter=hole_diameter,
        )
        for index in range(count)
    ]


def build_px2100_demo() -> DrawingSpec:
    """Create the deterministic, mechanically recognizable PX-2100 demo."""

    parts = [
        PartSpec(
            part_id="PX-2100-01",
            name="Output Flange",
            part_type="flange",
            length=180,
            width=180,
            height=24,
            outer_diameter=180,
            inner_diameter=55,
            bolt_circle_diameter=144,
            bolt_hole_diameter=12,
            holes=_bolt_pattern(180, 8, 12),
            material="Aluminum 6082",
        ),
        PartSpec(
            part_id="PX-2100-02",
            name="Deep Groove Bearing",
            part_type="bearing",
            length=110,
            width=110,
            height=30,
            outer_diameter=110,
            inner_diameter=55,
            secondary_outer_diameter=82,
            secondary_inner_diameter=35,
            secondary_height=24,
            material="Steel (AISI 52100)",
        ),
        PartSpec(
            part_id="PX-2100-03",
            name="Drive Shaft Set",
            part_type="shaft",
            length=250,
            width=55,
            height=55,
            outer_diameter=55,
            secondary_length=210,
            secondary_outer_diameter=35,
            slot_width=12,
            material="Alloy Steel",
        ),
        PartSpec(
            part_id="PX-2100-04",
            name="Gear Set",
            part_type="gear",
            length=150,
            width=150,
            height=32,
            outer_diameter=150,
            inner_diameter=55,
            gear_diameter=150,
            gear_teeth=36,
            secondary_gear_diameter=76,
            secondary_gear_teeth=20,
            material="Case Hardened Steel",
        ),
        PartSpec(
            part_id="PX-2100-05",
            name="Main Housing Lower",
            part_type="housing",
            length=360,
            width=240,
            height=90,
            corner_radius=20,
            wall_thickness=18,
            bearing_bore_diameter=110,
            bolt_hole_diameter=12,
            material="Aluminum 6082",
        ),
        PartSpec(
            part_id="PX-2100-06",
            name="Main Housing Upper",
            part_type="housing",
            length=360,
            width=240,
            height=90,
            corner_radius=20,
            wall_thickness=18,
            bearing_bore_diameter=110,
            bolt_hole_diameter=12,
            material="Aluminum 6082",
            notes=["Inspection cover", "Ribbed enclosure", "Bearing seat pair"],
        ),
        PartSpec(
            part_id="PX-2100-07",
            name="Sealing Gasket",
            part_type="flange",
            length=120,
            width=120,
            height=5,
            outer_diameter=120,
            inner_diameter=110,
            material="NBR",
        ),
        PartSpec(
            part_id="PX-2100-08",
            name="Motor Adapter",
            part_type="flange",
            length=160,
            width=160,
            height=28,
            outer_diameter=160,
            inner_diameter=35,
            bolt_circle_diameter=126,
            bolt_hole_diameter=10,
            slot_width=12,
            holes=_bolt_pattern(160, 6, 10),
            material="Aluminum 6082",
        ),
        PartSpec(
            part_id="PX-2100-09",
            name="Servo Motor",
            part_type="motor",
            length=220,
            width=180,
            height=180,
            outer_diameter=92,
            material="IEC Motor Package",
        ),
        PartSpec(
            part_id="PX-2100-10",
            name="Mounting Base",
            part_type="plate",
            length=760,
            width=340,
            height=24,
            corner_radius=16,
            holes=[
                HoleSpec(x=60, y=55, diameter=16),
                HoleSpec(x=700, y=55, diameter=16),
                HoleSpec(x=60, y=285, diameter=16),
                HoleSpec(x=700, y=285, diameter=16),
            ],
            material="Aluminum 6082",
        ),
        PartSpec(
            part_id="PX-2100-11",
            name="Fastener Set",
            part_type="fastener",
            length=34,
            width=14,
            height=14,
            outer_diameter=14,
            material="Stainless Steel",
        ),
    ]
    shaft = next(part for part in parts if part.part_id == "PX-2100-03")
    shaft.shaft_sections = [
        ShaftSection(length=70, diameter=48),
        ShaftSection(length=110, diameter=55),
        ShaftSection(length=70, diameter=42),
    ]
    shaft.secondary_shaft_sections = [
        ShaftSection(length=65, diameter=30),
        ShaftSection(length=95, diameter=35),
        ShaftSection(length=50, diameter=28),
    ]
    components = [
        AssemblyComponent(instance_id="output-flange", part_id="PX-2100-01", position=(20, 190, 114), rotation=(0, 90, 0), exploded_offset=(-120, 0, 0), item_number=1),
        AssemblyComponent(instance_id="output-bearing", part_id="PX-2100-02", position=(48, 190, 114), rotation=(0, 90, 0), exploded_offset=(-80, 0, 0), item_number=2, variant="output"),
        AssemblyComponent(instance_id="output-shaft", part_id="PX-2100-03", position=(55, 190, 114), rotation=(0, 90, 0), exploded_offset=(-40, 0, 0), item_number=3, variant="output"),
        AssemblyComponent(instance_id="large-gear", part_id="PX-2100-04", position=(145, 190, 114), rotation=(0, 90, 0), exploded_offset=(0, 0, 0), item_number=4, variant="large"),
        AssemblyComponent(instance_id="housing-lower", part_id="PX-2100-05", position=(140, 50, 24), rotation=(0, 0, 0), exploded_offset=(55, 0, 0), item_number=5),
        AssemblyComponent(instance_id="housing-upper", part_id="PX-2100-06", position=(140, 50, 114), rotation=(0, 0, 0), exploded_offset=(55, 0, 85), item_number=6),
        AssemblyComponent(instance_id="input-bearing", part_id="PX-2100-02", position=(370, 90, 114), rotation=(0, 90, 0), exploded_offset=(90, 0, 45), item_number=2, variant="input"),
        AssemblyComponent(instance_id="small-gear", part_id="PX-2100-04", position=(275, 90, 114), rotation=(0, 90, 0), exploded_offset=(0, 0, 40), item_number=4, variant="small"),
        AssemblyComponent(instance_id="input-shaft", part_id="PX-2100-03", position=(300, 90, 114), rotation=(0, 90, 0), exploded_offset=(0, 0, 80), item_number=3, variant="input"),
        AssemblyComponent(instance_id="gasket", part_id="PX-2100-07", position=(430, 90, 114), rotation=(0, 90, 0), exploded_offset=(100, 0, 70), item_number=7),
        AssemblyComponent(instance_id="motor-adapter", part_id="PX-2100-08", position=(460, 90, 114), rotation=(0, 90, 0), exploded_offset=(125, 0, 80), item_number=8),
        AssemblyComponent(instance_id="servo-motor", part_id="PX-2100-09", position=(490, 0, 24), rotation=(0, 0, 0), exploded_offset=(180, 0, 0), item_number=9),
        AssemblyComponent(instance_id="mounting-base", part_id="PX-2100-10", position=(0, 0, 0), rotation=(0, 0, 0), exploded_offset=(0, 0, -35), item_number=10),
        AssemblyComponent(instance_id="fastener-01", part_id="PX-2100-11", position=(210, 70, 208), rotation=(0, 0, 0), exploded_offset=(0, -40, 50), item_number=11),
        AssemblyComponent(instance_id="fastener-02", part_id="PX-2100-11", position=(410, 250, 208), rotation=(0, 0, 0), exploded_offset=(0, 40, 50), item_number=11),
    ]
    return DrawingSpec(
        title="PX-2100",
        drawing_type="assembly",
        parts=parts,
        assembly=AssemblySpec(name="PX-2100 Parametric Gear Drive", components=components),
        design_notes=[
            "Parametric portfolio gearbox assembly with stepped shafts, gear pair, bearing seats and ribbed housing.",
            "Not manufacturing release data.",
        ],
    )
