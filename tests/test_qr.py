import io
from datetime import date
from decimal import Decimal

import pytest

from billcode.barcode import BarcodeError, Payment
from billcode.bic import bic_for_iban
from billcode.qr import epc_payload, make, to_png

zxingcpp = pytest.importorskip("zxingcpp")
Image = pytest.importorskip("PIL.Image")


def test_guide_example_1():
    # Finance Finland, "Guidelines for the QR code in the Credit Transfer Forms", 9.1
    p = Payment(
        iban="FI7944052020036082",
        reference="RF07663321328510",
        amount=Decimal("158.24"),
        due=date(2014, 1, 22),
        name="Asiakas T. Meikäläinen",
        bic="OKOYFIHH",
    )
    assert epc_payload(p) == (
        "BCD\n001\n1\nSCT\nOKOYFIHH\nAsiakas T. Meikäläinen\nFI7944052020036082\n"
        "EUR158.24\n\nRF07663321328510\n\nReqdExctnDt/2014-01-22"
    )


def test_national_reference_and_bic_from_table():
    p = Payment(iban="FI87 1820 3000 0501 04", reference="44 52001 44310 00004",
                amount=Decimal("149.14"), due=date(2026, 11, 28), name="Esimerkki Oy")
    lines = epc_payload(p).split("\n")
    assert lines[4] == "NDEAFIHH"
    assert lines[9] == "44520014431000004"
    assert lines[11] == "ReqdExctnDt/2026-11-28"


def test_optional_fields_left_empty():
    p = Payment(iban="FI7944052020036082", reference="868516259619897", name="Esimerkki Oy")
    lines = epc_payload(p).split("\n")
    assert lines[7] == "" and len(lines) == 10  # no amount; trailing due date line dropped


def test_scans_back_with_utf8():
    p = Payment(iban="FI7944052020036082", reference="868516259619897", amount=Decimal("48.58"),
                due=date(2026, 12, 15), name="Åbo Sähkö ja Vesi Oy", bic="ITELFIHH")
    payload = epc_payload(p)
    results = zxingcpp.read_barcodes(Image.open(io.BytesIO(to_png(payload))))
    assert results[0].format == zxingcpp.BarcodeFormat.QRCode
    assert results[0].text == payload


def test_error_correction_and_max_size():
    p = Payment(iban="FI7944052020036082", reference="RF7192125374252539897737",
                amount=Decimal("999999999.99"), due=date(2099, 12, 31), name="X" * 70, bic="NDEAFIHH")
    qr = make(epc_payload(p))
    assert qr.error == "M" and qr.version <= 13


@pytest.mark.parametrize("kwargs,match", [
    (dict(name=None), "name"),
    (dict(iban="FI7331313001000058"), "BIC"),  # Handelsbanken left Finland: no BIC in table
])
def test_required_fields(kwargs, match):
    base = dict(iban="FI7944052020036082", reference="868516259619897", name="Esimerkki Oy")
    with pytest.raises(BarcodeError, match=match):
        epc_payload(Payment(**{**base, **kwargs}))


@pytest.mark.parametrize("iban,bic", [
    ("FI8718203000050104", "NDEAFIHH"),  # 1
    ("FI0250004640001302", "OKOYFIHH"),  # 5
    ("FI1566010001530641", "AABAFI22"),  # 6
    ("FI9239390001003391", "SBANFIHH"),  # 39
    ("FI1680001400050267", "DABAFIHH"),  # 8
    ("FI7944052020036082", "ITELFIHH"),  # 440: savings bank range
    ("FI2147900010000000", "POPFFI22"),  # 479
    ("FI2140500010000000", "HELSFIHH"),  # 405 Aktia
    ("FI2179900010000000", "HOLVFIHH"),  # 799 Holvi
])
def test_bic_table(iban, bic):
    assert bic_for_iban(iban) == bic
