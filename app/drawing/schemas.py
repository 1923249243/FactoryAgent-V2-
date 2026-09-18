from typing import Literal

from pydantic import BaseModel, Field, field_validator


PartType = Literal[
    "plate",
    "flange",
    "shaft",
    "bracket",
    "housing",
    "gear",
    "bearing",
    "motor",
    "fastener",
]
DrawingType = Literal["part", "assembly"]


class HoleSpec(BaseModel):
    x: float = Field(gt=0)
    y: float = Field(gt=0)
    diameter: float = Field(gt=0)
    through: bool = True


class ShaftSection(BaseModel):
    """One constant-diameter section of a stepped shaft."""

    length: float = Field(gt=0)
    diameter: float = Field(gt=0)


class PartSpec(BaseModel):
    """A constrained, serializable description of one mechanical part.

    The drawing agent only executes data validated by this model. It never
    executes code returned by an LLM.
    """

    part_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    part_type: PartType
    length: float | None = Field(default=None, gt=0)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    material: str = Field(default="Aluminum 6061-T6", min_length=1, max_length=120)
    holes: list[HoleSpec] = Field(default_factory=list)
    outer_diameter: float | None = Field(default=None, gt=0)
    inner_diameter: float | None = Field(default=None, gt=0)
    bolt_circle_diameter: float | None = Field(default=None, gt=0)
    slot_width: float | None = Field(default=None, gt=0)
    corner_radius: float | None = Field(default=None, gt=0)
    wall_thickness: float | None = Field(default=None, gt=0)
    bearing_bore_diameter: float | None = Field(default=None, gt=0)
    bolt_hole_diameter: float | None = Field(default=None, gt=0)
    gear_diameter: float | None = Field(default=None, gt=0)
    gear_teeth: int | None = Field(default=None, ge=6)
    secondary_length: float | None = Field(default=None, gt=0)
    secondary_height: float | None = Field(default=None, gt=0)
    secondary_outer_diameter: float | None = Field(default=None, gt=0)
    secondary_inner_diameter: float | None = Field(default=None, gt=0)
    secondary_gear_diameter: float | None = Field(default=None, gt=0)
    secondary_gear_teeth: int | None = Field(default=None, ge=6)
    shaft_sections: list[ShaftSection] = Field(default_factory=list)
    secondary_shaft_sections: list[ShaftSection] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("part_id", mode="before")
    @classmethod
    def blank_part_id_to_none(cls, value: str | None) -> str | None:
        return value or None


class AssemblyComponent(BaseModel):
    instance_id: str = Field(min_length=1, max_length=80)
    part_id: str = Field(min_length=1, max_length=80)
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    exploded_offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    item_number: int | None = Field(default=None, ge=1)
    variant: str | None = Field(default=None, max_length=40)


class AssemblySpec(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    components: list[AssemblyComponent] = Field(default_factory=list)


class DrawingSpec(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    drawing_type: DrawingType
    units: Literal["mm"] = "mm"
    parts: list[PartSpec] = Field(min_length=1)
    assembly: AssemblySpec | None = None
    revision: int = Field(default=1, ge=1)
    parent_drawing_id: str | None = None
    design_notes: list[str] = Field(default_factory=list)

    @field_validator("parts")
    @classmethod
    def assign_and_validate_part_ids(cls, parts: list[PartSpec]) -> list[PartSpec]:
        ids: set[str] = set()
        for index, part in enumerate(parts, start=1):
            if not part.part_id:
                part.part_id = f"PART-{index:02d}"
            if part.part_id in ids:
                raise ValueError(f"part_id must be unique: {part.part_id}")
            ids.add(part.part_id)

        return parts

    @field_validator("assembly")
    @classmethod
    def validate_assembly_presence(cls, assembly: AssemblySpec | None) -> AssemblySpec | None:
        if assembly is not None and not assembly.components:
            raise ValueError("assembly must contain at least one component")
        return assembly
