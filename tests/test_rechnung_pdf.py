"""Das Rechnungs-PDF: was die Buchhaltung darauf finden muss.

Bis zum 7.8.2026 war dieses Modul ungeprüft. Anlass für diese Datei war eine
Rückfrage aus der Praxis: das Steuerbüro musste den eigentlichen
Rechnungsbetrag (Netto + USt) für jede Rechnung selbst bilden, weil er nirgends
stand – dazwischen lag nur die Beherbergungssteuer, die dort gar nicht
hingehört.

Geprüft wird am **erzeugten PDF**, nicht am Rechenweg. Ein Betrag, der stimmt,
aber nicht auf dem Blatt landet, nützt niemandem.
"""
import re

import fitz
import pytest

from app import rechnung_pdf

BETREIBER = {"name": "DS Apartments", "strasse": "Antonstraße",
             "hausnummer": "15", "plz": "01097", "ort": "Dresden",
             "steuernummer": "203/277/09284"}


def _pos(bezeichnung, brutto, ustsatz):
    netto = round(brutto / (1 + ustsatz), 2) if ustsatz else brutto
    return {"bezeichnung": bezeichnung, "brutto": brutto, "netto": netto,
            "ust": round(brutto - netto, 2), "ustsatz": ustsatz}


def _rechnung(positionen):
    netto = round(sum(p["netto"] for p in positionen if p["ustsatz"]), 2)
    ust = round(sum(p["ust"] for p in positionen), 2)
    durchlaufend = round(sum(p["brutto"] for p in positionen if not p["ustsatz"]), 2)
    return {"nummer": "76", "datum": "2026-08-07", "status": "festgeschrieben",
            "gast": "Anja Ernst", "wohnung_name": "Cottaer Straße",
            "anreise": "2026-08-01", "abreise": "2026-08-05",
            "empfaenger": {"name": "Anja Ernst", "strasse": "Musterweg 3",
                           "plz": "01067", "ort": "Dresden"},
            "positionen": positionen,
            "summen": {"netto": netto, "ust": ust, "durchlaufend": durchlaufend,
                       "brutto": round(netto + ust + durchlaufend, 2)}}


def _text(r):
    doc = fitz.open(stream=rechnung_pdf.bauen(r, BETREIBER), filetype="pdf")
    return "\n".join(seite.get_text() for seite in doc)


MIT_STEUER = [_pos("Übernachtung", 969.62, 0.07),
              _pos("Endreinigung", 95.00, 0.07),
              _pos("Beherbergungssteuer", 74.52, 0.0)]


# ------------------------------------------- Der eigentliche Rechnungsbetrag
def test_die_zwischensumme_der_leistung_steht_da():
    """Der Auslöser. Netto (994,98) + USt (69,64) = 1.064,62 – das ist der
    Rechnungsbetrag der Leistung. Ohne diese Zeile muss die Buchhaltung ihn für
    jede Rechnung selbst ausrechnen, weil dazwischen die Beherbergungssteuer
    steht, die nicht dazugehört."""
    t = _text(_rechnung(MIT_STEUER))
    assert "Beherbergungsleistungen" in t
    assert "1.064,62" in t


# ------------------------------------------------------------- Die Aufstellung
def test_die_aufstellung_zeigt_netto_satz_und_brutto():
    """Vier Spalten wie in der abgestimmten Vorlage: die Buchhaltung liest die
    Netto-Spalte, der Gast die Brutto-Spalte."""
    t = _text(_rechnung(MIT_STEUER))
    for kopf in ("Leistung", "Netto", "USt.", "Brutto"):
        assert kopf in t, f"Spalte {kopf} fehlt"
    for betrag in ("906,19", "969,62", "88,79", "95,00", "74,52"):
        assert betrag in t, f"{betrag} fehlt in der Aufstellung"


def test_die_betraege_tragen_ein_eurozeichen():
    """Die eingebauten PDF-Schriften kodierten nach Latin-1, „€" wurde dort
    still zu einem Punkt – deshalb stand früher „EUR" auf der Rechnung. Über
    den TextWriter geht das Zeichen selbst."""
    t = _text(_rechnung(MIT_STEUER))
    assert "1.139,14 €" in t
    assert "EUR" not in t


def test_die_reihenfolge_stimmt():
    """Erst die eigenen Leistungen, dann ihre Zwischensumme, dann die
    Beherbergungssteuer, dann der Gesamtbetrag. Stünde die Steuer davor, wäre
    die Zwischensumme keine."""
    t = _text(_rechnung(MIT_STEUER))
    assert (t.index("Endreinigung") < t.index("Beherbergungsleistungen")
            < t.index("Beherbergungssteuer Dresden") < t.index("GESAMTBETRAG"))


