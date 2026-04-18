"""Загрузка набора Gerber/Excellon, детекция слоёв, кэш SVG, экспорт."""

from __future__ import annotations

import shutil
import threading
import traceback
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from gerber2dxf.dxf_export import write_drill_dxf, write_geometry_dxf
from gerber2dxf.excellon import DrillUnits, is_probably_excellon, read_drill_file
from gerber2dxf.gerber_convert import parse_gerber_file, units_is_mm
from gerber2dxf.naming import LAYER_COLORS, LayerKind, classify, output_stem
from gerber2dxf.svg_build import drill_to_svg_circles, geometry_to_svg_path_d


GERBER_EXTS = {
    ".gtl", ".gbl", ".gts", ".gbs", ".gtp", ".gbp",
    ".gto", ".gbo", ".gko", ".gdl",
    ".gm1", ".gm2", ".gm3", ".gm13", ".gm15",
    ".gbr", ".grb", ".pho", ".art",
    ".gpt", ".gpb",
}
DRILL_EXTS = {".drl", ".exc", ".xln", ".txt"}


@dataclass
class LayerInfo:
    id: str
    filename: str
    kind: str
    tag: str
    color: str
    is_drill: bool
    units: str  # "MM" / "INCH"
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    error: Optional[str] = None
    svg_path_d: Optional[str] = None
    svg_circles: Optional[str] = None
    drill_count: int = 0


@dataclass
class Project:
    id: str
    root: Path
    project_name: str = "board"
    layers: list[LayerInfo] = field(default_factory=list)

    def bbox(self, layer_ids: list[str] | None = None) -> tuple[float, float, float, float] | None:
        xs_min: list[float] = []
        ys_min: list[float] = []
        xs_max: list[float] = []
        ys_max: list[float] = []
        for lay in self.layers:
            if layer_ids is not None and lay.id not in layer_ids:
                continue
            if lay.error:
                continue
            xs_min.append(lay.min_x)
            ys_min.append(lay.min_y)
            xs_max.append(lay.max_x)
            ys_max.append(lay.max_y)
        if not xs_min:
            return None
        return (min(xs_min), min(ys_min), max(xs_max), max(ys_max))


class ProjectStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.projects: dict[str, Project] = {}
        self._lock = threading.Lock()

    def create(self) -> Project:
        pid = uuid.uuid4().hex[:12]
        root = self.base_dir / pid
        root.mkdir(parents=True, exist_ok=True)
        (root / "inputs").mkdir(exist_ok=True)
        (root / "outputs").mkdir(exist_ok=True)
        proj = Project(id=pid, root=root)
        with self._lock:
            self.projects[pid] = proj
        return proj

    def get(self, pid: str) -> Project:
        with self._lock:
            proj = self.projects.get(pid)
        if not proj:
            raise KeyError(f"Project {pid} not found")
        return proj

    def delete(self, pid: str) -> None:
        with self._lock:
            proj = self.projects.pop(pid, None)
        if proj is not None:
            shutil.rmtree(proj.root, ignore_errors=True)


def accept_extension(name: str) -> bool:
    ext = Path(name).suffix.lower()
    return ext in GERBER_EXTS or ext in DRILL_EXTS or ext == ".zip"


# back-compat alias (был приватным в ранней версии)
_accept_extension = accept_extension


