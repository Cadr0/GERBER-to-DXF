"""DXF -> SVG через ezdxf.addons.drawing (matplotlib)."""

from __future__ import annotations

import io
from pathlib import Path


def render_dxf_to_svg(dxf_path: Path, svg_path: Path, *, size_inches: tuple[float, float] = (10, 8)) -> None:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    fig, ax = plt.subplots(figsize=size_inches)
    ax.set_axis_off()
    ax.set_aspect("equal")
    try:
        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        Frontend(ctx, backend).draw_layout(msp, finalize=True)
    except Exception:
        plt.close(fig)
        raise
    fig.tight_layout(pad=0)
    fig.savefig(svg_path, format="svg", bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def render_dxf_to_svg_string(dxf_path: Path) -> str:
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    import matplotlib
    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    doc = ezdxf.readfile(str(dxf_path))
    msp = doc.modelspace()

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_axis_off()
    ax.set_aspect("equal")
    # Белый фон — контрастно и для печатных цветов (ACI), и для просмотра в браузере.
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    try:
        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        Frontend(ctx, backend).draw_layout(msp, finalize=True)
    except Exception:
        plt.close(fig)
        raise
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", pad_inches=0.02,
                facecolor="white")
    plt.close(fig)
    svg = buf.getvalue()
    # Уберём жёсткие width/height, чтобы SVG масштабировался контейнером.
    # Оставим viewBox — он задаёт внутреннюю систему координат.
    import re
    svg = re.sub(r'(<svg[^>]*?)\s(?:width|height)="[^"]+"', r'\1', svg, count=2)
    return svg