# ------------------------------------------------------- DIN 5008 Form A
def _mm(punkte):
    return punkte / 72 * 25.4


def _zeilen_mit_ort(r):
    """(Text, x, Grundlinie) je Textstück des erzeugten PDFs."""
    doc = fitz.open(stream=rechnung_pdf.bauen(r, BETREIBER), filetype="pdf")
    raus = []
    for block in doc[0].get_text("dict")["blocks"]:
        for zeile in block.get("lines", []):
            for stueck in zeile["spans"]:
                if stueck["text"].strip():
                    raus.append((stueck["text"], stueck["bbox"][0], stueck["bbox"][1]))
    return raus


def test_die_anschrift_sitzt_in_der_anschriftzone():
    """DIN 5008 Form A: das Anschriftfeld beginnt 27 mm unter der Blattkante,
    die **Anschriftzone ab 44,7 mm**. Steht der Empfänger tiefer, sitzt er im
    Fenster eines DIN-Umschlags nicht richtig – in der Vorlage stand er auf
    50,7 mm."""
    stuecke = _zeilen_mit_ort(_rechnung(MIT_STEUER))
    empfaenger = next(o for txt, _x, o in stuecke if txt.startswith("Anja Ernst"))
    assert 44.7 <= _mm(empfaenger) <= 50.0, f"Oberkante bei {_mm(empfaenger):.1f} mm"


def test_die_ruecksendeangabe_steht_ueber_der_anschriftzone():
    """Sie gehört in die Zusatz- und Vermerkzone (27,0–44,7 mm), sonst
    verdrängt sie die erste Anschriftzeile."""
    stuecke = _zeilen_mit_ort(_rechnung(MIT_STEUER))
    absender = next(o for txt, _x, o in stuecke if txt.startswith("DS Apartments ·"))
    assert _mm(absender) < 44.7, f"Rücksendeangabe bei {_mm(absender):.1f} mm"


def test_der_linke_rand_folgt_der_norm():
    """DIN 5008 setzt den Schreibbereich auf 24,1 mm. Die Vorlage hatte 22 mm."""
    stuecke = _zeilen_mit_ort(_rechnung(MIT_STEUER))
    linke = min(x for _t, x, _o in stuecke)
    assert abs(_mm(linke) - 24.1) < 0.6, f"linker Rand bei {_mm(linke):.1f} mm"


def test_der_titel_steht_unter_dem_empfaenger():
    """Wie in der ursprünglichen Fassung: die Überschrift gehört auf die
    Betreffzeile unter das Anschriftfeld, nicht darüber. Das Anschriftfeld
    endet nach DIN 5008 Form A bei 72 mm; die Betreffzeile folgt nach zwei
    Leerzeilen."""
    stuecke = _zeilen_mit_ort(_rechnung(MIT_STEUER))
    titel = next(o for txt, _x, o in stuecke if txt == "Rechnung")
    empfaenger = next(o for txt, _x, o in stuecke if txt.startswith("Anja Ernst"))
    assert titel > empfaenger
    assert 72 <= _mm(titel) <= 84, f"Betreffzeile bei {_mm(titel):.1f} mm"


def test_die_anbieterdaten_stehen_oben_rechts():
    stuecke = _zeilen_mit_ort(_rechnung(MIT_STEUER))
    name = next((x, o) for txt, x, o in stuecke if txt == "DS Apartments")
    assert _mm(name[1]) < 27, "nicht im Briefkopfbereich"
    assert name[0] > 300, "nicht in der rechten Blatthälfte"


# ------------------------------------------------------------------ Flächen
def _flaechen(r):
    """Gefüllte Flächen des erzeugten PDFs als (Farbe, Rechteck)."""
    doc = fitz.open(stream=rechnung_pdf.bauen(r, BETREIBER), filetype="pdf")
    return [(tuple(round(c, 3) for c in d["fill"]), d["rect"])
            for d in doc[0].get_drawings() if d.get("fill")]


def test_die_zwischensumme_ist_hinterlegt():
    """Sie hebt sich von den Einzelposten ab – sonst liest sie sich wie eine
    weitere Position."""
    treffer = [rechteck for farbe, rechteck in _flaechen(_rechnung(MIT_STEUER))
               if farbe == tuple(round(c, 3) for c in rechnung_pdf.KASTEN)]
    assert treffer, "Keine Hinterlegung gefunden"
    assert treffer[0].width > 400, "Die Fläche geht nicht über die ganze Tabelle"


