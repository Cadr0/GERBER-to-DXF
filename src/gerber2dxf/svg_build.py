"""Сборка SVG-path из shapely-геометрии (для предпросмотра в браузере).

Ось Y инвертирована (SVG идёт вниз).
"""

from __future__ import annotations

from typing import Iterable

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry


def _iter_polygons(geom: BaseGeometry) -> Iterable[Polygon]:
    if geom is None or geom.is_empty:
        return
    t = geom.geom_type
    if t == "Polygon":
        yield geom  # type: ignore[misc]
    elif t == "MultiPolygon":
        for p in geom.geoms:  # type: ignore[union-attr]
            yield from _iter_polygons(p)
    elif t == "GeometryCollection":
        for sub in geom.geoms:  # type: ignore[union-attr]
            yield from _iter_polygons(sub)


def _ring_to_d(ring, precision: int = 4) -> str:
    coords = list(ring.coords)
    if len(coords) < 2:
        return ""
    fmt = f"{{:.{precision}f}}"
    x0, y0 = coords[0]
    out = [f"M{fmt.format(x0)},{fmt.format(-y0)}"]
    for x, y in coords[1:]:
        out.append(f"L{fmt.format(x)},{fmt.format(-y)}")
    out.append("Z")
    return "".join(out)


def geometry_to_svg_path_d(geom: BaseGeometry, precision: int = 4) -> str:
    parts: list[str] = []
    for poly in _iter_polygons(geom):
        parts.append(_ring_to_d(poly.exterior, precision))
        for hole in poly.interiors:
            parts.append(_ring_to_d(hole, precision))
    return " ".join(p for p in parts if p)


def drill_to_svg_circles(
    hits: list[tuple[float, float, float]],
    precision: int = 4,
) -> str:
    fmt = f"{{:.{precision}f}}"
    parts: list[str] = []
    for x, y, dia in hits:
        if dia <= 0:
            continue
        r = dia / 2.0
        parts.append(
            f'<circle cx="{fmt.format(x)}" cy="{fmt.format(-y)}" r="{fmt.format(r)}"/>'
        )
    return "".join(parts)
