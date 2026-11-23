# billcode

Reads a Finnish PDF bill and gives you its **virtuaaliviivakoodi**: the 54-digit virtual bank barcode you can paste into online banking.

```
$ billcode lasku.pdf --copy
lasku.pdf:
  Saaja IBAN : FI79 4405 2020 0360 82
  Viite      : 86851 62596 19897
  Summa      : 48,58 €
  Eräpäivä   : 15.12.2026
  Lähde      : built
  Virtuaaliviivakoodi:
  479440520200360820000485800000000868516259619897261215
Copied to clipboard.
```

## How it works

1. It extracts the PDF's text with [pdfplumber](https://github.com/jsvine/pdfplumber).
2. If the bill prints the 54-digit code as text, it validates the code and uses it (`Lähde: printed`).
3. Otherwise it finds the IBAN, the reference number (national or RF), the amount and the due date, then builds the code (`Lähde: built`).

Every IBAN and reference number is checksum-validated, so random numbers on the bill are not picked up by mistake. Always compare the result with the bill before paying.

The amount and due date can be missing; in that case the code holds zeros, as the spec allows, and the bank asks for them. The IBAN and reference number are required.

If extraction gets something wrong, override the field:

```
billcode lasku.pdf --amount 48,58 --due 15.12.2026 --viite "86851 62596 19897" --iban "FI79 4405 2020 0360 82"
```

Use `--json` for machine-readable output.

## Payment QR code

Alongside the barcode, a payment QR code is made, following Finance Finland's *QR code in credit transfer forms* (EPC QR v001, UTF-8, error correction M, at most version 13). It carries the payee name, BIC, IBAN, amount, reference and due date (`ReqdExctnDt/`).

- The QR code requires the payee name and BIC. The name is looked for on the bill (Saaja / Mottagare / Yritys …). The BIC comes from Finance Finland's bank code table (`src/billcode/bic.py`, 16.3.2026), or failing that from the bill.
- If either is missing, only the barcode is made and a warning is shown. Fix with `--saaja "Firma Oy"` / `--bic NDEAFIHH`, or turn the QR code off with `--no-qr`.

## Scannable barcode

The barcode is drawn in the terminal by default, so you can scan it straight off the screen with your bank's mobile app. kitty and Ghostty use the kitty graphics protocol, iTerm2 and WezTerm use iTerm2 inline images, and other terminals get Unicode half blocks (176 columns needed). Turn it off with `--no-image`. Nothing is drawn when the output is piped.

```
billcode lasku.pdf --open        # open the barcode in the system image viewer
billcode lasku.pdf --png --svg   # save lasku.barcode.png / .svg to $TMPDIR/billcode/
billcode lasku.pdf --svg -o ~/laskut   # ...or keep it somewhere permanent
```

The symbol follows the guide's section 6: Code 128 with a fixed Start C and character set C only. The SVG is to scale for printing, with 105 mm of bars, 12 mm tall and 20 mm quiet zones. The PNG is a crisp 1-bit image for screens. The tests render every spec invoice and decode it again with ZXing to confirm it reads back as the same 54 digits.

## Install / run

```
uv sync
uv run billcode lasku.pdf
uv run pytest
```

## Spec

The encoder follows Finance Finland's *Bank Bar Code Guide* v5.3, versions 4 and 5. `tests/spec_vectors.json` holds all 18 test invoices from that guide, extracted mechanically from its text, and the encoder and decoder are tested against them.

## Limitations

- Scanned bills with no text layer are not supported yet. OCR would be the next step.
- Only Finnish (FI) IBANs are supported, as the barcode spec requires.
- RF references that contain letters cannot be encoded; the spec forbids them.
