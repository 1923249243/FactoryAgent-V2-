"""One visual theme shared by SVG and Pillow sheet renderers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Typography:
    H1: int = 52
    H2: int = 22
    H3: int = 14
    Body: int = 12
    Caption: int = 10
    Dimension: int = 11
    Table: int = 9

    def as_dict(self) -> dict[str, int]:
        return {
            "H1": self.H1,
            "H2": self.H2,
            "H3": self.H3,
            "Body": self.Body,
            "Caption": self.Caption,
            "Dimension": self.Dimension,
            "Table": self.Table,
        }


@dataclass(frozen=True)
class EngineeringTheme:
    # Requested PX-2100 engineering-board palette.
    background: str = "#F3F6F9"
    title_color: str = "#102D49"
    accent_color: str = "#2F6FA8"
    body_text: str = "#586A79"
    cad_dark: str = "#454D55"
    cad_light: str = "#D7DDE2"
    dimension_color: str = "#60798E"
    border_color: str = "#B8C7D4"
    metal: str = "#AEB8BF"
    metal_mid: str = "#89959E"
    metal_highlight: str = "#EEF2F5"
    cavity: str = "#293942"
    shadow: str = "#CBD5DC"
    # Backward-compatible alias used by existing drawing helpers.
    line_color: str = "#586A79"
    font_family: str = "Arial,Segoe UI,sans-serif"
    typography: Typography = field(default_factory=Typography)


DEFAULT_THEME = EngineeringTheme()
