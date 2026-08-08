"""Händler und Betrag aus dem Belegtext lesen – die Fehler vom 8.8.2026.

Nach dem ersten großen Upload (31 Belege mit erkanntem Text) gemeldet: eine
Lexware-Rechnung stand als „Netto 34,80 €" in der Liste. Nachgemessen:

* **13 von 31** Belegen hießen „Netto" – fast keiner war von Netto. Ursache:
  `NETTO` stand in der Händlerliste und wurde als Teilzeichenkette irgendwo im
  Dokument gesucht. Auf jeder Rechnung steht „Nettobetrag", und in jeder
  Betragstabelle steht „Netto" als Spaltenkopf.
* **5** hießen „1/2" oder „1/1" – die Seitenzahl der PDF.
* Viele Beträge waren **Datumsangaben**: „31,12" (31.12.), „30,04" (30.04.),
  „07,05" (07.05.).

Die Texte hier sind nachgebaut, nicht die echten – echte Belege gehören nicht
ins Repository.
"""
from app import receipts


# ------------------------------------------------------------------ Händler
def test_die_netto_falle():
    """Der gemeldete Fall: eine Lexware-Rechnung, die „Netto" hieß."""
    text = ("Internet:\nE-Mail:\nwww.office.lexware.de\n"
            "lexoffice@haufe-lexware.net\n"
            "Haufe Service Center GmbH\nMunzinger Straße 9\n79111 Freiburg\n"
            "Nettobetrag 29,24 EUR\nMwSt 19% 5,56 EUR\nGesamtbetrag 34,80 EUR\n")
    assert receipts.guess_merchant(text) == "Haufe Service Center GmbH"


def test_ein_spaltenkopf_netto_macht_noch_keinen_discounter():
    """Telekom-Rechnung: „Netto" steht als Spaltenkopf in der Betragstabelle.
    Wortgrenzen allein reichen deshalb nicht – der Händler steht im Briefkopf."""
    text = ("Telekom Deutschland GmbH, 53171 Bonn\nDatum\nRechnungsnummer\n"
            "Position    Netto    Steuer    Brutto\n"
            "Mobilfunk   17,68     3,36     21,04\n")
    assert receipts.guess_merchant(text) == "Telekom Deutschland GmbH"


def test_ein_echter_discounterbon_wird_weiter_erkannt():
    """Auf dem Kassenbon steht der Name oben und groß. Dafür war die Liste da,
    und dafür bleibt sie."""
    text = "NETTO Marken-Discount\nFiliale 1234\nSUMME 27,81 EUR\n"
    assert receipts.guess_merchant(text) == "Netto"


def test_ein_discounter_tief_im_text_zaehlt_nicht():
    text = ("Haufe Service Center GmbH\nFreiburg\n" + "\n" * 3
            + "\n".join(f"Zeile {i}" for i in range(30))
            + "\nZahlung bei Netto möglich\n")
    assert receipts.guess_merchant(text) == "Haufe Service Center GmbH"


def test_die_seitenzahl_ist_kein_haendler():
    text = "1/2\nSmoobu GmbH\nPappelallee 78-79\n10437 Berlin\n"
    assert receipts.guess_merchant(text) == "Smoobu GmbH"


def test_beschriftungen_sind_keine_haendler():
    """„Rechnungsnr.:" stand an 6 Belegen ganz oben."""
    text = ("Rechnungsnr.:\nKundennr.:\nDatum:\n"
            "Stadtwerke Musterstadt GmbH\nMusterweg 1\n")
    assert receipts.guess_merchant(text) == "Stadtwerke Musterstadt GmbH"


def test_eine_netzadresse_ist_kein_haendler():
    text = "www.example.de\ninfo@example.de\nBeispiel Handels AG\n"
    assert receipts.guess_merchant(text) == "Beispiel Handels AG"


def test_der_ort_hinter_dem_komma_faellt_weg():
    text = "Telekom Deutschland GmbH, 53171 Bonn\n"
    assert receipts.guess_merchant(text) == "Telekom Deutschland GmbH"


def test_ohne_rechtsform_zaehlt_die_erste_brauchbare_zeile():
    """Behörden und Vereine tragen keine Rechtsform – lieber die Kopfzeile als
    gar nichts."""
    text = "Landeshauptstadt Dresden\nAmt für Geodaten und Kataster\n"
    assert receipts.guess_merchant(text) == "Landeshauptstadt Dresden"


def test_der_eigene_betrieb_wird_uebergangen():
    """Auf Portalabrechnungen steht der eigene Name oben – als Empfänger.
    Ohne diese Regel hieße der Beleg nach dem eigenen Betrieb."""
    text = ("DS Appartments & Suites\nDaniel Steinhauß\nMozartstraße 10\n"
            "Airbnb Ireland UC\n25 North Wall Quay, Dublin\n")
    assert receipts.guess_merchant(text, eigene=["DS Appartments & Suites",
                                                 "Daniel Steinhauß"]) \
        == "Airbnb Ireland UC"


