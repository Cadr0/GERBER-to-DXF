"""Имена выходных DXF и тип слоя по расширению."""

from __future__ import annotations

from enum import Enum
from pathlib import Path


class LayerKind(str, Enum):
    COPPER_TOP = "copper_top"
    COPPER_BOTTOM = "copper_bottom"
    SOLDERMASK_TOP = "soldermask_top"
    SOLDERMASK_BOTTOM = "soldermask_bottom"
    PASTE_TOP = "paste_top"
    PASTE_BOTTOM = "paste_bottom"
    SILK_TOP = "silk_top"
    SILK_BOTTOM = "silk_bottom"
    OUTLINE = "outline"
    MECHANICAL = "mechanical"
    DOCUMENT = "document"
    PADS_TOP = "pads_top"
    PADS_BOTTOM = "pads_bottom"
    DRILL = "drill"
    DRILL_NPTH = "drill_npth"
    DRILL_VIA = "drill_via"
    OTHER = "other"


# Цвета для UI (HEX без #), подобраны для тёмного фона.
LAYER_COLORS: dict[LayerKind, str] = {
    LayerKind.COPPER_TOP: "c0392b",        # red
    LayerKind.COPPER_BOTTOM: "2980b9",     # blue
    LayerKind.SOLDERMASK_TOP: "8e44ad",    # violet
    LayerKind.SOLDERMASK_BOTTOM: "16a085", # teal
    LayerKind.PASTE_TOP: "f1c40f",         # yellow
    LayerKind.PASTE_BOTTOM: "9b59b6",      # purple
    LayerKind.SILK_TOP: "ecf0f1",          # near-white
    LayerKind.SILK_BOTTOM: "95a5a6",       # gray
    LayerKind.OUTLINE: "2ecc71",           # green
    LayerKind.MECHANICAL: "27ae60",        # green-dark
    LayerKind.DOCUMENT: "7f8c8d",          # gray-dark
    LayerKind.PADS_TOP: "e67e22",          # orange
    LayerKind.PADS_BOTTOM: "d35400",       # orange-dark
    LayerKind.DRILL: "e74c3c",             # red
    LayerKind.DRILL_NPTH: "e67e22",        # orange
    LayerKind.DRILL_VIA: "f1c40f",         # yellow
    LayerKind.OTHER: "bdc3c7",             # light gray
}


# Расширение (в нижнем регистре) -> тип и суффикс имени выхода.
_EXT_MAP: dict[str, tuple[LayerKind, str]] = {
    ".gtl": (LayerKind.COPPER_TOP, "copper_top"),
    ".gbl": (LayerKind.COPPER_BOTTOM, "copper_bottom"),
    ".gts": (LayerKind.SOLDERMASK_TOP, "soldermask_top"),
    ".gbs": (LayerKind.SOLDERMASK_BOTTOM, "soldermask_bottom"),
    ".gtp": (LayerKind.PASTE_TOP, "paste_top"),
    ".gbp": (LayerKind.PASTE_BOTTOM, "paste_bottom"),
    ".gto": (LayerKind.SILK_TOP, "silk_top"),
    ".gbo": (LayerKind.SILK_BOTTOM, "silk_bottom"),
    ".gko": (LayerKind.OUTLINE, "outline"),
    ".gm1": (LayerKind.MECHANICAL, "mechanical_1"),
    ".gm2": (LayerKind.MECHANICAL, "mechanical_2"),
    ".gm3": (LayerKind.MECHANICAL, "mechanical_3"),
    ".gm13": (LayerKind.MECHANICAL, "mechanical_13"),
    ".gm15": (LayerKind.MECHANICAL, "mechanical_15"),
    ".gdl": (LayerKind.DOCUMENT, "document"),
    ".gpt": (LayerKind.PADS_TOP, "pads_top"),
    ".gpb": (LayerKind.PADS_BOTTOM, "pads_bottom"),
    ".drl": (LayerKind.DRILL, "drill"),
    ".exc": (LayerKind.DRILL, "drill"),
    ".xln": (LayerKind.DRILL, "drill"),
    ".txt": (LayerKind.DRILL, "drill"),
    ".gbr": (LayerKind.OTHER, "layer"),
    ".grb": (LayerKind.OTHER, "layer"),
    ".pho": (LayerKind.OTHER, "layer"),
    ".art": (LayerKind.OTHER, "layer"),
}


def classify(path: Path) -> tuple[LayerKind, str]:
    """Тип слоя и суффикс имени. Дополнительно смотрим в имя файла для drill‑подтипов."""
    ext = path.suffix.lower()
    kind, tag = _EXT_MAP.get(ext, (LayerKind.OTHER, ext.lstrip(".") or "layer"))

    name = path.name.lower()
    if kind == LayerKind.DRILL:
        if "npth" in name or "nonplated" in name or "non_plated" in name:
            return LayerKind.DRILL_NPTH, "drill_npth"
        if "via" in name:
            return LayerKind.DRILL_VIA, "drill_via"
    if kind == LayerKind.OTHER:
        # Специально для EasyEDA: Drill_PTH_Through.DRL, Drill_PTH_Through_Via.DRL
        if name.startswith("drill") or "drill" in name:
            if "via" in name:
                return LayerKind.DRILL_VIA, "drill_via"
            if "npth" in name:
                return LayerKind.DRILL_NPTH, "drill_npth"
            return LayerKind.DRILL, "drill"
    return kind, tag


def output_stem(source: Path, project: str | None = None) -> str:
    _, tag = classify(source)
    base = project or source.stem
    return f"{base}_{tag}"
