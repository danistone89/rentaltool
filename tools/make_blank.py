#!/usr/bin/env python3
"""Erzeugt die Blanko-Vorlage + extrahiert die Unterschrift aus einer
eingereichten Steueranmeldungs-PDF.

Dresden bietet das Formular (Vdr 22.040/5) nur über ein Online-System an – es
gibt keinen Blanko-Download. Dieses Skript nimmt eine bereits ausgefüllte,
eingereichte PDF und entfernt per Redaction ALLE variablen/personenbezogenen
Werte (Zahlen, Datum, Jahr, Monatskreuz, Dokument-ID, Betreiberdaten,
Kassenzeichen, Unterschrift). Übrig bleibt das reine Formular-Layout.

Die Betreiberdaten + Unterschrift werden zur Laufzeit aus config.json bzw.
assets/signature.png eingesetzt (so sind sie in den Einstellungen änderbar).

Aufruf:
    python3 tools/make_blank.py <eingereichte.pdf> [ausgabe.pdf]

Standard-Ausgabe: templates/anmeldung_blank.pdf
Unterschrift wird (falls vorhanden) nach assets/signature.png extrahiert.

Benötigt PyMuPDF (pip install pymupdf).
"""
import os
import sys
import fitz

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NUM_Y = [788.1, 725.7, 691.7, 667.6, 619.4, 559.9, 537.2]  # Seite 2, Zahlenwerte
DEC_BOX = (409, 402, 421, 411)   # Dezember-Kreuz (Seite 1)
DATE_BOX = (54, 191, 135, 205)   # Datum unten links (Seite 2)

# Betreiber-Wertefelder (Seite 1) als PDF-Rects (x0,y0,x1,y1) – jeweils NUR die
# Eingabezeile, nicht das darüberliegende Label.
BETREIBER_BOXES = [
    (58, 242, 292, 256),    # Name/Firma
    (296, 242, 545, 256),   # Vorname/Firmenzusatz
    (58, 215, 500, 229),    # Straße
    (503, 215, 548, 229),   # Hausnummer
    (58, 188, 128, 202),    # PLZ
    (129, 188, 545, 202),   # Ort
    (58, 161, 300, 175),    # Telefon
    (393, 571, 562, 585),   # Kassenzeichen
]


def _r(x0, y0, x1, y1, h):
    return fitz.Rect(x0, h - y1, x1, h - y0)


def main():
    if len(sys.argv) < 2:
        sys.exit("Aufruf: python3 tools/make_blank.py <eingereichte.pdf> [ausgabe.pdf]")
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(
        HERE, "templates", "anmeldung_blank.pdf")

    d = fitz.open(src)
    p1, p2 = d[0], d[1]
    h1, h2 = p1.rect.height, p2.rect.height

    # --- Unterschrift (Bild) extrahieren + zur Redaction vormerken ---
    sig_rects = []
    for im in p2.get_images(full=True):
        xref = im[0]
        rects = p2.get_image_rects(xref)
        # Unterschrift sitzt im unteren Drittel (über der Unterschriftslinie)
        for r in rects:
            if r.y0 > h2 * 0.6:
                sig_rects.append(r)
                assets = os.path.join(HERE, "assets")
                os.makedirs(assets, exist_ok=True)
                pix = fitz.Pixmap(d, xref)
                if pix.n - pix.alpha >= 4:   # CMYK -> RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                # Soft-Mask (Transparenz) einrechnen, sonst schwarzer Block
                info = d.extract_image(xref)
                if info.get("smask"):
                    mask = fitz.Pixmap(d, info["smask"])
                    pix = fitz.Pixmap(pix, mask)
                pix.save(os.path.join(assets, "signature.png"))
                print(f"Unterschrift extrahiert -> assets/signature.png  (bbox {r})")

    # --- Seite 1: Jahr, Dokument-ID, Dezember-Kreuz, Betreiber, Kassenzeichen ---
    for term in ("2024", "2025", "2026", "2027", "2028"):
        for r in p1.search_for(term):
            if r.y0 < 320:  # oben = Jahr (unten steht der Vordruck-Footer)
                p1.add_redact_annot(r, fill=(1, 1, 1))
    for w in p1.get_text("words"):
        if w[4].isdigit() and len(w[4]) >= 18:   # abgabe-spezifische Dokument-ID
            p1.add_redact_annot(fitz.Rect(w[:4]), fill=(1, 1, 1))
    p1.add_redact_annot(_r(*DEC_BOX, h1), fill=(1, 1, 1))
    for box in BETREIBER_BOXES:
        p1.add_redact_annot(_r(*box, h1), fill=(1, 1, 1))

    # --- Seite 2: Zahlen, Datum, Unterschrift ---
    for y in NUM_Y:
        p2.add_redact_annot(_r(466, y - 3, 524, y + 10, h2), fill=(1, 1, 1))
    p2.add_redact_annot(_r(*DATE_BOX, h2), fill=(1, 1, 1))
    for r in sig_rects:
        p2.add_redact_annot(r + (-2, -2, 2, 2), fill=(1, 1, 1))

    p1.apply_redactions()
    p2.apply_redactions()
    d.save(out)
    print(f"Blanko-Vorlage gespeichert: {out}")


if __name__ == "__main__":
    main()