def test_ohne_text_kein_haendler():
    assert receipts.guess_merchant("") == ""
    assert receipts.guess_merchant(None) == ""


# ------------------------------------------------------------------ Betrag
def test_ein_datum_ist_kein_betrag():
    """„31.12.2026" lieferte den Betrag „31,12". An den echten Belegen war das
    der haeufigste Fehler."""
    text = "Rechnungsdatum 31.12.2026\nLeistungszeitraum 01.12. - 31.12.2026\n"
    assert receipts.guess_amount(text) == ""


def test_der_gesamtbetrag_schlaegt_den_nettobetrag():
    text = ("Nettobetrag 29,24 EUR\nMwSt 19% 5,56 EUR\n"
            "Gesamtbetrag 34,80 EUR\n")
    assert receipts.guess_amount(text) == "34,80"


def test_zu_zahlen_schlaegt_alles_andere():
    text = ("Zwischensumme 100,00\nRabatt 10,00\nGesamt 90,00\n"
            "Zu zahlen 90,00 EUR\n")
    assert receipts.guess_amount(text) == "90,00"


def test_der_alte_fall_bleibt_richtig():
    """Die Prüfung aus test_belegscan darf nicht kippen."""
    assert receipts.guess_amount(
        "Rena Textilpflege GmbH - Rechnung 4711 - Summe 119,00 EUR") == "119,00"


def test_ein_datum_neben_einem_betrag_stoert_nicht():
    text = "Rechnung vom 07.05.2026\nGesamtbetrag 34,80 EUR\n"
    assert receipts.guess_amount(text) == "34,80"


def test_ohne_schluesselwort_gewinnt_der_groesste_betrag():
    text = "Artikel A 12,00\nArtikel B 7,50\n19,50\n"
    assert receipts.guess_amount(text) == "19,50"


def test_ein_datum_gewinnt_auch_im_rueckfall_nicht():
    """Ohne Schlüsselwort wurde der groesste Fund genommen – und ein Datum wie
    „31.12" schlug jeden echten Kleinbetrag."""
    text = "Beleg vom 31.12.2026\nArtikel 9,44\n"
    assert receipts.guess_amount(text) == "9,44"


def test_ohne_text_kein_betrag():
    assert receipts.guess_amount("") == ""
    assert receipts.guess_amount(None) == ""


def test_anschriftzeilen_des_empfaengers_sind_keine_haendler():
    """„01219 Dresden" und „Herr" standen an drei Belegen als Händler."""
    text = "Herr\n01219 Dresden\nBeispiel Versand GmbH\n"
    assert receipts.guess_merchant(text) == "Beispiel Versand GmbH"


def test_der_absender_darf_auch_weiter_unten_im_kopf_stehen():
    """Bei der Lexware-Rechnung steht der Absender erst nach dem
    Kleingedruckten – vorher gewann die Zeile „Tobias Lagatz"."""
    text = ("Internet:\nE-Mail:\nwww.office.lexware.de\nlexoffice@haufe.net\n"
            "Registergericht Freiburg HRB 5718 Geschäftsführung:\n"
            "Tobias Lagatz, Christa van der Burgh\nGläubiger-ID: DE68ZZZ\n"
            "GLN-Nr.: 4024896000001\nDie rechtsgeschäftliche Durchführung\n"
            "erfolgt durch die Haufe Service Center GmbH im eigenen Namen\n"
            "Rechnung Dritter (Kommission). Kommittenten sind u. a.\n"
            "ControllingWissen AG, Schäffer-Poeschel GmbH.\n"
            "Haufe Service Center GmbH\nMunzinger Straße 9\n")
    assert receipts.guess_merchant(text) == "Haufe Service Center GmbH"


def test_die_beschriftung_darf_auf_einer_eigenen_zeile_stehen():
    """Aus einer PDF-Tabelle kommen Beschriftung und Wert getrennt:
    „Fälliger Gesamtbetrag" / „EUR 59,33"."""
    text = ("EUR 440,00\nEUR 52,80\nEUR 6,53\nFälliger Gesamtbetrag\nEUR 59,33\n")
    assert receipts.guess_amount(text) == "59,33"


def test_ein_bruchstueck_ist_kein_firmenname():
    """Bei mehrzeilig gesetztem Namen blieb „GmbH wy" übrig."""
    text = "Flugplatz\nRothenburg / Görlitz 2\nGmbH wy\n"
    assert receipts.guess_merchant(text) == "Flugplatz"


