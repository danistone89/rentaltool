#!/usr/bin/env python3
"""Erzeugt die amtliche Steueranmeldung als PDF – pixelgenau wie das Original.

Ansatz: Die Original-PDF (Online-Formular der Stadt Dresden, Vdr 22.040/5) wurde
einmalig zu einer Blanko-Vorlage `templates/anmeldung_blank.pdf` verarbeitet
(ALLE variablen/personenbezogenen Werte per Redaction entfernt – siehe
tools/make_blank.py). Hier werden je Anmeldung eingesetzt:
  * Betreiberdaten + Kassenzeichen aus config.json (in den Einstellungen änderbar)
  * Jahr, Monatskreuz, die 7 Werte, Datum aus der Berechnung
  * Unterschrift aus assets/signature.png (Position konfigurierbar)

Benötigt PyMuPDF (`pip install pymupdf`).
"""
import os
import fitz  # PyMuPDF

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(HERE, "templates", "anmeldung_blank.pdf")
SIGNATURE = os.path.join(HERE, "assets", "signature.png")

FONT = "helv"
FS = 10.0
X_RIGHT = 517.0  # rechte Kante der Zahlenspalte (Seite 2), rechtsbündig

# Monatskästchen: Spalten-x der Labels, Kästchen sitzt 16.3 pt links davon
_COLS = [74.0, 146.3, 215.7, 286.6, 358.9, 428.3]
_ROW_Y = {0: 419.1, 1: 403.5}  # Zeile 0 = Jan–Jun, Zeile 1 = Jul–Dez

# Betreiber-Wertefelder (Seite 1): config-key -> (x, baseline_y), linksbündig
_BETREIBER_XY = {
    "name": (61.1, 245.2),
    "zusatz": (299.2, 245.2),
    "strasse": (61.1, 218.3),
    "hausnummer": (507.6, 218.3),
    "plz": (61.1, 191.4),
    "ort": (132.0, 191.4),
    "telefon": (61.1, 164.4),
    "kassenzeichen": (397.0, 574.0),
}

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

# Unterschrift (Originalmaße aus der Vorlage); x ist konfigurierbar
_SIG_W, _SIG_H = 67.1, 26.8
_SIG_TOP, _SIG_BOTTOM = 626.18, 652.99  # fitz-Koordinaten (Seite 2)
_SIG_X_DEFAULT = 240.0


def _box(month):
    col = (month - 1) % 6
    row = (month - 1) // 6
    return _COLS[col] - 16.3, _ROW_Y[row]


def _money(v):
    # wie im Original: Dezimalkomma, ohne Tausenderpunkt
    return f"{v:.2f}".replace(".", ",")


def render_pdf(result, cfg, *, year=None, month=None, datum=""):
    """Gefülltes Formular als PDF-Bytes zurückgeben.

    result: Dict aus steuer.compute(). cfg: config-Dict (Betreiber, Unterschrift).
    datum: 'TT.MM.JJJJ' (Unterschriftsdatum).
    """
    year = year or result["year"]
    month = month or result["month"]
    betr = cfg.get("betreiber", {})
    doc = fitz.open(TEMPLATE)
    p1, p2 = doc[0], doc[1]
    h1, h2 = p1.rect.height, p2.rect.height

    def put(page, h, x, ybase, txt, right=False):
        if not txt:
            return
        if right:
            x = X_RIGHT - fitz.get_text_length(txt, FONT, FS)
        page.insert_text(fitz.Point(x, h - ybase), txt,
                         fontsize=FS, fontname=FONT, color=(0, 0, 0))

    # Seite 1: Betreiberdaten + Kassenzeichen
    for key, (x, ybase) in _BETREIBER_XY.items():
        put(p1, h1, x, ybase, str(betr.get(key, "")))
    # Jahr
    put(p1, h1, 332.5, 540.8, str(year))
    # Monatskreuz
    bx, by = _box(month)
    p1.draw_line(fitz.Point(bx + 0.6, h1 - (by + 0.6)),
                 fitz.Point(bx + 6.1, h1 - (by + 6.1)), color=(0, 0, 0), width=1.2)
    p1.draw_line(fitz.Point(bx + 0.6, h1 - (by + 6.1)),
                 fitz.Point(bx + 6.1, h1 - (by + 0.6)), color=(0, 0, 0), width=1.2)

    # Seite 2: Werte rechtsbündig + Datum + Unterschrift
    for key, ybase in _NUMY.items():
        v = result[key]
        txt = _money(v) if key in _MONEY else str(int(v))
        put(p2, h2, 0, ybase, txt, right=True)
    if datum:
        put(p2, h2, 59.7, 194.2, datum)
    if os.path.exists(SIGNATURE):
        sig_x = float(cfg.get("unterschrift_x", _SIG_X_DEFAULT))
        p2.insert_image(fitz.Rect(sig_x, _SIG_TOP, sig_x + _SIG_W, _SIG_BOTTOM),
                        filename=SIGNATURE)

    return doc.tobytes()
