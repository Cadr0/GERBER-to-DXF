(() => {
  "use strict";

  const state = {
    projectId: null,
    layers: [],             // массив LayerInfo с SVG (кэш)
    visibleIds: new Set(),  // id слоёв, включённых галочкой
    bbox: null,             // [minX, minY, maxX, maxY] в мм
    view: { x: 0, y: 0, w: 100, h: 100 }, // viewBox SVG для Gerber-режима
    mode: "gerber",         // "gerber" | "dxf"
    dxf: {
      zoom: 1, tx: 0, ty: 0,
      dragging: false, lastX: 0, lastY: 0,
      lastKey: "",          // ключ последнего рендера (для дедупа)
      loading: false,
    },
  };

  const svgNS = "http://www.w3.org/2000/svg";
  const $ = (sel) => document.querySelector(sel);

  // ---- helpers ----------------------------------------------------------

  function setStatus(text, kind) {
    const el = $("#status");
    el.textContent = text;
    el.classList.remove("busy", "ok", "err");
    if (kind) el.classList.add(kind);
  }
  let toastTimer = null;
  function toast(text, kind) {
    const el = $("#toast");
    el.textContent = text;
    el.classList.remove("hidden", "ok", "err");
    if (kind) el.classList.add(kind);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 3000);
  }
  function setLoading(on) {
    $("#loading").classList.toggle("hidden", !on);
  }

  async function api(method, url, opts = {}) {
    const res = await fetch(url, {
      method,
      headers: opts.json ? { "Content-Type": "application/json" } : undefined,
      body: opts.json ? JSON.stringify(opts.json) : opts.body,
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`${res.status} ${res.statusText}: ${text}`);
    }
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) return res.json();
    if (ct.includes("image/svg+xml") || ct.startsWith("text/")) return res.text();
    return res.blob();
  }

  async function ensureProject() {
    if (state.projectId) return state.projectId;
    const r = await api("POST", "/api/project");
    state.projectId = r.project_id;
    return state.projectId;
  }

  // ---- upload & analyze -------------------------------------------------

  async function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    await ensureProject();
    setStatus("загрузка…", "busy");
    setLoading(true);
    try {
      const fd = new FormData();
      for (const f of fileList) fd.append("files", f, f.name);
      const r = await api(
        "POST",
        `/api/project/${state.projectId}/upload`,
        { body: fd }
      );
      applyProject(r);
      setStatus("готов", "ok");
    } catch (e) {
      console.error(e);
      toast("Ошибка загрузки: " + e.message, "err");
      setStatus("ошибка", "err");
    } finally {
      setLoading(false);
    }
  }

  async function openLocalFolder(path) {
    if (!path) return;
    await ensureProject();
    setStatus("чтение папки…", "busy");
    setLoading(true);
    try {
      const r = await api(
        "POST",
        `/api/project/${state.projectId}/open-folder`,
        { json: { path } }
      );
      applyProject(r);
      setStatus("готов", "ok");
    } catch (e) {
      console.error(e);
      toast("Не удалось открыть папку: " + e.message, "err");
      setStatus("ошибка", "err");
    } finally {
      setLoading(false);
    }
  }

  function applyProject(r) {
    $("#project-name").textContent = r.project_name || "—";
    if (!$("#prefix").value) $("#prefix").value = r.project_name || "";
    state.layers = r.layers || [];
    // по умолчанию видимы все без ошибок
    state.visibleIds = new Set(state.layers.filter(l => !l.error).map(l => l.id));
    state.bbox = r.bbox || null;
    renderLayerList();
    redrawPreviewAll();
    fitView();
    // новый проект → сбросим кэш DXF и, если вкладка DXF активна, перерендерим
    state.dxf.lastKey = "";
    if (state.mode === "dxf") scheduleDxfRefresh(true);
  }

  // ---- layer list ------------------------------------------------------

  function renderLayerList() {
    const ul = $("#layers-list");
    ul.innerHTML = "";
    for (const lay of state.layers) {
      const li = document.createElement("li");
      if (lay.error) li.classList.add("err");

      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = state.visibleIds.has(lay.id);
      cb.addEventListener("change", () => {
        if (cb.checked) state.visibleIds.add(lay.id);
        else state.visibleIds.delete(lay.id);
        redrawPreviewAll();
        scheduleDxfRefresh();
      });

      const sw = document.createElement("span");
      sw.className = "swatch";
      sw.style.background = "#" + lay.color;

      const name = document.createElement("div");
      name.innerHTML = `<div class="lname" title="${escape(lay.filename)}">${escape(lay.filename)}</div>
        <div class="lmeta">${escape(lay.kind)} · ${escape(lay.units)}${lay.is_drill ? ` · ${lay.drill_count} hit(s)` : ""}${lay.error ? " · ОШИБКА" : ""}</div>`;

      const solo = document.createElement("span");
      solo.className = "solo";
      solo.textContent = "solo";
      solo.title = "Показать только этот слой";
      solo.addEventListener("click", (e) => {
        e.stopPropagation();
        state.visibleIds = new Set([lay.id]);
        renderLayerList();
        redrawPreviewAll();
        scheduleDxfRefresh();
      });

      li.append(cb, sw, name, solo);
      li.addEventListener("click", (e) => {
        if (e.target === cb || e.target === solo) return;
        cb.click();
      });
      ul.appendChild(li);
    }
  }

  function escape(s) {
    return String(s).replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  // ---- preview SVG ------------------------------------------------------

  async function getLayerGeom(id) {
    const lay = state.layers.find(l => l.id === id);
    if (!lay) return null;
    if (lay._svg) return lay._svg;
    try {
      const r = await api("GET", `/api/project/${state.projectId}/layer/${id}/svg`);
      lay._svg = r;
      return r;
    } catch (e) {
      console.warn("svg fetch failed", e);
      return null;
    }
  }

  async function redrawPreviewAll() {
    const svg = $("#preview");
    // Держим текущий viewBox, первую отрисовку делаем после.
    svg.innerHTML = "";
    // Фон плата (прозрачный).
    const bg = document.createElementNS(svgNS, "rect");
    bg.setAttribute("x", "-100000"); bg.setAttribute("y", "-100000");
    bg.setAttribute("width", "200000"); bg.setAttribute("height", "200000");
    bg.setAttribute("fill", "transparent");
    svg.appendChild(bg);

    const visibleLayers = state.layers.filter(l => state.visibleIds.has(l.id) && !l.error);

    // Порядок отрисовки: сначала крупные площади (медь), затем маска/паста, затем шелкография, outline сверху, drill поверх всего
    const order = {
      copper_top: 10, copper_bottom: 10,
      soldermask_top: 20, soldermask_bottom: 20,
      paste_top: 30, paste_bottom: 30,
      silk_top: 40, silk_bottom: 40,
      pads_top: 35, pads_bottom: 35,
      mechanical: 50, document: 50, other: 55,
      outline: 60,
      drill: 70, drill_via: 71, drill_npth: 72,
    };
    visibleLayers.sort((a, b) => (order[a.kind] || 90) - (order[b.kind] || 90));

    // параллельно подгружаем SVG-данные
    const geoms = await Promise.all(visibleLayers.map(l => getLayerGeom(l.id)));

    for (let i = 0; i < visibleLayers.length; i++) {
      const lay = visibleLayers[i];
      const geom = geoms[i];
      if (!geom) continue;
      const g = document.createElementNS(svgNS, "g");
      g.setAttribute("data-layer", lay.id);
      const color = "#" + lay.color;
      if (lay.is_drill) {
        g.innerHTML = geom.circles || "";
        g.setAttribute("fill", "none");
        g.setAttribute("stroke", color);
        g.setAttribute("stroke-width", "0.06");
      } else if (lay.kind === "outline") {
        // контур — рисуем обводкой без заливки, чтобы чётко видеть границу
        const path = document.createElementNS(svgNS, "path");
        path.setAttribute("d", geom.path_d || "");
        path.setAttribute("fill", color);
        path.setAttribute("fill-opacity", "1");
        path.setAttribute("stroke", color);
        path.setAttribute("stroke-width", "0.01");
        path.setAttribute("fill-rule", "evenodd");
        g.appendChild(path);
      } else {
        const path = document.createElementNS(svgNS, "path");
        path.setAttribute("d", geom.path_d || "");
        path.setAttribute("fill", color);
        path.setAttribute("fill-rule", "evenodd");
        path.setAttribute("fill-opacity", opacityFor(lay.kind));
        g.appendChild(path);
      }
      svg.appendChild(g);
    }

    updateViewBoxAttr();
    updateBboxLabel();
  }

  function opacityFor(kind) {
    switch (kind) {
      case "copper_top":
      case "copper_bottom":
      case "pads_top":
      case "pads_bottom":
        return 0.85;
      case "soldermask_top":
      case "soldermask_bottom":
        return 0.45;
      case "paste_top":
      case "paste_bottom":
        return 0.8;
      case "silk_top":
      case "silk_bottom":
        return 0.95;
      default:
        return 0.85;
    }
  }

  function updateBboxLabel() {
    if (!state.bbox) { $("#bbox-info").textContent = ""; return; }
    const [a, b, c, d] = state.bbox;
    const w = (c - a).toFixed(2);
    const h = (d - b).toFixed(2);
    $("#bbox-info").textContent = `BBox: ${w} × ${h} mm`;
  }

  // ---- pan / zoom -------------------------------------------------------

  function fitView() {
    const svg = $("#preview");
    const vp = $("#viewport");
    const rect = vp.getBoundingClientRect();
    if (!state.bbox) {
      state.view = { x: -50, y: -50, w: 100, h: 100 };
    } else {
      const [minX, minY, maxX, maxY] = state.bbox;
      // в SVG мы инвертировали Y: мировой Y становится -Y в SVG
      const sx = minX, sy = -maxY;
      const sw = maxX - minX;
      const sh = maxY - minY;
      const padX = sw * 0.06 || 5;
      const padY = sh * 0.06 || 5;
      // подогнать под соотношение сторон окна
      const ar = rect.width / rect.height;
      let w = sw + padX * 2;
      let h = sh + padY * 2;
      if (w / h < ar) {
        const nw = h * ar;
        state.view = { x: sx - (nw - sw) / 2, y: sy - padY, w: nw, h };
      } else {
        const nh = w / ar;
        state.view = { x: sx - padX, y: sy - (nh - sh) / 2, w, h: nh };
      }
    }
    updateViewBoxAttr();
  }

  function updateViewBoxAttr() {
    const svg = $("#preview");
    const v = state.view;
    svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  }

  function screenToWorld(clientX, clientY) {
    const svg = $("#preview");
    const rect = svg.getBoundingClientRect();
    const v = state.view;
    // compute the fitted transform (preserveAspectRatio = meet)
    const ar = rect.width / rect.height;
    const vAr = v.w / v.h;
    let w, h, x, y;
    if (vAr > ar) {
      w = v.w; h = v.w / ar;
      x = v.x; y = v.y - (h - v.h) / 2;
    } else {
      h = v.h; w = v.h * ar;
      x = v.x - (w - v.w) / 2; y = v.y;
    }
    const nx = (clientX - rect.left) / rect.width;
    const ny = (clientY - rect.top) / rect.height;
    return { x: x + nx * w, y: y + ny * h };
  }

  function bindPanZoom() {
    const svg = $("#preview");
    let dragging = false; let lastX = 0; let lastY = 0;
    svg.addEventListener("mousedown", (e) => {
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      svg.classList.add("dragging");
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
      svg.classList.remove("dragging");
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) {
        if (state.mode !== "gerber") { $("#cursor-xy").textContent = ""; return; }
        const w = screenToWorld(e.clientX, e.clientY);
        // отобразим мировые X, -Y (реальные мировые координаты платы)
        $("#cursor-xy").textContent = `${w.x.toFixed(3)} , ${(-w.y).toFixed(3)} mm`;
        return;
      }
      if (state.mode !== "gerber") return;
      const rect = svg.getBoundingClientRect();
      const dx = (e.clientX - lastX) / rect.width;
      const dy = (e.clientY - lastY) / rect.height;
      lastX = e.clientX; lastY = e.clientY;
      state.view.x -= dx * state.view.w;
      state.view.y -= dy * state.view.h;
      updateViewBoxAttr();
    });

    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 1.15 : 1 / 1.15;
      const w = screenToWorld(e.clientX, e.clientY);
      state.view.x = w.x - (w.x - state.view.x) * factor;
      state.view.y = w.y - (w.y - state.view.y) * factor;
      state.view.w *= factor;
      state.view.h *= factor;
      updateViewBoxAttr();
    }, { passive: false });
  }

  function bindDropzone() {
    const dz = $("#dropzone");
    ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, (e) => {
      e.preventDefault(); e.stopPropagation();
      dz.classList.add("dragover");
    }));
    ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, (e) => {
      e.preventDefault(); e.stopPropagation();
      dz.classList.remove("dragover");
    }));
    dz.addEventListener("drop", async (e) => {
      const items = e.dataTransfer?.items;
      if (items && items.length && items[0].webkitGetAsEntry) {
        const files = await collectEntries(items);
        await uploadFiles(files);
      } else {
        await uploadFiles(Array.from(e.dataTransfer.files || []));
      }
    });
    $("#file-input").addEventListener("change", async (e) => {
      await uploadFiles(Array.from(e.target.files || []));
      e.target.value = "";
    });
    $("#pick-folder-btn").addEventListener("click", () => {
      const inp = document.createElement("input");
      inp.type = "file"; inp.webkitdirectory = true; inp.multiple = true;
      inp.addEventListener("change", async () => {
        await uploadFiles(Array.from(inp.files || []));
      });
      inp.click();
    });
    $("#folder-load-btn").addEventListener("click", () => {
      openLocalFolder($("#folder-path").value.trim());
    });
  }

  async function collectEntries(items) {
    const out = [];
    const promises = [];
    for (const it of items) {
      const entry = it.webkitGetAsEntry?.();
      if (!entry) continue;
      promises.push(walkEntry(entry, out));
    }
    await Promise.all(promises);
    return out;
  }
  function walkEntry(entry, acc) {
    return new Promise((resolve) => {
      if (entry.isFile) {
        entry.file((f) => { acc.push(f); resolve(); }, () => resolve());
      } else if (entry.isDirectory) {
        const reader = entry.createReader();
        const readAll = () => {
          reader.readEntries(async (ents) => {
            if (!ents.length) return resolve();
            await Promise.all(ents.map(e => walkEntry(e, acc)));
            readAll();
          }, () => resolve());
        };
        readAll();
      } else resolve();
    });
  }

  // ---- export & viewer --------------------------------------------------

  async function doExport() {
    if (!state.projectId || !state.layers.length) {
      toast("Сначала загрузите Gerber/Excellon.", "err");
      return;
    }
    const selected = state.layers.filter(l => state.visibleIds.has(l.id) && !l.error).map(l => l.id);
    if (!selected.length) {
      toast("Выберите хотя бы один слой.", "err");
      return;
    }
    const payload = {
      layer_ids: selected,
      flip_y: $("#flip-y").checked,
      scale: parseFloat($("#scale").value) || 1,
      translate_x: parseFloat($("#tx").value) || 0,
      translate_y: parseFloat($("#ty").value) || 0,
      merge: $("#merge").checked,
      prefix: $("#prefix").value.trim() || undefined,
    };
    setStatus("экспорт…", "busy");
    setLoading(true);
    try {
      const res = await fetch(`/api/project/${state.projectId}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await res.text());
      const cd = res.headers.get("content-disposition") || "";
      const m = /filename="?([^"]+)"?/.exec(cd);
      const filename = m ? m[1] : "export.bin";
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = filename;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
      toast("Экспорт готов: " + filename, "ok");
      setStatus("готов", "ok");
    } catch (e) {
      console.error(e);
      toast("Ошибка экспорта: " + e.message, "err");
      setStatus("ошибка", "err");
    } finally {
      setLoading(false);
    }
  }

  // ---- DXF inline viewer (вкладка "DXF" в главном окне) ---------------

  /**
   * Ключ, по которому определяем, нужно ли перерендеривать DXF:
   * состав видимых слоёв + параметры экспорта.
   */
  function dxfKey() {
    const ids = [...state.visibleIds].sort().join(",");
    return [
      ids,
      $("#flip-y").checked ? "1" : "0",
      $("#scale").value || "1",
      $("#tx").value || "0",
      $("#ty").value || "0",
    ].join("|");
  }

  async function fetchDxfSvgMulti(layerIds) {
    const payload = {
      layer_ids: layerIds,
      flip_y: $("#flip-y").checked,
      scale: parseFloat($("#scale").value) || 1,
      translate_x: parseFloat($("#tx").value) || 0,
      translate_y: parseFloat($("#ty").value) || 0,
    };
    const res = await fetch(`/api/project/${state.projectId}/dxf-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(await res.text());
    return res.text();
  }

  function applyDxfTransform() {
    const host = $("#preview-dxf");
    const svg = host.querySelector("svg");
    if (!svg) return;
    const d = state.dxf;
    svg.style.transform = `translate(${d.tx}px, ${d.ty}px) scale(${d.zoom})`;
  }

  function resetDxfTransform() {
    state.dxf.zoom = 1;
    state.dxf.tx = 0;
    state.dxf.ty = 0;
    applyDxfTransform();
  }

  function dxfZoomAt(factor, cx, cy) {
    const host = $("#preview-dxf");
    const rect = host.getBoundingClientRect();
    const x = (cx ?? rect.left + rect.width / 2) - rect.left;
    const y = (cy ?? rect.top + rect.height / 2) - rect.top;
    const d = state.dxf;
    const nz = Math.max(0.1, Math.min(40, d.zoom * factor));
    const wx = (x - d.tx) / d.zoom;
    const wy = (y - d.ty) / d.zoom;
    d.zoom = nz;
    d.tx = x - wx * nz;
    d.ty = y - wy * nz;
    applyDxfTransform();
  }

  async function renderDxfInline(force) {
    if (!state.projectId || !state.layers.length) return;
    const visible = [...state.visibleIds];
    if (!visible.length) {
      $("#preview-dxf").innerHTML = `<div class="dxf-empty">Выберите слои слева — они появятся здесь в виде итогового DXF.</div>`;
      state.dxf.lastKey = "";
      return;
    }
    const key = dxfKey();
    if (!force && key === state.dxf.lastKey) return;
    const host = $("#preview-dxf");
    state.dxf.loading = true;
    setLoading(true);
    try {
      const svg = await fetchDxfSvgMulti(visible);
      host.innerHTML = svg;
      const svgEl = host.querySelector("svg");
      if (svgEl) {
        svgEl.removeAttribute("width");
        svgEl.removeAttribute("height");
        svgEl.setAttribute("preserveAspectRatio", "xMidYMid meet");
      }
      resetDxfTransform();
      state.dxf.lastKey = key;
    } catch (e) {
      console.error(e);
      host.innerHTML = `<div class="dxf-empty">Ошибка рендера DXF: ${escape(e.message)}</div>`;
    } finally {
      state.dxf.loading = false;
      setLoading(false);
    }
  }

  let dxfDebounce = null;
  /**
   * Ставит перерендер DXF — с небольшой задержкой, чтобы «быстрые» клики
   * по чекбоксам/инпутам не запускали N рендеров подряд.
   * Работает только когда активна вкладка DXF.
   */
  function scheduleDxfRefresh(force = false) {
    if (state.mode !== "dxf") return;
    clearTimeout(dxfDebounce);
    dxfDebounce = setTimeout(() => renderDxfInline(force), 250);
  }

  // ---- tab switching ---------------------------------------------------

  function switchTab(name) {
    if (name !== "gerber" && name !== "dxf") return;
    state.mode = name;
    document.querySelectorAll(".tab").forEach(t => {
      const active = t.dataset.tab === name;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
    });
    const isDxf = name === "dxf";
    $("#preview").classList.toggle("hidden", isDxf);
    $("#preview-dxf").classList.toggle("hidden", !isDxf);
    $("#dxf-refresh").classList.toggle("hidden", !isDxf);
    if (isDxf) {
      renderDxfInline(false);
    }
  }

  function bindTabs() {
    document.querySelectorAll(".tab").forEach(btn => {
      btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    });
  }

  function bindDxfPanZoom() {
    const host = $("#preview-dxf");
    host.addEventListener("mousedown", (e) => {
      // не тянем, если клик пришёл по пустой сцене без SVG
      if (!host.querySelector("svg")) return;
      state.dxf.dragging = true;
      state.dxf.lastX = e.clientX; state.dxf.lastY = e.clientY;
      host.classList.add("dragging");
    });
    window.addEventListener("mouseup", () => {
      if (state.dxf.dragging) {
        state.dxf.dragging = false;
        host.classList.remove("dragging");
      }
    });
    window.addEventListener("mousemove", (e) => {
      if (!state.dxf.dragging) return;
      state.dxf.tx += e.clientX - state.dxf.lastX;
      state.dxf.ty += e.clientY - state.dxf.lastY;
      state.dxf.lastX = e.clientX; state.dxf.lastY = e.clientY;
      applyDxfTransform();
    });
    host.addEventListener("wheel", (e) => {
      if (state.mode !== "dxf") return;
      e.preventDefault();
      const factor = e.deltaY > 0 ? 1 / 1.15 : 1.15;
      dxfZoomAt(factor, e.clientX, e.clientY);
    }, { passive: false });
  }

  // ---- init -------------------------------------------------------------

  function bindAll() {
    bindDropzone();
    bindPanZoom();
    bindTabs();
    bindDxfPanZoom();
    $("#zoom-fit").addEventListener("click", () => {
      if (state.mode === "dxf") resetDxfTransform();
      else fitView();
    });
    $("#zoom-in").addEventListener("click", () => {
      if (state.mode === "dxf") dxfZoomAt(1.3);
      else zoomAtCenter(1 / 1.3);
    });
    $("#zoom-out").addEventListener("click", () => {
      if (state.mode === "dxf") dxfZoomAt(1 / 1.3);
      else zoomAtCenter(1.3);
    });
    $("#dxf-refresh").addEventListener("click", () => renderDxfInline(true));
    $("#all-on").addEventListener("click", () => {
      state.visibleIds = new Set(state.layers.filter(l => !l.error).map(l => l.id));
      renderLayerList(); redrawPreviewAll();
      scheduleDxfRefresh();
    });
    $("#all-off").addEventListener("click", () => {
      state.visibleIds = new Set();
      renderLayerList(); redrawPreviewAll();
      scheduleDxfRefresh();
    });
    $("#export-btn").addEventListener("click", doExport);
    // любое изменение параметров экспорта — обновим DXF-вкладку
    ["#flip-y", "#scale", "#tx", "#ty"].forEach(sel => {
      $(sel).addEventListener("change", () => scheduleDxfRefresh());
      $(sel).addEventListener("input", () => scheduleDxfRefresh());
    });
    window.addEventListener("resize", updateViewBoxAttr);
  }
  function zoomAtCenter(factor) {
    const svg = $("#preview");
    const r = svg.getBoundingClientRect();
    const w = screenToWorld(r.left + r.width / 2, r.top + r.height / 2);
    state.view.x = w.x - (w.x - state.view.x) * factor;
    state.view.y = w.y - (w.y - state.view.y) * factor;
    state.view.w *= factor; state.view.h *= factor;
    updateViewBoxAttr();
  }

  bindAll();
  fitView();
})();
