"""The rendered barcodes must scan back to exactly the 54 digits (decoded by ZXing)."""

import io
import json
import re
from pathlib import Path

import pytest

from billcode.render import BARS_MM, modules, to_png, to_svg

zxingcpp = pytest.importorskip("zxingcpp")
Image = pytest.importorskip("PIL.Image")

VECTORS = json.loads((Path(__file__).parent / "spec_vectors.json").read_text())


def scan(png: bytes):
    return zxingcpp.read_barcodes(Image.open(io.BytesIO(png)).convert("L"))


@pytest.mark.parametrize("v", VECTORS, ids=lambda v: f"v{v['version']}-invoice{v['invoice']}")
def test_png_scans_back(v):
    results = scan(to_png(v["barcode"]))
    assert len(results) == 1
    assert results[0].format == zxingcpp.BarcodeFormat.Code128
    assert results[0].text == v["barcode"]


def test_small_module_still_scans():
    code = VECTORS[0]["barcode"]
    assert scan(to_png(code, module_px=2))[0].text == code


def test_symbol_structure():
    mods = modules(VECTORS[0]["barcode"])
    assert len(mods) == 29 * 11 + 13  # start + 27 pairs + check, then 13-module stop
    assert mods.startswith("11010011100")  # Start C, fixed by the guide
    assert mods.endswith("1100011101011")


def test_svg_physical_size():
    svg = to_svg(VECTORS[0]["barcode"])
    xs = [(float(x), float(w)) for x, w in re.findall(r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)"', svg)]
    width = xs[-1][0] + xs[-1][1] - xs[0][0]
    assert abs(width - BARS_MM) < 0.01
    assert 70 <= width <= 105


def test_refuses_invalid_code():
    with pytest.raises(ValueError):
        modules("4" + "0" * 53)
