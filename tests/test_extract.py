from datetime import date
from decimal import Decimal

import pytest

from billcode.extract import process_pdf, process_text

GIRO_TEXT = """\
Esimerkki Energia Oy                         LASKU
Laskun numero 1001        Päiväys 01.11.2026
Sähkö 10/2026                       38,71
ALV 25,5 % yhteensä                  9,87
Yhteensä                            48,58

Saajan       FI79 4405 2020 0360 82    IBAN
tilinumero   FI58 1017 1000 0001 22
Saaja        Esimerkki Energia Oy
Viitenumero  86851 62596 19897
Eräpäivä     15.12.2026        Euro  48,58
"""


def test_builds_from_fields():
    r = process_text(GIRO_TEXT)
    assert r.source == "built"
    assert r.payment.iban == "FI7944052020036082"
    assert r.payment.reference == "868516259619897"
    assert r.payment.amount == Decimal("48.58")
    assert r.payment.due == date(2026, 12, 15)
    assert r.code == "479440520200360820000485800000000868516259619897261215"
    assert any("several IBANs" in w for w in r.warnings)


def test_prefers_printed_barcode():
    text = GIRO_TEXT + "\nVirtuaaliviivakoodi: 5794 4052 0200 3608 2004 8831 5090 0000 0868 5162 5961 9897 1006 12\n"
    r = process_text(text)
    assert r.source == "printed"
    assert r.code == "579440520200360820048831509000000868516259619897100612"


def test_rf_reference_and_swedish_labels():
    text = """Mottagare FI58 1017 1000 0001 22
Referens RF06 5595 8224 3294 671
Förfallodag 31.1.2027   Att betala 482,99 €"""
    r = process_text(text)
    assert r.code == "558101710000001220004829906000000559582243294671270131"


def test_missing_reference():
    r = process_text("IBAN FI79 4405 2020 0360 82\nYhteensä 10,00")
    assert r.code is None
    assert any("reference" in w for w in r.warnings)


def test_ignores_invalid_reference_candidates():
    # Invoice number next to "Viite" label shouldn't be mistaken for the reference.
    text = "FI79 4405 2020 0360 82\nViite: asiakasnumero 12345 viitenumero 86851 62596 19897"
    r = process_text(text)
    assert r.payment.reference == "868516259619897"


def test_real_pdf(tmp_path):
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    path = tmp_path / "lasku.pdf"
    c = canvas.Canvas(str(path))
    for i, line in enumerate(GIRO_TEXT.splitlines()):
        c.drawString(40, 800 - 16 * i, line)
    c.save()
    r = process_pdf(path)
    assert r.code == "479440520200360820000485800000000868516259619897261215"


def test_pdf_without_text(tmp_path):
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    path = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(path))
    c.rect(10, 10, 100, 100)
    c.save()
    r = process_pdf(path)
    assert r.code is None and "OCR" in r.warnings[0]


# Structure of a real Finvoice-generated bill (names and numbers anonymized).
# It lists a VAT-free total before the payable one, and its footer has the payee.
FINVOICE_TEXT = """\
Lasku 1001 Sivu 1/1
Laskutusosoite
Asiakas Oy Laskun pvm 21.11.2026
Finland Viitenumero 86851625961989 7
Eräpäivä 28.11.2026
Maksuehdot 7 PV NETTO
Nro Kuvaus Toimituspvm Määrä Yksikkö Hinta à Alennus-% ALV-% Summa
1 Ladattava arvo 21.11.26 1 KPL 140,00 0 140,00
2 Latausmaksu 21.11.26 1 KPL 7,28 25,5 7,28
Yhteensä EUR ilman ALV:tä 147,28
ALV-summa 1,86
Yhteensä EUR sis. ALV:n 149,14
ALV-tunnus ALV-% Rivisumma perussumma alennussumma ALV-peruste ALV-summa
Yhteensä 147,28 147,28 0,00 147,28 1,86
Käytättehän maksuviitettä, kiitos. Yhteensä EUR 149,14 €
Yritys Esimerkki Palvelut Oy Puhelinnro (09) 123 4567 Pankki Nordea
Osoite Esimerkkikatu 1 Kotisivu www.example.fi ALV-nro FI12345678
00100 HELSINKI IBAN FI79 4405 2020 0360 82
Y-tunnus 1234567-8 BIC-/SWIFT koodi ITELFIHH
"""


def test_finvoice_bill_amount_due_and_payee():
    r = process_text(FINVOICE_TEXT)
    assert r.payment.amount == Decimal("149.14")  # not the VAT-free 147,28
    assert r.payment.due == date(2026, 11, 28)  # not the delivery date 21.11.26
    assert r.payment.name == "Esimerkki Palvelut Oy"
    assert r.payment.bic == "ITELFIHH"


def test_due_date_not_taken_from_far_below_label():
    text = "FI79 4405 2020 0360 82\nViitenumero 86851 62596 19897\nEräpäivä heti\nMaksuehto\nToimitettu 21.11.26"
    assert process_text(text).payment.due is None


def test_giro_payee_label():
    text = GIRO_TEXT.replace("Saaja        Esimerkki Energia Oy", "Saaja Mottagare Esimerkki Energia Oy")
    assert process_text(text).payment.name == "Esimerkki Energia Oy"


def test_overprinted_digit_is_dropped(tmp_path):
    canvas = pytest.importorskip("reportlab.pdfgen.canvas")
    path = tmp_path / "overprint.pdf"
    c = canvas.Canvas(str(path))
    c.setFont("Helvetica", 9)
    c.drawString(40, 700, "FI79 4405 2020 0360 82   Viitenumero 86851 62596 19897")
    c.drawString(40, 680, "Eräpäivä")
    c.drawString(200, 680, "28.11.2026")
    c.drawString(200, 681.8, "0")  # stray glyph over the '2', 1.8 pt off the baseline
    c.save()
    r = process_pdf(path)
    assert r.payment.due == date(2026, 11, 28)
