# gerber2dxf

Локальное веб-приложение для конвертации **Gerber / Excellon → DXF** для фрезеровки.

Перетащили файлы → видите предпросмотр слоёв → выбираете нужные → переключаетесь на вкладку **DXF**, чтобы увидеть точно тот DXF, который будет экспортирован → нажимаете «Экспорт DXF».

![workflow](docs/workflow.png)
<!-- скриншот опционален; файл можно не добавлять — README просто не покажет картинку -->

## Быстрый запуск (Windows)

1. Установите **Python 3.10+** с [python.org](https://www.python.org/downloads/). При установке отметьте **«Add Python to PATH»**.
2. Дважды кликните по `run_gerber2dxf.cmd` в корне проекта.
   - Первый запуск сам создаст `.venv`, поставит зависимости (`pygerber[shapely]`, `ezdxf`, `fastapi`, `uvicorn`, `shapely`, `matplotlib` и т. д.) и поднимет сервер на `http://127.0.0.1:8765`.
   - Откроется браузер с интерфейсом.
3. Для диагностики проблем запуска — `diagnose.cmd`.

## Что умеет

- **Загрузка**: drag-and-drop файлов/папки, кнопки «Файлы…» / «Папка…», либо путь к локальной папке.
- **Автодетекция слоёв** по расширению и атрибутам Gerber X2/X3: медь top/bottom, маска, паста, шелкография, контур (outline), сверловка PTH / VIA / NPTH, документ, механика.
- **Две вкладки в одном окне просмотра**:
  - **Gerber** — суперпозиция всех выбранных слоёв в одном SVG, каждый своим цветом.
  - **DXF** — полный рендер итогового DXF (через `ezdxf` + `matplotlib`), с теми же pan/zoom. Это ровно то, что увидит CAM после экспорта.
  - Pan — ЛКМ, zoom — колесо, кнопки `Fit` / `+` / `−` работают в обоих режимах.
- **Экспорт DXF**:
  - Отдельный DXF на слой (упаковываются в ZIP) или один DXF со слоями AutoCAD — галочка «Один DXF».
  - Параметры: префикс имён, flip Y, масштаб, сдвиг X/Y.
  - Замкнутые `LWPOLYLINE` для контуров, `CIRCLE` с реальным диаметром для сверловки из Excellon.

## Ручной запуск (без `.cmd`)

```powershell
cd gerber2dxf
python -m venv .venv
.venv\Scripts\pip install --pre -e .
.venv\Scripts\gerber2dxf-web
```

Либо пакетный CLI без веба:

```powershell
gerber2dxf path\to\Gerber_Folder -o dxf_out
gerber2dxf --web
```

## Архитектура (коротко)

```
src/gerber2dxf/
├── gerber_convert.py    # pygerber → shapely geometry
├── excellon.py          # свой парсер .DRL (metric/inch, LZ/TZ, FILE_FORMAT)
├── naming.py            # классификация слоёв по расширению/атрибутам
├── dxf_export.py        # write_geometry_dxf / write_drill_dxf (ezdxf)
├── dxf_render.py        # ezdxf + matplotlib → SVG для превью
├── svg_build.py         # лёгкий SVG из shapely для Gerber-вкладки
├── cli.py               # пакетный режим (--web тоже тут)
└── web/
    ├── launcher.py      # поднимает uvicorn + открывает браузер
    ├── server.py        # FastAPI endpoints
    ├── layer_service.py # анализ проекта, кэш, экспорт
    └── static/          # index.html, app.js, styles.css
```

## Известные детали

- Медь в DXF — это **плоская область** (залитые дорожки/полигоны с обводкой), не центральная линия. Для изоляционной фрезеровки по оси нужен алгоритм смещения/скелета — в эту версию не включён.
- Excellon: поддерживаются `FILE_FORMAT=m:n`, `METRIC/INCH`, `LZ/TZ`, `M71/M72`, `Tnn C<d>`. Для большинства CAM-систем файл читается без проблем.
- Сервер слушает только `127.0.0.1` — наружу не доступен.
- Для одинаковых `kind` (например, два `.DRL`) все объекты попадают в один AutoCAD-слой (`DRILL`) — в рендере и экспорте это корректно, падения `LAYER already exists` нет.

## Лицензия

MIT — см. [`LICENSE`](LICENSE).
