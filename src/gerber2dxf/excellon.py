"""Парсер Excellon (KiCad / EasyEDA / Altium / Eagle).

Поддерживает:
- комментарий `;FILE_FORMAT=m:n`
- заголовок `METRIC,LZ,000.000` / `INCH,LZ,00.0000` (формат выводится из кол-ва точек)
- `M71`/`M72` (METRIC/INCH), `INCH`/`METRIC`
- `LZ`/`TZ` (вкл. trailing/leading zero)
- определения инструментов `T<nn>C<diameter>`
- выбор инструмента `T<nn>`
- координаты `X<...>Y<...>` с/без десятичной точки
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class DrillUnits(str, Enum):
    MM = "MM"
    INCH = "INCH"


class ZeroMode(str, Enum):
    LEADING_OMITTED = "LZ"   # leading zeros omitted (исторически в LZ: trailing keep)
    TRAILING_OMITTED = "TZ"  # trailing zeros omitted


@dataclass
class ExcellonParseResult:
    units: DrillUnits = DrillUnits.MM
    integer_digits: int = 3
    decimal_digits: int = 3
    zero_mode: ZeroMode = ZeroMode.LEADING_OMITTED
    tools: dict[int, float] = field(default_factory=dict)
    hits: list[tuple[float, float, int]] = field(default_factory=list)


_RE_TOOL_DEF = re.compile(r"T0*(\d+)C([-+]?\d*\.?\d+)", re.IGNORECASE)
_RE_TOOL_LINE = re.compile(r"^T0*(\d+)\s*\*?\s*$", re.IGNORECASE)
_RE_XY_FLOAT = re.compile(r"X([-+]?\d*\.\d+)\s*Y([-+]?\d*\.\d+)", re.IGNORECASE)
_RE_XY_INT = re.compile(r"X([-+]?\d+)\s*Y([-+]?\d+)", re.IGNORECASE)
_RE_FILE_FORMAT = re.compile(r"FILE[_ ]?FORMAT\s*=\s*(\d+)\s*:\s*(\d+)", re.IGNORECASE)
_RE_UNITS_FORMAT = re.compile(
    r"\b(METRIC|INCH)\s*,\s*(LZ|TZ)?\s*,?\s*(\d+)\.(\d+)", re.IGNORECASE
)
_RE_UNITS_SIMPLE = re.compile(r"\b(METRIC|INCH)\b", re.IGNORECASE)
_RE_LZ_TZ = re.compile(r"\b(LZ|TZ)\b", re.IGNORECASE)


def _int_to_mm(
    raw: str,
    integer_digits: int,
    decimal_digits: int,
    zero_mode: ZeroMode,
) -> float:
    sign = 1.0
    s = raw
    if s.startswith("+"):
        s = s[1:]
    elif s.startswith("-"):
        sign = -1.0
        s = s[1:]

    total = integer_digits + decimal_digits
    if zero_mode is ZeroMode.TRAILING_OMITTED:
        s = s.ljust(total, "0")
    # LZ: trailing zeros присутствуют — как есть, просто делим на 10^decimal_digits.
    try:
        value = int(s)
    except ValueError:
        return 0.0
    return sign * value / (10 ** decimal_digits)


def parse_excellon(text: str) -> ExcellonParseResult:
    res = ExcellonParseResult()

    fmt_match = _RE_FILE_FORMAT.search(text)
    header_match = _RE_UNITS_FORMAT.search(text)

    if fmt_match:
        res.integer_digits = int(fmt_match.group(1))
        res.decimal_digits = int(fmt_match.group(2))
    elif header_match:
        res.integer_digits = len(header_match.group(3))
        res.decimal_digits = len(header_match.group(4))

    unit_word = None
    if header_match:
        unit_word = header_match.group(1)
    else:
        m = _RE_UNITS_SIMPLE.search(text)
        if m:
            unit_word = m.group(1)
    if unit_word:
        res.units = DrillUnits.MM if unit_word.upper() == "METRIC" else DrillUnits.INCH

    zm_match = _RE_LZ_TZ.search(text)
    if zm_match:
        res.zero_mode = (
            ZeroMode.LEADING_OMITTED if zm_match.group(1).upper() == "LZ" else ZeroMode.TRAILING_OMITTED
        )

    if "M71" in text.upper():
        res.units = DrillUnits.MM
    elif "M72" in text.upper():
        res.units = DrillUnits.INCH

    for m in _RE_TOOL_DEF.finditer(text):
        res.tools[int(m.group(1))] = float(m.group(2))

    has_percent = "%" in text
    after_header = not ("M48" in text.upper() and has_percent)

    current_tool: int | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip().rstrip("*").strip()
        if not line or line.startswith(";"):
            continue
        if line == "%":
            after_header = True
            continue
        if not after_header:
            continue

        if re.match(r"^(M\d+|G\d+)", line, re.IGNORECASE):
            continue

        if _RE_TOOL_DEF.fullmatch(line):
            continue

        tm = _RE_TOOL_LINE.match(line)
        if tm:
            current_tool = int(tm.group(1))
            continue

        fm = _RE_XY_FLOAT.search(line)
        if fm:
            x, y = float(fm.group(1)), float(fm.group(2))
            if current_tool is not None:
                res.hits.append((x, y, current_tool))
            continue

        im = _RE_XY_INT.search(line)
        if im:
            x = _int_to_mm(im.group(1), res.integer_digits, res.decimal_digits, res.zero_mode)
            y = _int_to_mm(im.group(2), res.integer_digits, res.decimal_digits, res.zero_mode)
            if current_tool is not None:
                res.hits.append((x, y, current_tool))

    return res


@dataclass
class DrillHit:
    x: float
    y: float
    diameter: float
    tool: int


def read_drill_file(path: Path) -> tuple[list[DrillHit], DrillUnits]:
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_excellon(text)

    out: list[DrillHit] = []
    for x, y, tool in parsed.hits:
        dia = parsed.tools.get(tool, 0.0)
        if parsed.units is DrillUnits.INCH:
            # пользователю вернём в файле DXF те же единицы, но для bbox удобнее
            # хранить всё в мм; оставим значения и передадим единицы отдельно.
            pass
        out.append(DrillHit(x=x, y=y, diameter=dia, tool=tool))
    return out, parsed.units


def is_probably_excellon(path: Path) -> bool:
    if path.suffix.lower() not in {".drl", ".txt", ".exc", ".xln"}:
        return False
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:8192]
    except OSError:
        return False
    hu = head.upper()
    if "M48" in hu:
        return True
    if _RE_TOOL_DEF.search(head) and re.search(r"\bX[-+]?\d", head, re.IGNORECASE):
        return True
    return False
