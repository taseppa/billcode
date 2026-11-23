import base64
import io
import re

import pytest

from billcode import terminal
from billcode.render import modules

zxingcpp = pytest.importorskip("zxingcpp")
Image = pytest.importorskip("PIL.Image")

CODE = "479440520200360820048831500000000868516259619897100612"


def _scan(png: bytes) -> str:
    return zxingcpp.read_barcodes(Image.open(io.BytesIO(png)).convert("L"))[0].text


def test_kitty_sequence_carries_scannable_png():
    seq = terminal.kitty_sequence(CODE, cols=80, xpix=1600)
    chunks = re.findall(r"\x1b_G([^;]*);([^\x1b]*)\x1b\\", seq)
    assert chunks[0][0].startswith("a=T,f=100")
    assert chunks[-1][0].endswith("m=0") and all(k.endswith("m=1") for k, _ in chunks[:-1])
    assert all(len(d) <= 4096 for _, d in chunks)
    assert _scan(base64.b64decode("".join(d for _, d in chunks))) == CODE


def test_kitty_fits_window_pixels():
    seq = terminal.kitty_sequence(CODE, cols=80, xpix=1000)
    png = base64.b64decode("".join(re.findall(r";([^;\x1b]*)\x1b\\", seq)))
    assert png.startswith(b"\x89PNG")
    width = int.from_bytes(png[16:20], "big")
    assert width <= 1000 and ",c=" not in seq  # 1:1 pixels, no blurry scaling


def test_iterm_sequence_carries_scannable_png():
    seq = terminal.iterm_sequence(CODE, xpix=1600)
    data = seq.split(":", 1)[1].split("\x07")[0]
    assert _scan(base64.b64decode(data)) == CODE


def test_blocks_round_trip():
    lines = terminal.blocks(CODE)
    back = {"█": "11", "▌": "10", "▐": "01", " ": "00"}
    mods = "".join(back[c] for c in lines[1])
    q = terminal.QUIET_MODULES
    assert mods[q : q + len(modules(CODE))] == modules(CODE)
    assert len(lines[1]) <= 180


def test_not_a_tty_prints_nothing():
    out = io.StringIO()
    assert terminal.show(CODE, out) is None
    assert out.getvalue() == ""
