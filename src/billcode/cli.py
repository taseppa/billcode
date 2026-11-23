"""billcode: get the virtual barcode (virtuaaliviivakoodi) of a PDF bill."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from .barcode import BarcodeError, Payment, encode, format_iban, format_reference, parse_amount
from .extract import Result, process_pdf
from . import qr, render, terminal

TEMP_DIR = Path(tempfile.gettempdir()) / "billcode"


def _parse_date(s: str) -> date:
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise argparse.ArgumentTypeError(f"bad date {s!r}, use dd.mm.yyyy")


def copy_to_clipboard(text: str) -> bool:
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(cmd[0]):
            subprocess.run(cmd, input=text.encode(), check=True)
            return True
    return False


def _apply_overrides(result: Result, args: argparse.Namespace) -> Result:
    overrides = {k: getattr(args, k) for k in ("iban", "reference", "amount", "due")}
    if any(v is not None for v in overrides.values()):
        base = result.payment
        payment = Payment(
            iban=args.iban or (base.iban if base else (result.ibans[0] if result.ibans else "")),
            reference=args.reference or (base.reference if base else ""),
            amount=parse_amount(args.amount) if args.amount is not None else (base.amount if base else None),
            due=args.due or (base.due if base else None),
            name=base.name if base else None,
            bic=base.bic if base else None,
        )
        result = Result(code=encode(payment), payment=payment, source="built (with overrides)", ibans=result.ibans)
    if result.payment and (args.name or args.bic):
        result.payment = replace(result.payment, name=args.name or result.payment.name, bic=args.bic or result.payment.bic)
    return result


def _print_human(path: str, result: Result) -> None:
    print(f"{path}:")
    for w in result.warnings:
        print(f"  ! {w}", file=sys.stderr)
    if not result.code:
        return
    p = result.payment
    print(f"  Saaja      : {p.name or '-'}")
    print(f"  Saaja IBAN : {format_iban(p.iban)}" + (f"  ({p.bic})" if p.bic else ""))
    print(f"  Viite      : {format_reference(p.reference)}")
    print(f"  Summa      : {f'{p.amount:.2f} €'.replace('.', ',') if p.amount is not None else '(maksaja täyttää)'}")
    print(f"  Eräpäivä   : {p.due.strftime('%d.%m.%Y') if p.due else '-'}")
    print(f"  Lähde      : {result.source}")
    print(f"  Virtuaaliviivakoodi:\n  {result.code}")


def _write_images(pdf_path: str, code: str, payload: str | None, args: argparse.Namespace) -> list[Path]:
    """Save requested images (temp folder unless --out-dir) and open them if asked."""
    if not (args.png or args.svg or args.open):
        return []
    out_dir = args.out_dir or TEMP_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(pdf_path).stem
    images = []
    for ext in [e for e, wanted in ((".png", args.png or args.open), (".svg", args.svg)) if wanted]:
        images.append(render.write(code, out_dir / f"{stem}.barcode{ext}"))
        if payload:
            images.append(qr.write(payload, out_dir / f"{stem}.qr{ext}"))
    if args.open:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        if shutil.which(opener):
            subprocess.run([opener, *[str(i) for i in images if i.suffix == ".png"]], check=False)
    return images


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="billcode", description=__doc__)
    ap.add_argument("pdf", nargs="+", help="PDF bill(s)")
    ap.add_argument("-c", "--copy", action="store_true", help="copy the (last) barcode to the clipboard")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--iban", help="override the payee IBAN")
    ap.add_argument("--reference", "--viite", dest="reference", help="override the reference number")
    ap.add_argument("--amount", "--summa", dest="amount", help="override the amount, e.g. 123,45")
    ap.add_argument("--due", "--erapaiva", dest="due", type=_parse_date, help="override the due date dd.mm.yyyy")
    ap.add_argument("--saaja", "--payee", dest="name", help="override the payee name (QR code)")
    ap.add_argument("--bic", help="override the payee bank BIC (QR code)")
    ap.add_argument("--no-image", action="store_true", help="don't draw the codes in the terminal")
    ap.add_argument("--no-qr", action="store_true", help="don't make the payment QR code")
    ap.add_argument("--png", action="store_true", help="save a scannable barcode image <bill>.barcode.png")
    ap.add_argument("--svg", action="store_true", help="save a print-size barcode image <bill>.barcode.svg")
    ap.add_argument("-o", "--out-dir", type=Path, help=f"where to save images (default: {TEMP_DIR})")
    ap.add_argument("--open", action="store_true", help="open the barcode image in the system image viewer")
    args = ap.parse_args(argv)

    status, last_code, out = 0, None, []
    for path in args.pdf:
        try:
            result = _apply_overrides(process_pdf(path), args)
        except (BarcodeError, OSError) as e:
            result = Result(warnings=[str(e)])
        except Exception as e:  # pdfplumber raises various errors on broken files
            result = Result(warnings=[f"cannot read PDF: {e}"])
        images, payload = [], None
        if not result.code:
            status = 1
        else:
            last_code = result.code
            if not args.no_qr:
                try:
                    payload = qr.epc_payload(result.payment)
                except BarcodeError as e:
                    result.warnings.append(f"no QR code: {e}")
            images = _write_images(path, result.code, payload, args)
        if args.json:
            p = result.payment
            out.append({
                "file": path,
                "code": result.code,
                "source": result.source or None,
                "iban": p.iban if p else None,
                "reference": p.reference if p else None,
                "amount": f"{p.amount:.2f}" if p and p.amount is not None else None,
                "due": p.due.isoformat() if p and p.due else None,
                "qr": payload,
                "images": [str(i) for i in images],
                "warnings": result.warnings,
            })
        else:
            _print_human(path, result)
            for image in images:
                print(f"  Kuva       : {image}")
            if result.code and not args.no_image:
                print()
                sys.stdout.flush()
                if problem := terminal.show(result.code):
                    print(f"  ! {problem}", file=sys.stderr)
                if payload:
                    print()
                    sys.stdout.flush()
                    if problem := terminal.show_qr(payload):
                        print(f"  ! {problem}", file=sys.stderr)

    if args.json:
        print(json.dumps(out if len(out) > 1 else out[0], ensure_ascii=False, indent=2))
    sys.stdout.flush()
    if args.copy and last_code:
        if copy_to_clipboard(last_code):
            print("Copied to clipboard.", file=sys.stderr)
        else:
            print("No clipboard tool found.", file=sys.stderr)
    return status


if __name__ == "__main__":
    sys.exit(main())