def test_der_gesamtbetrag_steht_in_der_hausfarbe():
    treffer = [rechteck for farbe, rechteck in _flaechen(_rechnung(MIT_STEUER))
               if farbe == tuple(round(c, 3) for c in rechnung_pdf.PURPLE)]
    assert treffer, "Kein farbiger Kasten für den Gesamtbetrag"
    kasten = treffer[0]
    assert kasten.width < 300, "Der Kasten soll nur die rechte Hälfte einnehmen"
    assert 35 < kasten.height < 60, kasten.height


def test_ohne_durchlaufenden_posten_bleibt_die_hinterlegung_weg():
    """Ohne Beherbergungssteuer gibt es keine Zwischensumme – und damit auch
    nichts zu hinterlegen."""
    hell = tuple(round(c, 3) for c in rechnung_pdf.KASTEN)
    farben = [f for f, _r in _flaechen(_rechnung([_pos("Übernachtung", 400.00, 0.07)]))]
    assert hell not in farben


# ------------------------------------------------------------------- Logo
def test_ohne_logo_entsteht_trotzdem_eine_rechnung():
    doc = fitz.open(stream=rechnung_pdf.bauen(_rechnung(MIT_STEUER), BETREIBER),
                    filetype="pdf")
    assert doc[0].get_images() == []


def test_ein_kaputtes_logo_verhindert_keine_rechnung():
    """Ein fehlendes oder unlesbares Bild darf keinen Beleg blockieren."""
    betr = dict(BETREIBER, logo="logo/gibtsnicht.png")
    doc = fitz.open(stream=rechnung_pdf.bauen(_rechnung(MIT_STEUER), betr),
                    filetype="pdf")
    assert "GESAMTBETRAG" in doc[0].get_text()


def test_das_logo_landet_oben_links(tmp_path):
    """Gespeichert wird der Name relativ zum Medienordner – dieselbe Angabe
    zeigt das Bild in der Oberfläche unter /media/… und hier im PDF."""
    from app import paths
    bild = tmp_path / "media" / "logo"
    bild.mkdir(parents=True)
    doc = fitz.open()
    doc.new_page(width=200, height=80).draw_rect(fitz.Rect(0, 0, 200, 80), fill=(1, 0, 0))
    doc[0].get_pixmap().save(str(bild / "l.png"))
    alt = paths.DATA_DIR
    paths.DATA_DIR = str(tmp_path)
    try:
        betr = dict(BETREIBER, logo="logo/l.png")
        seite = fitz.open(stream=rechnung_pdf.bauen(_rechnung(MIT_STEUER), betr),
                          filetype="pdf")[0]
        bilder = seite.get_images()
        assert bilder, "Logo fehlt im PDF"
        kasten = seite.get_image_rects(bilder[0][0])[0]
        assert _mm(kasten.x0) < 30 and _mm(kasten.y0) < 30, kasten
    finally:
        paths.DATA_DIR = alt


def test_der_aufbau_folgt_der_vorlage():
    """Die Blöcke in der Reihenfolge der abgestimmten Beispielrechnung."""
    t = _text(_rechnung(MIT_STEUER))
    folge = ["Anja Ernst", "Rechnung", "Aufenthalt", "Leistung",
             "GESAMTBETRAG", "Steuerinformation", "Hinweis zur Beherbergungssteuer",
             "Steuerdaten", "Bankverbindung"]
    stellen = [t.index(x) for x in folge]
    assert stellen == sorted(stellen), dict(zip(folge, stellen))


def test_ohne_durchlaufenden_posten_braucht_es_keine_zwischensumme():
    """Steht nichts dazwischen, ist der Gesamtbetrag schon der
    Rechnungsbetrag – eine Zwischensumme wäre dieselbe Zahl zweimal."""
    t = _text(_rechnung([_pos("Übernachtung", 400.00, 0.07)]))
    # Das Wort steht weiter in der Steuerinformation („7 % Umsatzsteuer auf
    # Beherbergungsleistungen") – gemeint ist die Zeile in der Aufstellung.
    assert "Beherbergungsleistungen" not in t.splitlines()