# ------------------------------------------- Bestehende Belege nachlesen
def _beleg(bid, merchant, amount, text, hand=None):
    from app import db
    satz = {"id": bid, "uploader": "x", "ts": "2026-08-08T10:00:00",
            "photo": "p.jpg", "merchant": merchant, "amount": amount,
            "ocr_text": text, "datum": "", "kategorie": ""}
    if hand:
        satz["hand"] = hand
    from app import db as _db
    _db.anlegen("belege", satz)
    return satz


_LEX = ("Haufe Service Center GmbH\nMunzinger Straße 9\n"
        "Gesamt Netto\n34,80\nMwSt. 19%\n6,61\nGesamtbetrag EUR\n41,41\n")


def test_nachlesen_findet_die_falschen_angaben():
    """Die 31 bereits hochgeladenen Belege tragen die alten Fehlgriffe. Ohne
    Nachlesen muesste jeder von Hand berichtigt werden."""
    _beleg("q1", "Netto", "34,80", _LEX)
    aenderungen = receipts.nachlesen(eigene=[])
    assert len(aenderungen) == 1
    a = aenderungen[0]
    assert a["alt"] == ("Netto", "34,80")
    assert a["neu"] == ("Haufe Service Center GmbH", "41,41")


def test_was_schon_stimmt_taucht_nicht_auf():
    _beleg("q1", "Smoobu GmbH", "73,78", "Smoobu GmbH\nGesamtbetrag 73,78 EUR\n")
    assert receipts.nachlesen(eigene=[]) == []


def test_von_hand_gepflegtes_bleibt_unangetastet():
    """Sonst nimmt das Nachlesen eine Korrektur wieder zurueck – der Fehler,
    den `konto.zuordnen` schon einmal vermieden hat."""
    _beleg("q1", "Lexware", "41,41", _LEX, hand=["merchant"])
    a = receipts.nachlesen(eigene=[])
    # Der Betrag darf geaendert werden, der Haendler nicht.
    assert a == [] or a[0]["neu"][0] == "Lexware"


def test_ohne_erkannten_text_passiert_nichts():
    _beleg("q1", "Irgendwas", "1,00", "")
    assert receipts.nachlesen(eigene=[]) == []


def test_uebernehmen_schreibt_die_werte():
    from app import db
    _beleg("q1", "Netto", "34,80", _LEX)
    receipts.uebernehmen(receipts.nachlesen(eigene=[]))
    r = db.holen("belege", "q1")
    assert r["merchant"] == "Haufe Service Center GmbH" and r["amount"] == "41,41"


def test_eine_handkorrektur_wird_vermerkt():
    """Damit ein spaeteres Nachlesen sie nicht ueberschreibt."""
    from app import db
    _beleg("q1", "Netto", "34,80", _LEX)
    receipts.update_receipt("q1", merchant="Lexware", von_hand=True)
    assert "merchant" in (db.holen("belege", "q1").get("hand") or [])


def test_eine_teilbetragszeile_verliert_gegen_dieselbe_summenzeile():
    """Schaerfer als `test_der_gesamtbetrag_schlaegt_den_nettobetrag`: dort
    entschied schon die Reihenfolge der Schluesselwoerter. Hier tragen beide
    Zeilen dasselbe Wort „Summe" – nur der Netto-Ausschluss entscheidet."""
    text = "Summe netto 29,24 EUR\nSumme 34,80 EUR\n"
    assert receipts.guess_amount(text) == "34,80"


def test_der_eigene_name_wird_auch_mit_rechtsform_uebergangen():
    """Schaerfer als `test_der_eigene_betrieb_wird_uebergangen`: dort trug die
    eigene Zeile keine Rechtsform und fiel ohnehin durch."""
    text = ("DS Apartments GmbH\nMozartstraße 10\n01219 Dresden\n"
            "Airbnb Ireland UC\n")
    assert receipts.guess_merchant(text, eigene=["DS Apartments GmbH"]) \
        == "Airbnb Ireland UC"


def test_der_absender_zaehlt_nur_im_kopf_nicht_auf_seite_drei():
    """Schaerfer als `test_ein_discounter_tief_im_text_zaehlt_nicht`: hier
    steht weiter unten eine echte Firmenzeile, kein Discountername."""
    text = ("Landeshauptstadt Dresden\nAmt für Geodaten\n"
            + "\n".join(f"Zeile {i}" for i in range(40))
            + "\nFremde Handels GmbH\n")
    assert receipts.guess_merchant(text) == "Landeshauptstadt Dresden"


def test_der_blosse_vorname_ist_kein_ausschluss():
    """„Daniel" allein wuerde auch einen Lieferanten „Daniel Mueller GmbH"
    verwerfen – der Betrieb wird am Nachnamen erkannt, nicht am Vornamen."""
    cfg = {"betreiber": {"name": "Steinhauß", "zusatz": "Daniel",
                         "strasse": "Mozartstr."}}
    namen = receipts.eigene_namen(cfg)
    assert "Daniel" not in namen
    assert "Steinhauß" in namen and "Daniel Steinhauß" in namen
