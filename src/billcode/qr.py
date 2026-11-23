"""Payment QR code per Finance Finland's "QR code in credit transfer forms" (2015).

The content is EPC QR (European Payments Council, "BCD") version 001:

    BCD / 001 / 1 (UTF-8) / SCT / BIC / payee name / IBAN / EUR<amount> /
    purpose / reference (RF or national) / message / ReqdExctnDt/<due date>

Fields are separated by LF. At most 331 bytes, QR version 13, error correction M.
"""

from __future__ import annotations

import io
import re
from decimal import Decimal
from pathlib import Path

import segno

from .barcode import BarcodeError, Payment, normalize_iban, normalize_reference
from .bic import bic_for_iban

MAX_BYTES = 331
MODULE_MM = 0.5  # the guide's recommended X-dimension


def epc_payload(payment: Payment) -> str:
    iban = normalize_iban(payment.iban)
    bic = (payment.bic or bic_for_iban(iban) or "").upper()
    if not re.fullmatch(r"[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?", bic):
        raise BarcodeError("QR code needs the payee's BIC (not found; use --bic)")
    name = " ".join((payment.name or "").split())
    if not name:
        raise BarcodeError("QR code needs the payee's name (not found; use --saaja)")
    if len(name) > 70:
        raise BarcodeError(f"payee name is over 70 characters: {name!r}")

    amount = ""
    if payment.amount:
        a = Decimal(payment.amount)
        if not Decimal("0.01") <= a <= Decimal("999999999.99"):
            raise BarcodeError(f"amount out of range for QR code: {a}")
        amount = f"EUR{a:.2f}"

    lines = [
        "BCD",
        "001",
        "1",
        "SCT",
        bic,
        name,
        iban,
        amount,
        "",  # purpose code
        normalize_reference(payment.reference),
        "",  # unstructured message: a reference and a message are mutually exclusive
        f"ReqdExctnDt/{payment.due.isoformat()}" if payment.due else "",
    ]
    payload = "\n".join(lines).rstrip("\n")
    if len(payload.encode("utf-8")) > MAX_BYTES:
        raise BarcodeError(f"QR payload is over {MAX_BYTES} bytes")
    return payload


def make(payload: str) -> segno.QRCode:
    qr = segno.make_qr(payload, error="m", boost_error=False, encoding="utf-8")
    if qr.version > 13:
        raise BarcodeError(f"QR code version {qr.version} is over the maximum 13")
    return qr


def to_png(payload: str, scale: int = 8) -> bytes:
    buf = io.BytesIO()
    make(payload).save(buf, kind="png", scale=scale, border=4)
    return buf.getvalue()


def to_svg(payload: str) -> str:
    buf = io.BytesIO()
    make(payload).save(buf, kind="svg", scale=MODULE_MM, unit="mm", border=4, xmldecl=False)
    return buf.getvalue().decode()


def matrix(payload: str) -> list[list[bool]]:
    return [[bool(v) for v in row] for row in make(payload).matrix]


def write(payload: str, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix.lower() == ".svg":
        path.write_text(to_svg(payload))
    elif path.suffix.lower() == ".png":
        path.write_bytes(to_png(payload))
    else:
        raise ValueError(f"unsupported image type: {path.suffix} (use .png or .svg)")
    return path
