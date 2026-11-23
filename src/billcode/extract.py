"""Find payment details in a PDF bill and produce its virtual barcode."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from pathlib import Path

from .bic import bic_for_iban
from .barcode import (
    BarcodeError,
    Payment,
    decode,
    encode,
    is_valid_fi_reference,
    is_valid_rf_reference,
    normalize_iban,
    normalize_reference,
    parse_amount,
)

# Labels as they appear on Finnish / Swedish / English bills (lowercase).
REF_LABELS = r"viitenumero|viitenro|viite|referensnummer|referens|reference\s*(?:number|no\.?)?|ref\.?\s*(?:nr|no)?\.?"
AMOUNT_LABELS = (
    r"euro|eur|€|maksettava|att\s+betala|amount\s+due|to\s+pay"
    r"|loppusumma|yhteensä|totalt|total|summa|belopp|amount"
)
# A line with these is a VAT-free subtotal, VAT amount, discount etc.: never the sum to pay.
_AMOUNT_EXCLUDE = re.compile(
    r"ilman\s+alv|veroton|alv[- ]?(?:summa|peruste|osuus|erittely|määritys)|alv\s*0\s*%"
    r"|exkl|excl|ex\.?\s*vat|netto|vat\s+amount|momsbelopp|alennus|rabatt|discount",
    re.I,
)
# A line with these is very likely the sum to pay.
_AMOUNT_BOOST = re.compile(
    r"maksettava|att\s+betala|to\s+pay|amount\s+due|sis\.?\s*alv|inkl\.?\s*moms|incl\.?\s*vat|loppusumma",
    re.I,
)
PAYEE_LABELS = [
    r"saaja|mottagare|maksun\s+saaja|payee|beneficiary",
    r"yritys|laskuttaja|myyjä|säljare|seller|company|företag",
]
# Words that end a payee name on the same line (next label in a footer table).
_NAME_STOP = re.compile(
    r"\s+(?:puh(?:elin)?(?:nro)?|tel(?:efon)?|osoite|adress|address|y-tunnus|fo-nummer|business\s+id"
    r"|kotisivu|www\.|iban|bic|pankki|bank|sähköposti|e-?mail|alv|moms|vat|tilinumero|mottagare)\b.*",
    re.I,
)
_COMPANY_SUFFIX = re.compile(r"^(.*?\b(?:oyj|oy|ab|abp|ky|tmi|ry|ltd|plc|gmbh|as|a/s|asa))\b", re.I)
_BIC_RE = re.compile(r"\b[A-Z]{4}FI[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b")
DUE_LABELS = r"eräpäivä|eräp\.?|förfallodag|förfallodatum|due\s*date"

LABEL_WINDOW = 160  # characters after a label that we search for its value

_BARCODE_RE = re.compile(r"(?<![\d])[45](?:[  ]?\d){53}(?![\d])")
_IBAN_RE = re.compile(r"\bFI\s?\d{2}(?:[  ]?\d){14}(?!\d)")
_RF_RE = re.compile(r"\bRF\s?\d{2}(?:[  ]?[0-9A-Z]){1,21}\b")
_DIGITS_RE = re.compile(r"(?<![\d,.])\d(?:[  ]?\d){3,24}(?![\d,.])")
_AMOUNT_RE = re.compile(r"(?<![\d.,])\d{1,3}(?:[  .]\d{3})*(?:[.,]\d{2})(?![\d])|(?<![\d.,])\d+[.,]\d{2}(?![\d])")
_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)")


@dataclass
class Result:
    code: str | None = None
    payment: Payment | None = None
    source: str = ""  # "printed" (found in PDF) or "built" (from fields)
    warnings: list[str] = field(default_factory=list)
    ibans: list[str] = field(default_factory=list)


def extract_text(pdf_path: str | Path) -> str:
    import pdfplumber

    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(_drop_overprinted(page).extract_text() or "" for page in pdf.pages)


def _drop_overprinted(page):
    """Remove stray glyphs drawn on top of other glyphs.

    Some invoice generators draw a character over another one, slightly off the
    baseline (seen: a '0' over the '2' of "28.11.2026"). pdfplumber merges
    both into the line, giving "208.11.2026". Of two different overlapping
    characters, keep the one that shares its baseline with more of the line.
    """
    chars = [c for c in page.chars if c["text"].strip()]
    baseline_count = Counter(round(c["top"], 1) for c in chars)
    by_x = defaultdict(list)
    for c in chars:
        by_x[int(c["x0"])].append(c)
    drop = set()
    for c in chars:
        for bucket in (int(c["x0"]) - 1, int(c["x0"]), int(c["x0"]) + 1):
            for o in by_x.get(bucket, ()):
                if o is c or o["text"] == c["text"]:
                    continue
                overlap = min(c["x1"], o["x1"]) - max(c["x0"], o["x0"])
                if overlap > 0.5 * min(c["x1"] - c["x0"], o["x1"] - o["x0"]) and abs(c["top"] - o["top"]) < 0.5 * c["size"]:
                    if baseline_count[round(c["top"], 1)] < baseline_count[round(o["top"], 1)]:
                        drop.add(id(c))
    if not drop:
        return page
    return page.filter(lambda obj: id(obj) not in drop)


def find_printed_barcodes(text: str) -> list[str]:
    found = []
    for m in _BARCODE_RE.finditer(text):
        code = re.sub(r"\D", "", m.group(0))
        try:
            decode(code)
        except BarcodeError:
            continue
        if code not in found:
            found.append(code)
    return found


def find_ibans(text: str) -> list[str]:
    found = []
    for m in _IBAN_RE.finditer(text):
        try:
            iban = normalize_iban(m.group(0))
        except BarcodeError:
            continue
        if iban not in found:
            found.append(iban)
    return found


def _after_labels(text: str, labels: str):
    """Yield text windows that follow each occurrence of a label."""
    for m in re.finditer(rf"(?<![\w])(?:{labels})(?![^\W\d])", text, re.I):
        yield text[m.end() : m.end() + LABEL_WINDOW]


def find_reference(text: str) -> str | None:
    # RF references are self-identifying and checksummed: take the first valid one.
    for m in _RF_RE.finditer(text):
        candidate = re.sub(r"\s", "", m.group(0))
        # The regex may swallow a following word; shrink until valid.
        while len(candidate) > 4 and not is_valid_rf_reference(candidate):
            candidate = candidate[:-1]
        if is_valid_rf_reference(candidate) and candidate[4:].isdigit():
            return normalize_reference(candidate)
    # National references: only trust numbers right after a reference label.
    for window in _after_labels(text, REF_LABELS):
        for m in _DIGITS_RE.finditer(window):
            candidate = re.sub(r"\D", "", m.group(0))
            if is_valid_fi_reference(candidate):
                return normalize_reference(candidate)
    return None


def _line_at(text: str, pos: int) -> str:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text[start : end if end >= 0 else len(text)]


def find_amount(text: str) -> Decimal | None:
    """The sum to pay: labelled amounts, skipping VAT-free subtotals and VAT lines.

    Lines that say "to pay" / "incl. VAT" win; among equals, the largest amount
    (the grand total is never smaller than the subtotals around it).
    """
    candidates = []
    for m in re.finditer(rf"(?<![\w])(?:{AMOUNT_LABELS})(?![^\W\d])", text, re.I):
        line = _line_at(text, m.start())
        if _AMOUNT_EXCLUDE.search(line):
            continue
        am = _AMOUNT_RE.search(text, m.end(), m.end() + 60)
        if not am:
            continue
        try:
            amount = parse_amount(am.group(0))
        except BarcodeError:
            continue
        candidates.append((2 if _AMOUNT_BOOST.search(line) else 1, amount))
    return max(candidates)[1] if candidates else None


def _parse_date(m: re.Match) -> date | None:
    d, mo, y = (int(g) for g in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def find_due_date(text: str) -> date | None:
    for window in _after_labels(text, DUE_LABELS):
        # The value is on the label's line or the next one, never further away.
        window = "\n".join(window.split("\n")[:2])
        for m in _DATE_RE.finditer(window):
            if parsed := _parse_date(m):
                return parsed
    return None


def find_payee_name(text: str) -> str | None:
    for labels in PAYEE_LABELS:
        for m in re.finditer(rf"(?<![\w])(?:{labels})(?![^\W\d])\s*:?[ \t]*", text, re.I):
            rest = _line_at(text, m.start())[m.end() - text.rfind("\n", 0, m.start()) - 1 :]
            # Bilingual giro labels: "Saaja Mottagare Firma Oy"
            rest = re.sub(r"^(?:mottagare|saaja|payee)\s*:?\s*", "", rest, flags=re.I)
            rest = _NAME_STOP.sub("", rest).strip(" :;,")
            if suffix := _COMPANY_SUFFIX.match(rest):
                rest = suffix.group(1)
            if 2 <= len(rest) <= 70 and re.match(r"[^\W\d_]", rest):
                return rest
    return None


def find_bic(text: str, iban: str) -> str | None:
    """BIC from Finance Finland's table; else one printed on the bill."""
    if bic := bic_for_iban(iban):
        return bic
    m = _BIC_RE.search(text)
    return m.group(0) if m else None


