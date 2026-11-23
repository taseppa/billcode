"""Generate examples/esimerkkilasku.pdf, a fictional bill for demos and manual testing.

The IBAN and reference number are the public test values from Finance Finland's
Bank Bar Code Guide; the company is made up.

    uv run python examples/make_sample.py
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

OUT = Path(__file__).with_name("esimerkkilasku.pdf")


def main() -> None:
    c = canvas.Canvas(str(OUT), pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, h - 25 * mm, "Esimerkki Energia Oy")
    c.drawRightString(w - 20 * mm, h - 25 * mm, "LASKU")
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 31 * mm, "Sähkökatu 1, 00100 Helsinki · Y-tunnus 1234567-8")

    y = h - 50 * mm
    for label, value in [
        ("Laskun numero", "2026-1123"),
        ("Laskun päiväys", "23.11.2026"),
        ("Asiakasnumero", "40012"),
        ("Viitenumero", "86851 62596 19897"),
        ("Eräpäivä", "15.12.2026"),
    ]:
        c.drawString(120 * mm, y, label)
        c.drawString(155 * mm, y, value)
        y -= 5 * mm

    y = h - 90 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "Kuvaus")
    c.drawRightString(150 * mm, y, "ALV-%")
    c.drawRightString(w - 20 * mm, y, "Summa")
    c.setFont("Helvetica", 9)
    for desc, vat, amount in [
        ("Sähköenergia 10/2026, 412 kWh", "25,5", "52,73"),
        ("Perusmaksu 10/2026", "25,5", "4,99"),
        ("Siirto 10/2026", "25,5", "12,96"),
    ]:
        y -= 6 * mm
        c.drawString(20 * mm, y, desc)
        c.drawRightString(150 * mm, y, vat)
        c.drawRightString(w - 20 * mm, y, amount)
    y -= 10 * mm
    for label, amount in [
        ("Yhteensä ilman ALV:tä", "70,68"),
        ("ALV-summa 25,5 %", "18,02"),
        ("Maksettava yhteensä sis. ALV:n", "88,70 €"),
    ]:
        c.drawString(100 * mm, y, label)
        c.drawRightString(w - 20 * mm, y, amount)
        y -= 6 * mm

    # Credit transfer form (tilisiirtolomake) at the bottom of the page
    top = 95 * mm
    c.line(15 * mm, top, w - 15 * mm, top)
    rows = [
        ("Saajan tilinumero", "IBAN FI79 4405 2020 0360 82"),
        ("Saaja", "Esimerkki Energia Oy"),
        ("Maksajan nimi", "Maija Meikäläinen"),
        ("Viitenumero", "86851 62596 19897"),
    ]
    y = top - 8 * mm
    for label, value in rows:
        c.drawString(20 * mm, y, label)
        c.drawString(60 * mm, y, value)
        y -= 9 * mm
    c.drawString(20 * mm, y, "Eräpäivä")
    c.drawString(60 * mm, y, "15.12.2026")
    c.drawString(115 * mm, y, "Euro")
    c.drawString(130 * mm, y, "88,70")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, 30 * mm, "TILISIIRTO. GIRERING")
    c.save()
    print(OUT)


if __name__ == "__main__":
    main()
