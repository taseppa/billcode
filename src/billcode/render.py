"""Render the virtual barcode as a scannable Bank Bar Code (Code 128, set C).

Per Finance Finland's Bank Bar Code Guide v5.3, section 6: Code 128 character
set C only, fixed Start C, no set changes; bars 70-105 mm wide (105 preferred),
10-12.7 mm tall; 20 mm quiet zones left and right.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from barcode.charsets.code128 import CODES, START_CODES, STOP

from .barcode import code128_check_digit, decode

BARS_MM = 105.0  # width of the bars, left edge to right edge
HEIGHT_MM = 12.0
QUIET_MM = 20.0
MARGIN_MM = 2.0  # top/bottom padding


def modules(code: str) -> str:
    """The symbol as a string of '1' (bar) and '0' (space) modules."""
    decode(code)  # validate: only well-formed bank barcodes get rendered
    values = [START_CODES["C"]] + [int(code[i : i + 2]) for i in range(0, len(code), 2)]
    values.append(code128_check_digit(code))
    return "".join(CODES[v] for v in values) + STOP + "11"


def _runs(mods: str):
    """Yield (start, width) of each bar."""
    i = 0
    while i < len(mods):
        if mods[i] == "1":
            j = i
            while j < len(mods) and mods[j] == "1":
                j += 1
            yield i, j - i
            i = j
        else:
            i += 1


def to_svg(code: str) -> str:
    mods = modules(code)
    m = BARS_MM / len(mods)  # module width in mm (~0.32 mm)
    w, h = BARS_MM + 2 * QUIET_MM, HEIGHT_MM + 2 * MARGIN_MM
    bars = "".join(
        f'<rect x="{QUIET_MM + s * m:.4f}" y="{MARGIN_MM}" width="{n * m:.4f}" height="{HEIGHT_MM}"/>'
        for s, n in _runs(mods)
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}" '
        f'shape-rendering="crispEdges"><title>{code}</title>'
        f'<rect width="{w}" height="{h}" fill="#fff"/><g fill="#000">{bars}</g></svg>\n'
    )


def to_png(code: str, module_px: int = 4) -> bytes:
    """A 1-bit PNG, crisp at any integer module size (default 4 px per module)."""
    mods = modules(code)
    quiet = round(len(mods) * QUIET_MM / BARS_MM)
    height = round(len(mods) * HEIGHT_MM / BARS_MM)
    margin = round(len(mods) * MARGIN_MM / BARS_MM)
    row_mods = "0" * quiet + mods + "0" * quiet
    # PNG grayscale 1-bit: 1 = white, 0 = black
    bits = "".join("0" if c == "1" else "1" for c in row_mods for _ in range(module_px))
    bits += "1" * (-len(bits) % 8)
    bar_row = b"\x00" + int(bits, 2).to_bytes(len(bits) // 8, "big")
    white_row = b"\x00" + b"\xff" * (len(bits) // 8)
    rows = [white_row] * (margin * module_px) + [bar_row] * (height * module_px)
    rows += [white_row] * (margin * module_px)
    width_px = len(row_mods) * module_px

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width_px, len(rows), 1, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


def write(code: str, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix.lower() == ".svg":
        path.write_text(to_svg(code))
    elif path.suffix.lower() == ".png":
        path.write_bytes(to_png(code))
    else:
        raise ValueError(f"unsupported image type: {path.suffix} (use .png or .svg)")
    return path
