#!/usr/bin/env python3
"""Erzeugt die amtliche Steueranmeldung als PDF – pixelgenau wie das Original.

Ansatz: Die Original-PDF (Online-Formular der Stadt Dresden, Vdr 22.040/5) wurde
einmalig zu einer Blanko-Vorlage `templates/anmeldung_blank.pdf` verarbeitet
(variable Werte per Redaction entfernt, Betreiberdaten/Kassenzeichen/Layout
erhalten – siehe tools/make_blank.py). Hier werden je Monat nur die berechneten
Werte koordinatengenau eingesetzt und der Monat angekreuzt.

Benötigt PyMuPDF (`pip install pymupdf`).
"""
import os
import fitz  # PyMuPDF

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(HERE, "templates", "anmeldung_blank.pdf")

FONT = "helv"
FS = 10.0
X_RIGHT = 517.0  # rechte Kante der Zahlenspalte (Seite 2), rechtsbündig

# Monatskästchen: Spalten-x der Labels, Kästchen sitzt 16.3 pt links davon
_COLS = [74.0, 146.3, 215.7, 286.6, 358.9, 428.3]
_ROW_Y = {0: 419.1, 1: 403.5}  # Zeile 0 = Jan–Jun, Zeile 1 = Jul–Dez

# Baselines (PDF-Koordinaten) der Werte auf Seite 2
_NUMY = {
    "uebernachtungen_insgesamt": 788.1,
    "uebernachtungen_airbnb": 725.7,
    "uebernachtungen_verbleibend": 691.7,
    "umsatz_verbleibend": 667.6,
    "umsatz_steuerbefreit": 619.4,
    "umsatz_steuerpflichtig": 559.9,
    "beherbergungssteuer": 537.2,
}
_MONEY = {"umsatz_verbleibend", "umsatz_steuerbefreit",
          "umsatz_steuerpflichtig", "beherbergungssteuer"}


def _box(month):
    col = (month - 1) % 6
    row = (month - 1) // 6
    return _COLS[col] - 16.3, _ROW_Y[row]


def _money(v):
    # wie im Original: Dezimalkomma, ohne Tausenderpunkt
    return f"{v:.2f}".replace(".", ",")


def render_pdf(result, *, year=None, month=None, datum=""):
    """Gefülltes Formular als PDF-Bytes zurückgeben.

    result: Dict aus steuer.compute(). datum: 'TT.MM.JJJJ' (Unterschriftsdatum).
    """
    year = year or result["year"]
    month = month or result["month"]
    doc = fitz.open(TEMPLATE)
    p1, p2 = doc[0], doc[1]
    h1, h2 = p1.rect.height, p2.rect.height

    def put(page, h, x, ybase, txt, right=False):
        if right:
            x = X_RIGHT - fitz.get_text_length(txt, FONT, FS)
        page.insert_text(fitz.Point(x, h - ybase), txt,
                         fontsize=FS, fontname=FONT, color=(0, 0, 0))

    # Seite 1: Jahr + Monatskreuz
    put(p1, h1, 332.5, 540.8, str(year))
    bx, by = _box(month)
    p1.draw_line(fitz.Point(bx + 0.6, h1 - (by + 0.6)),
                 fitz.Point(bx + 6.1, h1 - (by + 6.1)), color=(0, 0, 0), width=1.2)
    p1.draw_line(fitz.Point(bx + 0.6, h1 - (by + 6.1)),
                 fitz.Point(bx + 6.1, h1 - (by + 0.6)), color=(0, 0, 0), width=1.2)

    # Seite 2: Werte rechtsbündig + Datum unten links
    for key, ybase in _NUMY.items():
        v = result[key]
        txt = _money(v) if key in _MONEY else str(int(v))
        put(p2, h2, 0, ybase, txt, right=True)
    if datum:
        put(p2, h2, 59.7, 194.2, datum)

    return doc.tobytes()
