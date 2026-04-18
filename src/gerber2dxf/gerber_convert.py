"""Gerber -> Shapely-геометрия через публичный пайплайн PyGerber.

Возвращает union‑геометрию слоя и bounding box в единицах файла.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from pygerber.gerber.ast import get_final_state
from pygerber.gerber.ast.nodes.enums import UnitMode
from pygerber.gerber.compiler import compile as compile_gerber
from pygerber.gerber.parser import parse as parse_gerber
from pygerber.vm import render
from pygerber.vm.shapely.vm import ShapelyResult


@dataclass
class GerberGeometry:
    shape: object  # shapely BaseGeometry (Polygon / MultiPolygon / GeometryCollection / empty)
    units: UnitMode
    min_x: float
    min_y: float
    max_x: float
    max_y: float


def parse_gerber_file(path: Path) -> GerberGeometry:
    text = path.read_text(encoding="utf-8", errors="replace")
    # сначала строгий парсер, при неудаче — устойчивый
    try:
        ast = parse_gerber(text, strict=True)
    except Exception:
        ast = parse_gerber(text, strict=False, resilient=True)
    rvmc = compile_gerber(ast)
    result = render(rvmc, backend="shapely")
    if not isinstance(result, ShapelyResult):
        raise RuntimeError(f"Ожидался ShapelyResult, получен {type(result).__name__}")
    state = get_final_state(ast)
    box = result.main_box
    return GerberGeometry(
        shape=result.shape,
        units=state.unit_mode,
        min_x=float(box.min_x),
        min_y=float(box.min_y),
        max_x=float(box.max_x),
        max_y=float(box.max_y),
    )


def units_is_mm(units: UnitMode) -> bool:
    return units is UnitMode.METRIC
