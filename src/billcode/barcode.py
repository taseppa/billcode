"""Finnish virtual bank barcode (virtuaaliviivakoodi / pankkiviivakoodi).

Implements versions 4 and 5 of Finance Finland's *Bank Bar Code Guide* v5.3.
The 54-digit string is laid out as:

    version 4: 4 | IBAN digits 16 | euros 6 | cents 2 | 000 | national ref 20 | YYMMDD
    version 5: 5 | IBAN digits 16 | euros 6 | cents 2 | RF ref 23          | YYMMDD

Amount and due date may be zeros (payer chooses the amount / no due date).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_AMOUNT = Decimal("999999.99")


class BarcodeError(ValueError):
    """Input cannot be encoded, or a barcode string is invalid."""


@dataclass(frozen=True)
class Payment:
    iban: str  # normalized, e.g. "FI7944052020036082"
    reference: str  # normalized, national "868516259619897" or "RF09868516259619897"
    amount: Decimal | None = None  # None = payer chooses the amount
    due: date | None = None
    name: str | None = None  # payee name (QR code only)
    bic: str | None = None  # payee bank BIC (QR code only)

    @property
    def is_rf(self) -> bool:
        return self.reference.startswith("RF")


# --- validation helpers -------------------------------------------------------


def _compact(value: str) -> str:
    return re.sub(r"[\s -]", "", value).upper()


def _mod97(s: str) -> int:
    """ISO 7064 mod 97-10 over a string of digits and letters (A=10 ... Z=35)."""
    return int("".join(str(int(c, 36)) for c in s)) % 97


def normalize_iban(iban: str) -> str:
    iban = _compact(iban)
    if not re.fullmatch(r"FI\d{16}", iban):
        raise BarcodeError(f"not a Finnish IBAN (FI + 16 digits): {iban!r}")
    if _mod97(iban[4:] + iban[:4]) != 1:
        raise BarcodeError(f"IBAN checksum fails: {iban}")
    if int(iban[4:]) == 0:
        raise BarcodeError("IBAN account number cannot be zero")
    return iban


def fi_reference_check_digit(base: str) -> int:
    """Check digit for a Finnish national reference (weights 7, 3, 1 from the right)."""
    weights = (7, 3, 1)
    total = sum(int(d) * weights[i % 3] for i, d in enumerate(reversed(base)))
    return (10 - total % 10) % 10


def is_valid_fi_reference(ref: str) -> bool:
    ref = _compact(ref).lstrip("0")
    return (
        re.fullmatch(r"\d{4,20}", ref) is not None
        and fi_reference_check_digit(ref[:-1]) == int(ref[-1])
    )


def is_valid_rf_reference(ref: str) -> bool:
    ref = _compact(ref)
    return (
        re.fullmatch(r"RF\d{2}[0-9A-Z]{1,21}", ref) is not None
        and _mod97(ref[4:] + ref[:4]) == 1
    )


def normalize_reference(ref: str) -> str:
    ref = _compact(ref)
    if ref.startswith("RF"):
        if not is_valid_rf_reference(ref):
            raise BarcodeError(f"invalid RF reference: {ref}")
        if not ref[4:].isdigit():
            # The guide: RF references with letters cannot go into the barcode.
            raise BarcodeError(f"RF reference contains letters, not barcode-encodable: {ref}")
        return "RF" + ref[2:4] + ref[4:].lstrip("0")
    ref = ref.lstrip("0")
    if not is_valid_fi_reference(ref):
        raise BarcodeError(f"invalid reference number: {ref}")
    return ref


def parse_amount(value: str | Decimal | int | float | None) -> Decimal | None:
    """Parse '1 234,56', '1234.56', '1.234,56' etc. into Decimal (None stays None)."""
    if value is None or isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    s = re.sub(r"[\s €]|EUR", "", value, flags=re.I)
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d{1,2})?", s) or "," in s and "." not in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        raise BarcodeError(f"cannot parse amount: {value!r}") from None


# --- encode / decode ----------------------------------------------------------


def encode(payment: Payment) -> str:
    """Build the 54-digit virtual barcode for a payment."""
    iban = normalize_iban(payment.iban)
    ref = normalize_reference(payment.reference)

    cents = 0
    if payment.amount is not None:
        amount = Decimal(payment.amount)
        if amount < 0:
            raise BarcodeError("amount cannot be negative")
        if amount.quantize(Decimal("0.01")) != amount:
            raise BarcodeError(f"amount has more than 2 decimals: {amount}")
        # Over the limit, the guide allows printing zeros (payer enters amount).
        cents = 0 if amount > MAX_AMOUNT else int(amount * 100)

    due = payment.due.strftime("%y%m%d") if payment.due else "000000"
    if payment.due and not 2000 <= payment.due.year <= 2099:
        raise BarcodeError("due date must be in years 2000-2099")

    if ref.startswith("RF"):
        code = f"5{iban[2:]}{cents:08d}{ref[2:4]}{ref[4:].zfill(21)}{due}"
    else:
        code = f"4{iban[2:]}{cents:08d}000{ref.zfill(20)}{due}"
    assert len(code) == 54, code
    return code


def decode(code: str) -> Payment:
    """Parse and validate a 54-digit virtual barcode."""
    code = _compact(code)
    if not re.fullmatch(r"[45]\d{53}", code):
        raise BarcodeError("virtual barcode must be 54 digits starting with 4 or 5")

    iban = normalize_iban("FI" + code[1:17])
    cents = int(code[17:25])
    if code[0] == "4":
        if code[25:28] != "000":
            raise BarcodeError("version 4 reserve field must be 000")
        reference = normalize_reference(code[28:48])
    else:
        reference = normalize_reference("RF" + code[25:27] + code[27:48])

    yymmdd = code[48:54]
    due = None
    if yymmdd != "000000":
        try:
            due = date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:]))
        except ValueError:
            raise BarcodeError(f"invalid due date in barcode: {yymmdd}") from None

    amount = Decimal(cents) / 100 if cents else None
    return Payment(iban=iban, reference=reference, amount=amount, due=due)


def code128_check_digit(code: str) -> int:
    """Code 128 (set C) modulus-103 check value for a printed bank barcode.

    Not part of the virtual barcode; useful if you render the actual bars.
    """
    pairs = [int(code[i : i + 2]) for i in range(0, len(code), 2)]
    return (105 + sum(i * v for i, v in enumerate(pairs, start=1))) % 103


def format_reference(ref: str) -> str:
    """Human-readable grouping: national refs in 5s from the right, RF in 4s."""
    if ref.startswith("RF"):
        return " ".join(ref[i : i + 4] for i in range(0, len(ref), 4))
    groups = []
    while ref:
        groups.insert(0, ref[-5:])
        ref = ref[:-5]
    return " ".join(groups)


def format_iban(iban: str) -> str:
    return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))