def process_text(text: str) -> Result:
    result = _process_text(text)
    if result.payment:
        result.payment = replace(
            result.payment,
            name=find_payee_name(text),
            bic=find_bic(text, result.payment.iban),
        )
    return result


def _process_text(text: str) -> Result:
    result = Result(ibans=find_ibans(text))

    printed = find_printed_barcodes(text)
    if printed:
        result.code = printed[0]
        result.payment = decode(printed[0])
        result.source = "printed"
        if len(printed) > 1:
            result.warnings.append(f"{len(printed)} different barcodes found; using the first")
        return result

    if not result.ibans:
        result.warnings.append("no valid Finnish IBAN found")
    reference = find_reference(text)
    if not reference:
        result.warnings.append("no valid reference number found")
    if not result.ibans or not reference:
        return result

    amount = find_amount(text)
    due = find_due_date(text)
    if amount is None:
        result.warnings.append("amount not found; barcode leaves it for the payer to fill in")
    if due is None:
        result.warnings.append("due date not found; barcode has no due date")
    if len(result.ibans) > 1:
        result.warnings.append(f"several IBANs on the bill; using {result.ibans[0]}")

    result.payment = Payment(iban=result.ibans[0], reference=reference, amount=amount, due=due)
    result.code = encode(result.payment)
    result.source = "built"
    return result


def process_pdf(pdf_path: str | Path) -> Result:
    text = extract_text(pdf_path)
    if not text.strip():
        return Result(warnings=["PDF has no text layer (scanned image?); OCR is not supported yet"])
    return process_text(text)