# --------------------------------------------------- Nicht steuerbar ≠ steuerfrei
def test_der_durchlaufende_posten_heisst_nicht_steuerfrei():
    """Der Unterschied ist kein Wortklauben, er entscheidet die Buchung:

    * **steuerfrei** (§ 4 UStG) ist ein Umsatz – er ist Erlös und geht in die
      Umsatzsteuer-Voranmeldung.
    * **nicht steuerbar** als durchlaufender Posten (§ 10 Abs. 1 UStG) ist gar
      kein Entgelt – er gehört auf ein Verbindlichkeitskonto.

    Vorher stand „steuerfrei" in der Tabelle und „durchlaufender Posten" in der
    Fußnote: die Rechnung widersprach sich selbst."""
    t = _text(_rechnung(MIT_STEUER))
    assert "steuerfrei" not in t, "Weist die Buchhaltung in die falsche Richtung"
    assert "nicht steuerbar" in t
    assert "durchlaufender Posten" in t


def test_kein_steuersatz_an_der_beherbergungssteuer():
    """Solange offen ist, warum Booking.com 7 % abrechnet und die Satzung 6 %
    vorsieht, steht auf der Rechnung lieber kein Satz als ein falscher. Was
    dasteht, muss sich nachrechnen lassen."""
    t = _text(_rechnung(MIT_STEUER))
    zeile = [z for z in t.splitlines() if "Beherbergungssteuer" in z]
    assert zeile, "Die Position fehlt ganz"
    assert not any("%" in z for z in zeile), f"Satz an der Steuer: {zeile}"


# ------------------------------------------------------ Steuerlicher Hinweis
def test_der_steuerhinweis_nennt_entgelt_satz_und_steuerbetrag():
    """§ 14 Abs. 4 Nr. 8 UStG verlangt das Entgelt nach Steuersätzen
    aufgeschlüsselt sowie Steuersatz und Steuerbetrag. Ein ausgeschriebener Satz
    leistet das genauso wie eine Spaltentabelle – aber nur, wenn alle drei
    Zahlen darin vorkommen."""
    r = _rechnung(MIT_STEUER)
    t = _text(r)
    zeile = next(z for z in t.splitlines() if z.startswith("Netto "))
    assert "994,98" in zeile, "Der Nettobetrag fehlt"
    assert "69,64" in zeile, "Der Steuerbetrag fehlt"
    assert "1.064,62" in zeile, "Das Entgelt inkl. Steuer fehlt"
    assert "7 % Umsatzsteuer auf Beherbergungsleistungen:" in t, "Der Steuersatz fehlt"
    assert r["summen"]["brutto"] == 1139.14


def test_die_steuerinformation_rechnet_sich_auf():
    """Die Probe: Netto + USt. muss das genannte Brutto sein. Eine Angabe, die
    nicht aufgeht, ist schlimmer als keine."""
    t = _text(_rechnung(MIT_STEUER))
    zeile = next(z for z in t.splitlines() if z.startswith("Netto "))
    netto, ust, brutto = [float(x.replace(".", "").replace(",", "."))
                          for x in re.findall(r"\d[\d.]*,\d\d", zeile)]
    assert round(netto + ust, 2) == brutto


def test_zwei_steuersaetze_bekommen_zwei_zeilen():
    """Vorsorge: heute ist alles 7 %. Frühstück, Parkplatz oder Haustier sind
    19 % und brauchen eine eigene Zeile – sonst wäre die Aufschlüsselung nach
    Steuersätzen keine."""
    t = _text(_rechnung([_pos("Übernachtung", 400.00, 0.07),
                         _pos("Frühstück", 119.00, 0.19),
                         _pos("Beherbergungssteuer", 24.00, 0.0)]))
    zeilen = [z for z in t.splitlines() if z.startswith("Netto ")]
    assert len(zeilen) == 2, zeilen
    assert "7 % Umsatzsteuer" in t and "19 % Umsatzsteuer" in t
    assert any("100,00" in z for z in zeilen), "Netto zu 19 % (119,00 / 1,19) fehlt"


# ------------------------------------------------------------- Pflichtangaben
@pytest.mark.parametrize("pflicht", ["DS Apartments", "Anja Ernst", "203/277/09284",
                                     "07.08.2026", "76"])
def test_die_pflichtangaben_bleiben_auf_dem_blatt(pflicht):
    """§ 14 Abs. 4 UStG – beim Umbau des Layouts leicht zu verlieren."""
    assert pflicht in _text(_rechnung(MIT_STEUER))


def test_die_rechnung_bleibt_auf_einer_seite():
    """Der Steuernachweis kam neu dazu. Eine zweite Seite mit drei Zeilen
    darauf sieht nach Fehler aus."""
    doc = fitz.open(stream=rechnung_pdf.bauen(_rechnung(MIT_STEUER), BETREIBER),
                    filetype="pdf")
    assert doc.page_count == 1
