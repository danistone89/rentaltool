#!/usr/bin/env python3
"""Erzeugt die Blanko-Vorlage aus einer eingereichten Steueranmeldungs-PDF.

Dresden bietet das Formular (Vdr 22.040/5) nur über ein Online-System an – es
gibt keinen Blanko-Download. Dieses Skript nimmt eine bereits ausgefüllte,
eingereichte PDF und entfernt per Redaction alle variablen Werte, sodass eine
wiederverwendbare Blanko-Vorlage entsteht (Betreiberdaten, Kassenzeichen und das
Layout bleiben erhalten).

Aufruf:
    python3 tools/make_blank.py <eingereichte.pdf> [ausgabe.pdf]

Standard-Ausgabe: templates/anmeldung_blank.pdf

Benötigt PyMuPDF (pip install pymupdf).

ACHTUNG: Die erzeugte Vorlage enthält deine Betreiberdaten + Kassenzeichen und
gehört NICHT in ein öffentliches Repository (ist in .gitignore ausgeschlossen).
"""
import os
import sys
import fitz

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Baselines (PDF-Koordinaten) der zu entfernenden Werte – passend zum amtlichen
# Layout. Bei einer neuen Formularversion ggf. anpassen.
NUM_Y = [788.1, 725.7, 691.7, 667.6, 619.4, 559.9, 537.2]  # Seite 2, Zahlen
DEC_BOX = (409, 402, 421, 411)  # Dezember-Kreuz (Seite 1)
DATE_BOX = (54, 191, 135, 205)  # Datum unten links (Seite 2)


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

    # Seite 1: Jahresangabe oben (nicht den Vdr-Footer) entfernen
    for term in ("2024", "2025", "2026", "2027", "2028"):
        for r in p1.search_for(term):
            if r.y0 < 320:  # oberer Bereich = Jahr; unten steht der Vordruck-Footer
                p1.add_redact_annot(r, fill=(1, 1, 1))
    # abgabe-spezifische Dokument-ID (lange Ziffernfolge) entfernen
    for w in p1.get_text("words"):
        token = w[4]
        if token.isdigit() and len(token) >= 18:
            p1.add_redact_annot(fitz.Rect(w[:4]), fill=(1, 1, 1))
    # Dezember-Kreuz
    p1.add_redact_annot(_r(*DEC_BOX, h1), fill=(1, 1, 1))

    # Seite 2: Zahlenwerte + Datum
    for y in NUM_Y:
        p2.add_redact_annot(_r(466, y - 3, 524, y + 10, h2), fill=(1, 1, 1))
    p2.add_redact_annot(_r(*DATE_BOX, h2), fill=(1, 1, 1))

    p1.apply_redactions()
    p2.apply_redactions()
    d.save(out)
    print(f"Blanko-Vorlage gespeichert: {out}")


if __name__ == "__main__":
    main()
