"""DXF-экспорт геометрии слоя и сверловки."""

from __future__ import annotations

from typing import Iterable, Sequence

import ezdxf
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry


UNIT_MM = 4
UNIT_INCH = 1


def _ring_coords(ring) -> list[tuple[float, float]]:
    coords = list(ring.coords)
    if len(coords) >= 2 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [(float(x), float(y)) for x, y in coords]


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


def _apply_transform(pt: tuple[float, float], *, scale: float, flip_y: bool, tx: float, ty: float) -> tuple[float, float]:
    x, y = pt
    x = x * scale + tx
    y = y * scale + ty
    if flip_y:
        y = -y
    return x, y


def _set_units(doc, mm: bool) -> None:
    try:
        doc.header["$INSUNITS"] = UNIT_MM if mm else UNIT_INCH
    except KeyError:
        pass
    try:
        doc.units = UNIT_MM if mm else UNIT_INCH
    except Exception:
        pass


def write_geometry_dxf(
    geometry: BaseGeometry,
    path: str,
    *,
    units_mm: bool,
    flip_y: bool = False,
    scale: float = 1.0,
    translate: tuple[float, float] = (0.0, 0.0),
    layer_name: str = "GEOMETRY",
    color_index: int = 7,
) -> None:
    """Замкнутые LWPOLYLINE: внешние контуры и отверстия — отдельные полилинии."""
    doc = ezdxf.new(setup=True)
    doc.layers.add(layer_name, color=color_index)
    _set_units(doc, units_mm)
    msp = doc.modelspace()

    tx, ty = translate
    for poly in _iter_polygons(geometry):
        outer = [
            _apply_transform(pt, scale=scale, flip_y=flip_y, tx=tx, ty=ty)
            for pt in _ring_coords(poly.exterior)
        ]
        if len(outer) >= 2:
            msp.add_lwpolyline(outer, close=True, dxfattribs={"layer": layer_name})
        for hole in poly.interiors:
            inner = [
                _apply_transform(pt, scale=scale, flip_y=flip_y, tx=tx, ty=ty)
                for pt in _ring_coords(hole)
            ]
            if len(inner) >= 2:
                msp.add_lwpolyline(inner, close=True, dxfattribs={"layer": layer_name})

    doc.saveas(path)


def write_drill_dxf(
    hits: Sequence[tuple[float, float, float]],
    path: str,
    *,
    units_mm: bool,
    flip_y: bool = False,
    scale: float = 1.0,
    translate: tuple[float, float] = (0.0, 0.0),
    layer_name: str = "DRILL",
    color_index: int = 1,
) -> None:
    doc = ezdxf.new(setup=True)
    doc.layers.add(layer_name, color=color_index)
    _set_units(doc, units_mm)
    msp = doc.modelspace()
    tx, ty = translate
    for x, y, dia in hits:
        if dia <= 0:
            continue
        cx, cy = _apply_transform((x, y), scale=scale, flip_y=flip_y, tx=tx, ty=ty)
        msp.add_circle((cx, cy), radius=dia / 2.0 * scale, dxfattribs={"layer": layer_name})
    doc.saveas(path)
