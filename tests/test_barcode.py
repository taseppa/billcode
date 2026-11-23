"""Tests against the official test invoices in Finance Finland's Bank Bar Code Guide v5.3.

spec_vectors.json was generated mechanically from the guide's text (section 13).
"""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from billcode.barcode import (
    BarcodeError,
    Payment,
    code128_check_digit,
    decode,
    encode,
    fi_reference_check_digit,
)

VECTORS = json.loads((Path(__file__).parent / "spec_vectors.json").read_text())


def _due(v):
    return datetime.strptime(v["due"], "%d.%m.%Y").date() if v["due"] else None


def _id(v):
    return f"v{v['version']}-invoice{v['invoice']}"


def test_vector_count():
    assert len(VECTORS) == 18
    assert sorted(v["version"] for v in VECTORS) == [4] * 9 + [5] * 9


@pytest.mark.parametrize("v", VECTORS, ids=_id)
def test_encode_matches_spec(v):
    payment = Payment(iban=v["iban"], reference=v["reference"], amount=Decimal(v["amount"]), due=_due(v))
    assert encode(payment) == v["barcode"]


@pytest.mark.parametrize("v", VECTORS, ids=_id)
def test_decode_matches_spec(v):
    p = decode(v["barcode"])
    assert p.iban == v["iban"]
    assert p.reference == v["reference"]
    assert p.due == _due(v)
    expected = Decimal(v["amount"])
    assert p.amount == (expected if expected else None)


# Erratum in the guide: v5 invoice 3 prints check value [59], but its own value
# pairs sum to 34 mod 103. The 54 data digits themselves match our encoder.
GUIDE_ERRATA = {(5, 3)}


@pytest.mark.parametrize("v", VECTORS, ids=_id)
def test_code128_check_matches_spec(v):
    if (v["version"], v["invoice"]) in GUIDE_ERRATA:
        assert code128_check_digit(v["barcode"]) == 34
    else:
        assert code128_check_digit(v["barcode"]) == v["code128_check"]


def test_rf_example_from_guide_text():
    # Section 10: "RF04 9991" -> reference field 04000000000000000009991
    code = encode(Payment(iban="FI7944052020036082", reference="RF04 9991"))
    assert code[25:48] == "04000000000000000009991"


def test_no_amount_and_no_due_date_are_zeros():
    code = encode(Payment(iban="FI79 4405 2020 0360 82", reference="86851 62596 19897"))
    assert code[17:25] == "00000000" and code[-6:] == "000000"


def test_amount_over_limit_becomes_zeros():
    code = encode(Payment(iban="FI7944052020036082", reference="868516259619897", amount=Decimal("1000000.00")))
    assert code[17:25] == "00000000"


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(iban="FI7944052020036083", reference="868516259619897"),  # bad IBAN checksum
        dict(iban="SE4550000000058398257466", reference="868516259619897"),  # not Finnish
        dict(iban="FI7944052020036082", reference="868516259619896"),  # bad ref check digit
        dict(iban="FI7944052020036082", reference="RF08868516259619897"),  # bad RF checksum
        dict(iban="FI7944052020036082", reference="RF18539007547034"[:4] + "ABC"),  # letters
        dict(iban="FI7944052020036082", reference="868516259619897", amount=Decimal("1.005")),
        dict(iban="FI7944052020036082", reference="868516259619897", amount=Decimal("-1")),
    ],
)
def test_invalid_input_rejected(kwargs):
    with pytest.raises(BarcodeError):
        encode(Payment(**kwargs))


def test_decode_rejects_corruption():
    good = VECTORS[0]["barcode"]
    bad = good[:20] + str((int(good[20]) + 1) % 10) + good[21:]  # amount digit: still valid
    decode(bad)
    bad_ref = good[:40] + str((int(good[40]) + 1) % 10) + good[41:]
    with pytest.raises(BarcodeError):
        decode(bad_ref)
    with pytest.raises(BarcodeError):
        decode(good[:-1])


def test_reference_check_digit():
    assert fi_reference_check_digit("123") == 2  # 1232, the standard example
