"""Show the bank barcode and payment QR code inside the terminal.

Uses the kitty graphics protocol (kitty, Ghostty) or the iTerm2 inline image
protocol (iTerm2, WezTerm) when available; otherwise draws the bars with
Unicode half blocks, which needs a wide window (~176 columns).
"""

from __future__ import annotations

import base64
import fcntl
import os
import struct
import sys
import termios
from typing import TextIO

from . import qr
from .render import modules, to_png

QUIET_MODULES = 10  # Code 128 minimum quiet zone, used for the text fallback


def detect(stream: TextIO = sys.stdout) -> str | None:
    """'kitty', 'iterm', 'blocks', or None when not writing to a terminal."""
    if not stream.isatty():
        return None
    env = os.environ
    if env.get("TMUX"):
        return "blocks"  # image protocols need passthrough config inside tmux
    if "kitty" in env.get("TERM", "") or env.get("KITTY_WINDOW_ID") or env.get("GHOSTTY_RESOURCES_DIR"):
        return "kitty"
    if env.get("TERM_PROGRAM") in ("iTerm.app", "WezTerm") or env.get("LC_TERMINAL") == "iTerm2":
        return "iterm"
    return "blocks"


def _window_size(stream: TextIO) -> tuple[int, int]:
    """(columns, width in pixels); pixels is 0 if the terminal doesn't report it."""
    try:
        _, cols, xpix, _ = struct.unpack("HHHH", fcntl.ioctl(stream.fileno(), termios.TIOCGWINSZ, b"\0" * 8))
        return cols, xpix
    except OSError:
        return 80, 0


def _png_for_width(code: str, xpix: int) -> tuple[bytes, bool]:
    """PNG with the biggest whole-pixel module that fits; (png, needs_scaling)."""
    probe = to_png(code, module_px=1)
    width_1px = struct.unpack(">I", probe[16:20])[0]
    if xpix <= 0:
        return to_png(code, module_px=3), True
    module_px = xpix // width_1px
    if module_px < 1:
        return to_png(code, module_px=2), True
    return to_png(code, module_px=min(module_px, 4)), False


def _kitty(png: bytes, cols: int | None) -> str:
    data = base64.standard_b64encode(png).decode()
    chunks = [data[i : i + 4096] for i in range(0, len(data), 4096)]
    first = "a=T,f=100,q=2" + (f",c={cols}" if cols else "")
    out = []
    for i, chunk in enumerate(chunks):
        more = 1 if i < len(chunks) - 1 else 0
        keys = f"{first},m={more}" if i == 0 else f"m={more}"
        out.append(f"\x1b_G{keys};{chunk}\x1b\\")
    return "".join(out) + "\n"


def _iterm(png: bytes, full_width: bool) -> str:
    data = base64.b64encode(png).decode()
    size = "width=100%;" if full_width else ""
    return f"\x1b]1337;File=inline=1;size={len(png)};{size}preserveAspectRatio=1:{data}\x07\n"


def kitty_sequence(code: str, cols: int = 80, xpix: int = 0) -> str:
    png, scale = _png_for_width(code, xpix)
    return _kitty(png, cols if scale else None)


def iterm_sequence(code: str, cols: int = 80, xpix: int = 0) -> str:
    png, scale = _png_for_width(code, xpix)
    return _iterm(png, scale)


def blocks(code: str, rows: int = 4) -> list[str]:
    """Bars drawn with half blocks (2 modules per column), black on white."""
    mods = "0" * QUIET_MODULES + modules(code) + "0" * QUIET_MODULES
    mods += "0" * (len(mods) % 2)
    glyph = {"11": "█", "10": "▌", "01": "▐", "00": " "}
    line = "".join(glyph[mods[i : i + 2]] for i in range(0, len(mods), 2))
    return [" " * len(line)] + [line] * rows + [" " * len(line)]


def qr_blocks(payload: str, border: int = 4) -> list[str]:
    """QR code drawn with half blocks (2 module rows per text row), black on white."""
    m = qr.matrix(payload)
    size = len(m) + 2 * border
    rows = [[False] * size for _ in range(border)]
    rows += [[False] * border + r + [False] * border for r in m]
    rows += [[False] * size for _ in range(border + (size % 2))]
    glyph = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}
    return ["".join(glyph[(a, b)] for a, b in zip(rows[i], rows[i + 1])) for i in range(0, len(rows), 2)]


def _write_blocks(lines: list[str], stream: TextIO) -> None:
    on_white = "\x1b[38;2;0;0;0;48;2;255;255;255m"
    for line in lines:
        stream.write(f"{on_white}{line}\x1b[0m\n")


def show(code: str, stream: TextIO = sys.stdout) -> str | None:
    """Draw the barcode in the terminal. Returns a message if it could not."""
    kind = detect(stream)
    if kind is None:
        return None
    cols, xpix = _window_size(stream)
    if kind == "kitty":
        stream.write(kitty_sequence(code, cols, xpix))
    elif kind == "iterm":
        stream.write(iterm_sequence(code, cols, xpix))
    else:
        lines = blocks(code)
        if len(lines[0]) > cols:
            return f"terminal too narrow to draw the barcode ({len(lines[0])} columns needed); try --open"
        _write_blocks(lines, stream)
    stream.flush()
    return None


def show_qr(payload: str, stream: TextIO = sys.stdout) -> str | None:
    """Draw the payment QR code in the terminal. Returns a message if it could not."""
    kind = detect(stream)
    if kind is None:
        return None
    cols, _ = _window_size(stream)
    if kind in ("kitty", "iterm"):
        png = qr.to_png(payload, scale=6)
        stream.write(_kitty(png, None) if kind == "kitty" else _iterm(png, False))
    else:
        lines = qr_blocks(payload)
        if len(lines[0]) > cols:
            return f"terminal too narrow to draw the QR code ({len(lines[0])} columns needed); try --open"
        _write_blocks(lines, stream)
    stream.flush()
    return None
