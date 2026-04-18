"""FastAPI-приложение gerber2dxf."""

from __future__ import annotations

import logging
import os
import tempfile
import traceback
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException, UploadFile, File, Body, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from gerber2dxf.web.layer_service import (
    ExportSettings,
    ProjectStore,
    analyze_project,
    export_project,
    layer_info_dict,
    save_uploaded,
)


log = logging.getLogger("gerber2dxf")


def create_app() -> FastAPI:
    base_dir = Path(os.environ.get("GERBER2DXF_WORKDIR", Path(tempfile.gettempdir()) / "gerber2dxf"))
    store = ProjectStore(base_dir)

    app = FastAPI(title="gerber2dxf", version="0.2.0")

    static_dir = Path(__file__).parent / "static"
    if not static_dir.is_dir():
        raise RuntimeError(f"static directory not found: {static_dir}")

    @app.exception_handler(KeyError)
    async def _key_error(_req: Request, exc: KeyError) -> JSONResponse:  # noqa: ARG001
        return JSONResponse({"detail": f"not found: {exc}"}, status_code=404)

    @app.exception_handler(Exception)
    async def _any_error(_req: Request, exc: Exception) -> JSONResponse:  # noqa: ARG001
        tb = traceback.format_exc()
        log.error("unhandled: %s\n%s", exc, tb)
        return JSONResponse(
            {"detail": f"{type(exc).__name__}: {exc}", "trace": tb},
            status_code=500,
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(static_dir / "index.html"))

    @app.post("/api/project")
    def create_project() -> dict:
        proj = store.create()
        return {"project_id": proj.id}

    @app.delete("/api/project/{pid}")
    def delete_project(pid: str) -> dict:
        store.delete(pid)
        return {"ok": True}

    @app.post("/api/project/{pid}/upload")
    async def upload(pid: str, files: List[UploadFile] = File(...)) -> dict:
        proj = store.get(pid)
        total_saved: list[str] = []
        for f in files:
            data = await f.read()
            saved = save_uploaded(proj, f.filename or "upload.bin", data)
            total_saved.extend(p.name for p in saved)
        analyze_project(proj)
        return {
            "project_id": pid,
            "project_name": proj.project_name,
            "uploaded": total_saved,
            "layers": [layer_info_dict(l) for l in proj.layers],
            "bbox": proj.bbox(),
        }

    @app.post("/api/project/{pid}/open-folder")
    def open_folder(pid: str, payload: dict = Body(...)) -> dict:
        """Импорт из локальной папки — удобно при запуске на том же ПК."""
        folder = payload.get("path")
        if not folder:
            raise HTTPException(400, "path is required")
        src = Path(folder).expanduser()
        if not src.exists() or not src.is_dir():
            raise HTTPException(400, f"Папка не найдена: {folder}")
        proj = store.get(pid)
        from gerber2dxf.web.layer_service import accept_extension
        saved: list[str] = []
        for p in sorted(src.iterdir()):
            if p.is_file() and accept_extension(p.name):
                data = p.read_bytes()
                result = save_uploaded(proj, p.name, data)
                saved.extend(x.name for x in result)
        # если имя проекта = имя папки, пробрасываем
        analyze_project(proj)
        if src.name and src.name != "inputs":
            proj.project_name = src.name
        return {
            "project_id": pid,
            "project_name": proj.project_name,
            "uploaded": saved,
            "layers": [layer_info_dict(l) for l in proj.layers],
            "bbox": proj.bbox(),
        }

    @app.get("/api/project/{pid}/layer/{lid}/svg")
    def layer_svg(pid: str, lid: str) -> Response:
        proj = store.get(pid)
        lay = next((l for l in proj.layers if l.id == lid), None)
        if not lay:
            raise HTTPException(404, "Layer not found")
        body = {
            "id": lay.id,
            "is_drill": lay.is_drill,
            "color": lay.color,
            "path_d": lay.svg_path_d or "",
            "circles": lay.svg_circles or "",
            "bbox": [lay.min_x, lay.min_y, lay.max_x, lay.max_y],
            "error": lay.error,
        }
        return JSONResponse(body)

    @app.post("/api/project/{pid}/export")
    def export(pid: str, payload: dict = Body(...)) -> FileResponse:
        proj = store.get(pid)
        layer_ids = payload.get("layer_ids") or [l.id for l in proj.layers]
        settings = ExportSettings(
            flip_y=bool(payload.get("flip_y", False)),
            scale=float(payload.get("scale", 1.0)),
            translate_x=float(payload.get("translate_x", 0.0)),
            translate_y=float(payload.get("translate_y", 0.0)),
            merge_into_single_dxf=bool(payload.get("merge", False)),
            filename_prefix=payload.get("prefix") or None,
        )
        out_path = export_project(proj, layer_ids, settings)
        return FileResponse(str(out_path), filename=out_path.name)

    @app.post("/api/project/{pid}/dxf-preview")
    def dxf_preview(pid: str, payload: dict = Body(...)) -> Response:
        """Рендерит финальный DXF (один или несколько слоёв) в SVG.

        Если передан `layer_ids` (список) — кладёт их в один DXF со слоями AutoCAD
        и рендерит целиком. Это основной режим просмотра («DXF» во вкладке viewport'а).
        Поле `layer_id` поддерживается для обратной совместимости.
        """
        proj = store.get(pid)
        layer_ids = payload.get("layer_ids")
        if not layer_ids:
            single = payload.get("layer_id")
            if not single:
                raise HTTPException(400, "layer_id(s) required")
            layer_ids = [single]
        if not isinstance(layer_ids, list) or not all(isinstance(x, str) for x in layer_ids):
            raise HTTPException(400, "layer_ids must be a list[str]")
        # Все слои в одном DXF — это именно то, что увидит фрезер.
        # Для одного слоя тоже используем merge, чтобы упростить выгрузку (всегда .dxf, не .zip).
        settings = ExportSettings(
            flip_y=bool(payload.get("flip_y", False)),
            scale=float(payload.get("scale", 1.0)),
            translate_x=float(payload.get("translate_x", 0.0)),
            translate_y=float(payload.get("translate_y", 0.0)),
            merge_into_single_dxf=True,
        )
        tmp_path = export_project(proj, layer_ids, settings)
        # если вернулся ZIP, извлекаем первый DXF
        import zipfile
        if tmp_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(tmp_path) as zf:
                name = next((n for n in zf.namelist() if n.lower().endswith(".dxf")), None)
                if not name:
                    raise HTTPException(500, "DXF not produced")
                extracted = proj.root / "outputs" / name
                with zf.open(name) as src, open(extracted, "wb") as dst:
                    import shutil
                    shutil.copyfileobj(src, dst)
                tmp_path = extracted
        from gerber2dxf.dxf_render import render_dxf_to_svg_string
        svg = render_dxf_to_svg_string(tmp_path)
        return Response(svg, media_type="image/svg+xml")

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


app = create_app()