def save_uploaded(project: Project, filename: str, data: bytes) -> list[Path]:
    """Сохраняет файл в inputs. Если это .zip — распаковывает внутрь."""
    target_dir = project.root / "inputs"
    target_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    dest = target_dir / safe_name
    dest.write_bytes(data)

    saved: list[Path] = []
    if dest.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(dest) as zf:
                for zi in zf.infolist():
                    if zi.is_dir():
                        continue
                    inner_name = Path(zi.filename).name
                    if not inner_name:
                        continue
                    if not accept_extension(inner_name):
                        continue
                    out = target_dir / inner_name
                    with zf.open(zi) as src, open(out, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    saved.append(out)
        finally:
            try:
                dest.unlink()
            except OSError:
                pass
    else:
        saved.append(dest)

    return saved


def _layer_id(path: Path) -> str:
    # стабильный id — хэш от относительного пути
    import hashlib
    return hashlib.sha1(path.name.encode("utf-8", "ignore")).hexdigest()[:10]


def _detect_project_name(files: list[Path]) -> str:
    if not files:
        return "board"
    parent_name = files[0].parent.name
    if parent_name and parent_name != "inputs":
        return parent_name
    # общий префикс по именам
    stems = [p.stem for p in files]
    prefix = stems[0]
    for s in stems[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                break
        if not prefix:
            break
    return prefix.rstrip("_- ") or "board"


def analyze_project(project: Project) -> Project:
    inputs = project.root / "inputs"
    files = sorted(
        [p for p in inputs.iterdir() if p.is_file() and _accept_extension(p.name)],
        key=lambda p: p.name.lower(),
    )
    project.project_name = _detect_project_name(files)
    project.layers.clear()

    for p in files:
        try:
            info = _analyze_one(p)
            project.layers.append(info)
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc(limit=3)
            project.layers.append(
                LayerInfo(
                    id=_layer_id(p),
                    filename=p.name,
                    kind=LayerKind.OTHER.value,
                    tag="layer",
                    color=LAYER_COLORS[LayerKind.OTHER],
                    is_drill=False,
                    units="MM",
                    min_x=0, min_y=0, max_x=0, max_y=0,
                    error=f"{exc}\n{tb}",
                )
            )
    return project


def _analyze_one(path: Path) -> LayerInfo:
    kind, tag = classify(path)
    color = LAYER_COLORS.get(kind, LAYER_COLORS[LayerKind.OTHER])

    if is_probably_excellon(path) or kind in {LayerKind.DRILL, LayerKind.DRILL_NPTH, LayerKind.DRILL_VIA}:
        hits, units = read_drill_file(path)
        if hits:
            xs = [h.x for h in hits]
            ys = [h.y for h in hits]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            # расширим bbox на радиусы
            max_r = max((h.diameter / 2.0 for h in hits), default=0.5)
            min_x -= max_r; min_y -= max_r; max_x += max_r; max_y += max_r
        else:
            min_x = min_y = max_x = max_y = 0.0

        circles = drill_to_svg_circles([(h.x, h.y, h.diameter) for h in hits])
        return LayerInfo(
            id=_layer_id(path),
            filename=path.name,
            kind=kind.value,
            tag=tag,
            color=color,
            is_drill=True,
            units="MM" if units is DrillUnits.MM else "INCH",
            min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y,
            svg_circles=circles,
            drill_count=len(hits),
        )

    # Gerber
    geom = parse_gerber_file(path)
    path_d = geometry_to_svg_path_d(geom.shape)
    return LayerInfo(
        id=_layer_id(path),
        filename=path.name,
        kind=kind.value,
        tag=tag,
        color=color,
        is_drill=False,
        units="MM" if units_is_mm(geom.units) else "INCH",
        min_x=geom.min_x, min_y=geom.min_y,
        max_x=geom.max_x, max_y=geom.max_y,
        svg_path_d=path_d,
    )


@dataclass
class ExportSettings:
    flip_y: bool = False
    scale: float = 1.0
    translate_x: float = 0.0
    translate_y: float = 0.0
    merge_into_single_dxf: bool = False
    filename_prefix: Optional[str] = None


def export_project(
    project: Project,
    layer_ids: list[str],
    settings: ExportSettings,
) -> Path:
    """Возвращает путь к ZIP с DXF-файлами либо к одному DXF, если merge_into_single_dxf."""
    out_dir = project.root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.iterdir():
        try:
            old.unlink()
        except OSError:
            pass

    prefix = settings.filename_prefix or project.project_name
    selected = [lay for lay in project.layers if lay.id in layer_ids and not lay.error]

    produced: list[Path] = []
    if settings.merge_into_single_dxf:
        # Один DXF со слоями AutoCAD
        import ezdxf
        doc = ezdxf.new(setup=True)
        doc.header["$INSUNITS"] = 4  # MM, даже если часть в inch; принудительный единый стандарт
        msp = doc.modelspace()
        # Несколько файлов могут иметь одинаковый kind (например, два DRL) —
        # не даём ezdxf упасть с "LAYER 'DRILL' already exists".
        for lay in selected:
            layer_name = (lay.kind or "layer").upper() or "LAYER"
            if not doc.layers.has_entry(layer_name):
                doc.layers.add(
                    layer_name,
                    color=_ezdxf_color_for(lay.kind),
                )
            _draw_layer_into_ezdxf(
                msp,
                lay,
                project.root / "inputs" / lay.filename,
                layer_name=layer_name,
                settings=settings,
            )
        dxf_path = out_dir / f"{prefix}_all_layers.dxf"
        doc.saveas(dxf_path)
        produced.append(dxf_path)
    else:
        for lay in selected:
            src = project.root / "inputs" / lay.filename
            out_name = f"{prefix}_{lay.tag}.dxf"
            out_path = out_dir / out_name
            try:
                if lay.is_drill:
                    hits, units = read_drill_file(src)
                    write_drill_dxf(
                        [(h.x, h.y, h.diameter) for h in hits],
                        str(out_path),
                        units_mm=(units is DrillUnits.MM),
                        flip_y=settings.flip_y,
                        scale=settings.scale,
                        translate=(settings.translate_x, settings.translate_y),
                        layer_name=lay.kind.upper(),
                        color_index=_ezdxf_color_for(lay.kind),
                    )
                else:
                    geom = parse_gerber_file(src)
                    write_geometry_dxf(
                        geom.shape,
                        str(out_path),
                        units_mm=units_is_mm(geom.units),
                        flip_y=settings.flip_y,
                        scale=settings.scale,
                        translate=(settings.translate_x, settings.translate_y),
                        layer_name=lay.kind.upper(),
                        color_index=_ezdxf_color_for(lay.kind),
                    )
                produced.append(out_path)
            except Exception:
                traceback.print_exc()
                continue

    # Упаковываем в zip при множественных файлах
    if len(produced) == 1 and not settings.merge_into_single_dxf:
        return produced[0]

    zip_path = out_dir / f"{prefix}_dxf.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in produced:
            zf.write(p, arcname=p.name)
    return zip_path


def _ezdxf_color_for(kind: str) -> int:
    # ACI-палитра: 1=red, 2=yellow, 3=green, 4=cyan, 5=blue, 6=magenta, 7=white/black, 8=gray.
    # ВАЖНО: color_index=0 означает «ByBlock» и в matplotlib-рендере DXF
    # даёт нулевой цвет (невидимо на тёмном фоне). Никогда не используем 0 здесь.
    mapping = {
        LayerKind.COPPER_TOP.value: 1,         # red
        LayerKind.COPPER_BOTTOM.value: 5,      # blue
        LayerKind.SOLDERMASK_TOP.value: 6,     # magenta
        LayerKind.SOLDERMASK_BOTTOM.value: 4,  # cyan
        LayerKind.PASTE_TOP.value: 2,          # yellow
        LayerKind.PASTE_BOTTOM.value: 214,     # светло-оранжевый
        LayerKind.SILK_TOP.value: 7,           # white/black
        LayerKind.SILK_BOTTOM.value: 9,        # light gray
        LayerKind.OUTLINE.value: 3,            # green
        LayerKind.MECHANICAL.value: 3,         # green
        LayerKind.DOCUMENT.value: 8,           # dark gray
        LayerKind.PADS_TOP.value: 40,          # оранжевый
        LayerKind.PADS_BOTTOM.value: 20,       # тёмно-оранжевый
        LayerKind.DRILL.value: 1,              # red (был 0 -> невидимо)
        LayerKind.DRILL_NPTH.value: 30,        # orange
        LayerKind.DRILL_VIA.value: 2,          # yellow
    }
    return mapping.get(kind, 7)


def _draw_layer_into_ezdxf(msp, lay: LayerInfo, src: Path, *, layer_name: str, settings: ExportSettings) -> None:
    if lay.is_drill:
        hits, _ = read_drill_file(src)
        for h in hits:
            if h.diameter <= 0:
                continue
            x = h.x * settings.scale + settings.translate_x
            y = h.y * settings.scale + settings.translate_y
            if settings.flip_y:
                y = -y
            msp.add_circle((x, y), radius=h.diameter / 2.0 * settings.scale, dxfattribs={"layer": layer_name})
    else:
        geom = parse_gerber_file(src)
        from shapely.geometry import Polygon
        from shapely.geometry.base import BaseGeometry

        def _iter(g: BaseGeometry):
            if g.is_empty:
                return
            t = g.geom_type
            if t == "Polygon":
                yield g
            elif t == "MultiPolygon":
                for p in g.geoms:
                    yield from _iter(p)
            elif t == "GeometryCollection":
                for s in g.geoms:
                    yield from _iter(s)

        for poly in _iter(geom.shape):
            for ring in [poly.exterior, *poly.interiors]:
                pts = list(ring.coords)
                if len(pts) >= 2 and pts[0] == pts[-1]:
                    pts = pts[:-1]
                if len(pts) < 2:
                    continue
                transformed = []
                for x, y in pts:
                    x2 = x * settings.scale + settings.translate_x
                    y2 = y * settings.scale + settings.translate_y
                    if settings.flip_y:
                        y2 = -y2
                    transformed.append((x2, y2))
                msp.add_lwpolyline(transformed, close=True, dxfattribs={"layer": layer_name})


def layer_info_dict(lay: LayerInfo) -> dict:
    d = asdict(lay)
    # SVG-данные крупные — не возвращаем в списке, отдаём отдельным эндпоинтом.
    d.pop("svg_path_d", None)
    d.pop("svg_circles", None)
    return d
