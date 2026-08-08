"""B8: ist überhaupt alles da?

B7 zeigt Zahlen. Ob sie etwas wert sind, hängt daran, ob *alle* Bewegungen
erfasst sind – und das sieht man ihnen nicht an. Ein fehlender Auszugsmonat
macht keinen Fehler, er macht ein falsches, plausibel aussehendes Ergebnis.

Die Kopfzeilen des DKB-Auszugs tragen alles Nötige (Zeitraum, Stichtag,
Kontostand); sie wurden beim Einlesen bisher übersprungen.
"""
from app import konto, kontoauszug as ka, vollstaendigkeit as vs, zuordnung as z

GIRO_KOPF = '''"DKB-Business";"DE62120300001310062102"
"Zeitraum:";"{von} - {bis}"
"Kontostand vom {bis}:";"{stand}"
""
"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"
'''

ZEILE = ('"{tag}";"{tag}";"Gebucht";"Wer";"Wem";"Zweck {nr}";"{typ}";'
         '"DE75100500001584049444";"{betrag}";"";"";""\n')


def _auszug(von, bis, stand, zeilen=()):
    text = GIRO_KOPF.format(von=von, bis=bis, stand=stand)
    for i, (tag, betrag) in enumerate(zeilen):
        text += ZEILE.format(tag=tag, nr=i, betrag=betrag,
                             typ="Eingang" if not betrag.startswith("-") else "Ausgang")
    return text


# ------------------------------------------------------- B8a: die Kopfdaten
def test_die_kopfdaten_werden_gelesen():
    kopf = ka.kopfdaten(ka._zeilen(_auszug("01.01.2026", "31.01.2026", "1.000,00 €")),
                        ka.GESCHAEFT)
    assert kopf["von"] == "2026-01-01" and kopf["bis"] == "2026-01-31"
    assert kopf["stand"] == 1000.0


def test_ein_negativer_kontostand_wird_gelesen():
    kopf = ka.kopfdaten(ka._zeilen(_auszug("01.01.2026", "31.01.2026", "-250,50 €")),
                        ka.GESCHAEFT)
    assert kopf["stand"] == -250.5


def test_ohne_kopfzeilen_bleibt_es_leer():
    """Ein Auszug ohne Vorspann darf nichts behaupten."""
    kopf = ka.kopfdaten([["Buchungsdatum", "Betrag (€)"]], ka.GESCHAEFT)
    assert kopf["stand"] is None and kopf["bis"] == ""


def test_der_import_schreibt_die_kopfdaten_mit():
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €",
                              [("15.01.26", "100")]))
    a = vs.auszuege()
    assert len(a) == 1
    assert a[0]["stand"] == 1000.0 and a[0]["bis"] == "2026-01-31"


def test_derselbe_auszug_zweimal_gibt_keinen_zweiten_satz():
    text = _auszug("01.01.2026", "31.01.2026", "1.000,00 €", [("15.01.26", "100")])
    konto.importieren(text)
    konto.importieren(text)
    assert len(vs.auszuege()) == 1


# ------------------------------------------------------- B8a: der Saldosprung
def test_ein_stimmiger_saldo_meldet_nichts():
    """1.000 € Ende Januar, 1.100 € Ende Februar, 100 € Bewegung dazwischen."""
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €",
                              [("15.01.26", "500")]))
    konto.importieren(_auszug("01.02.2026", "28.02.2026", "1.100,00 €",
                              [("15.02.26", "100")]))
    assert vs.saldospruenge() == []


def test_eine_fehlende_bewegung_faellt_auf():
    """Der eigentliche Zweck: man weiss nicht WELCHE fehlt, aber DASS etwas
    fehlt. Ohne diese Probe sieht ein Monat mit Luecke normal aus."""
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €",
                              [("15.01.26", "500")]))
    konto.importieren(_auszug("01.02.2026", "28.02.2026", "1.500,00 €",
                              [("15.02.26", "100")]))
    sprung = vs.saldospruenge()[0]
    assert sprung["erwartet"] == 1100.0 and sprung["gemeldet"] == 1500.0
    assert sprung["differenz"] == 400.0


def test_mit_nur_einem_auszug_wird_nichts_behauptet():
    """Ohne Vergleichspunkt laesst sich der Saldo nicht pruefen – das ist kein
    Befund, sondern ein fehlender Anfangswert."""
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €",
                              [("15.01.26", "500")]))
    assert vs.saldospruenge() == []


def test_verschiedene_konten_werden_nicht_vermischt():
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €",
                              [("15.01.26", "500")]))
    from app import db
    db.anlegen(vs.TABELLE, {"id": "x", "konto": "VISA 8136", "von": "2026-02-01",
                            "bis": "2026-02-28", "stand": 99.0,
                            "erfasst": "2026-08-08T10:00:00"})
    assert vs.saldospruenge() == []


# ------------------------------------------------------- B8b: Zeitraumluecken
def test_ein_durchgehender_zeitraum_meldet_nichts():
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €"))
    konto.importieren(_auszug("01.02.2026", "28.02.2026", "1.000,00 €"))
    assert vs.luecken() == []


def test_ein_fehlender_monat_faellt_auf():
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €"))
    konto.importieren(_auszug("01.03.2026", "31.03.2026", "1.000,00 €"))
    luecke = vs.luecken()[0]
    assert luecke["von"] == "2026-02-01" and luecke["bis"] == "2026-02-28"


def test_ueberlappende_auszuege_sind_keine_luecke():
    """Ueberlappung ist der Normalfall – die Dublettenpruefung faengt sie ab."""
    konto.importieren(_auszug("01.01.2026", "15.02.2026", "1.000,00 €"))
    konto.importieren(_auszug("01.02.2026", "28.02.2026", "1.000,00 €"))
    assert vs.luecken() == []


def test_ein_einzelner_auszug_hat_keine_luecke():
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €"))
    assert vs.luecken() == []


# ------------------------------------------------------- B8c: offene Arbeiten
def _bewegung(betrag, gegenpartei, bid, datum="2026-06-12", kategorie=""):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": gegenpartei,
            "text": "", "konto": "giro", "umbuchung": False, "kategorie": kategorie}
    db.anlegen(konto.TABELLE, satz)
    return satz


def test_die_offenen_arbeiten_stehen_zusammen():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")   # Rest 40
    _bewegung(-50.0, "Unbekannt", "w2")                              # ohne Kategorie
    offen = vs.offene_arbeiten()
    assert offen["rest"] == 1
    assert offen["ohne_kategorie"] == 1


def test_eine_fertige_bewegung_taucht_nirgends_auf():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -100.0, "Wäscherei (Rena)")
    offen = vs.offene_arbeiten()
    assert offen["rest"] == 0 and offen["ohne_kategorie"] == 0


def test_fehlende_belege_werden_mitgezaehlt():
    _bewegung(-100.0, "Baumarkt", "w1", kategorie="Wäscherei (Rena)")
    assert vs.offene_arbeiten()["ohne_beleg"] == 1


def test_posten_ohne_kategorie_werden_mitgezaehlt():
    """Sie entstanden vor B6 und tauchen in keiner Auswertung auf."""
    from app import db
    b = _bewegung(1000.0, "Booking.com BV", "w1")
    db.anlegen(z.TABELLE, {"id": "p1", "bewegung_id": "w1", "art": z.KATEGORIE,
                           "ziel_id": "", "kategorie": "", "betrag": -790.27,
                           "notiz": "", "angelegt": "2026-06-01T10:00:00"})
    assert vs.offene_arbeiten()["posten_ohne_kategorie"] == 1


# ------------------------------------------------------------ Der Gesamtbefund
def test_der_befund_nennt_was_geprueft_wurde():
    """Bewusst kein Ampel-Urteil: „alles in Ordnung" waere eine Behauptung
    ueber Daten, die das Werkzeug nicht kennen kann."""
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €"))
    b = vs.befund()
    assert set(b) >= {"auszuege", "saldospruenge", "luecken", "offene_arbeiten"}
    assert b["auszuege"] == 1


def test_ohne_auszuege_sagt_der_befund_das_auch():
    b = vs.befund()
    assert b["auszuege"] == 0
    assert b["saldo_pruefbar"] is False


def test_die_zahlen_ueberschneiden_sich_nicht():
    """Sonst zaehlt eine angefangene Bewegung zweimal und die Summe der Zahlen
    ist groesser als die Arbeit."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    offen = vs.offene_arbeiten()
    assert offen["rest"] == 1 and offen["ohne_kategorie"] == 0


def test_der_stichtag_selbst_zaehlt_nicht_nochmal():
    """Die Bewegungen des Stichtags stecken schon im alten Kontostand. Sie
    erneut zu zaehlen erfaende einen Saldosprung, wo keiner ist."""
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €",
                              [("31.01.26", "200")]))
    konto.importieren(_auszug("01.02.2026", "28.02.2026", "1.100,00 €",
                              [("15.02.26", "100")]))
    assert vs.saldospruenge() == []


def test_ein_auszug_ohne_vorspann_wird_nicht_gemerkt():
    """Ohne Kontostand gibt es nichts zu vergleichen – ein Satz mit stand=None
    waere ein Pruefpunkt, der nichts pruefen kann."""
    ohne = ('"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";'
            '"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";'
            '"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"\n'
            + ZEILE.format(tag="15.01.26", nr=1, betrag="100", typ="Eingang"))
    konto.importieren(ohne)
    assert vs.auszuege() == []


# ------------------------------------------------------------- Die Anzeige
def _in_client(bauen):
    from nicegui import ui
    from nicegui.client import Client
    with Client(lambda: None):
        with ui.card():
            bauen()


def test_der_befund_laesst_sich_zeichnen():
    from app.ui import ueberblick as ui_ub
    konto.importieren(_auszug("01.01.2026", "31.01.2026", "1.000,00 €",
                              [("15.01.26", "500")]))
    konto.importieren(_auszug("01.03.2026", "31.03.2026", "1.500,00 €",
                              [("15.03.26", "100")]))
    _in_client(ui_ub._vollstaendigkeit)


def test_der_befund_haelt_auch_einen_leeren_bestand_aus():
    from app.ui import ueberblick as ui_ub
    _in_client(ui_ub._vollstaendigkeit)


# --------------------------------------------------- Die Kreditkarten-Probe
# Auf dem Girokonto steht EINE Sammelbuchung „Kreditkartenabrechnung"; im
# VISA-Auszug stehen dieselben Betraege einzeln plus ein „Ausgleich
# Kreditkarte" in gleicher Hoehe. Beide Umbuchungen sind neutral, die
# Einzelkaeufe tragen die Ausgabe. Die Probe: deckt der Ausgleich genau die
# Kaeufe seit dem letzten Ausgleich?
#
# An den echten Daten (8.8.2026) traf das in 5 von 6 Abrechnungen auf den
# Cent; die erste wich um 22,00 EUR ab, weil die Kaeufe davor vor dem
# Importzeitraum lagen. Genau deshalb ist der erste Zyklus nicht pruefbar.
def _karte(betrag, text, bid, datum, umbuchung=False, konto_name="VISA 8136"):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": text,
            "text": text, "konto": konto_name, "umbuchung": umbuchung,
            "kategorie": ""}
    db.anlegen(konto.TABELLE, satz)
    return satz


def test_ein_stimmiger_abrechnungszyklus_meldet_nichts():
    _karte(100.0, "Ausgleich Kreditkarte gem", "a0", "2026-01-22", umbuchung=True)
    _karte(-30.0, "Rossmann", "k1", "2026-02-05")
    _karte(-26.93, "dm", "k2", "2026-02-10")
    _karte(56.93, "Ausgleich Kreditkarte gem", "a1", "2026-02-20", umbuchung=True)
    proben = [p for p in vs.kartenproben() if p["pruefbar"]]
    assert len(proben) == 1 and proben[0]["differenz"] == 0.0


def test_eine_fehlende_kartenbuchung_faellt_auf():
    """Der Fall aus dem Alltag: die Sammelbuchung ist da, der Kartenauszug
    unvollstaendig – dann fehlt eine Ausgabe im Ergebnis."""
    _karte(100.0, "Ausgleich Kreditkarte gem", "a0", "2026-01-22", umbuchung=True)
    _karte(-30.0, "Rossmann", "k1", "2026-02-05")
    _karte(56.93, "Ausgleich Kreditkarte gem", "a1", "2026-02-20", umbuchung=True)
    p = [x for x in vs.kartenproben() if x["pruefbar"]][0]
    assert p["kaeufe"] == -30.0 and p["ausgleich"] == 56.93
    assert p["differenz"] == 26.93


def test_der_erste_zyklus_ist_nicht_pruefbar():
    """Vor dem ersten Ausgleich fehlt der Anfangspunkt – an den echten Daten
    wich er um 22,00 EUR ab, weil die Dezemberkaeufe davor lagen."""
    _karte(-30.0, "Rossmann", "k1", "2026-01-05")
    _karte(185.68, "Ausgleich Kreditkarte gem", "a1", "2026-01-22", umbuchung=True)
    proben = vs.kartenproben()
    assert len(proben) == 1 and proben[0]["pruefbar"] is False


def test_ohne_karte_gibt_es_keine_probe():
    _bewegung(-100.0, "Baumarkt", "w1")
    assert vs.kartenproben() == []


# ---------------------------------- Sammelbuchung ohne Kartenauszug
def test_eine_sammelbuchung_ohne_kartenauszug_faellt_auf():
    """Genau die Frage vom 8.8.2026: „auf dem Bankimport muesste es eine
    Sammelbuchung zu einem Kreditkartenbelegmonat geben." Ist sie da, der
    Kartenauszug aber nicht, fehlen alle Einzelausgaben im Ergebnis."""
    from app import db
    db.anlegen(konto.TABELLE, {"id": "g1", "datum": "2026-01-26", "betrag": -185.68,
                               "gegenpartei": "Deutsche Kreditbank Berlin",
                               "text": "KREDITKARTENABRECHNUNG VISA -ABR. 4998",
                               "konto": "DE62", "umbuchung": True, "kategorie": ""})
    offen = vs.sammelbuchungen_ohne_karte()
    assert len(offen) == 1 and offen[0]["betrag"] == -185.68


def test_mit_passendem_ausgleich_ist_alles_gut():
    from app import db
    db.anlegen(konto.TABELLE, {"id": "g1", "datum": "2026-01-26", "betrag": -185.68,
                               "gegenpartei": "Deutsche Kreditbank Berlin",
                               "text": "KREDITKARTENABRECHNUNG VISA -ABR. 4998",
                               "konto": "DE62", "umbuchung": True, "kategorie": ""})
    _karte(185.68, "Ausgleich Kreditkarte gem", "a1", "2026-01-22", umbuchung=True)
    assert vs.sammelbuchungen_ohne_karte() == []


def test_ein_anderer_betrag_gilt_nicht_als_passend():
    from app import db
    db.anlegen(konto.TABELLE, {"id": "g1", "datum": "2026-01-26", "betrag": -185.68,
                               "gegenpartei": "DKB", "text": "KREDITKARTENABRECHNUNG",
                               "konto": "DE62", "umbuchung": True, "kategorie": ""})
    _karte(56.93, "Ausgleich Kreditkarte gem", "a1", "2026-01-22", umbuchung=True)
    assert len(vs.sammelbuchungen_ohne_karte()) == 1


def test_zwei_zyklen_werden_nicht_vermischt():
    """Ohne untere Grenze zaehlten die Kaeufe des ersten Zyklus im zweiten
    nochmal mit – jede zweite Abrechnung saehe nach Fehlbetrag aus."""
    _karte(-40.0, "Rossmann", "k1", "2026-01-05")
    _karte(40.0, "Ausgleich Kreditkarte gem", "a1", "2026-01-22", umbuchung=True)
    _karte(-25.0, "dm", "k2", "2026-02-05")
    _karte(25.0, "Ausgleich Kreditkarte gem", "a2", "2026-02-20", umbuchung=True)
    zweiter = [p for p in vs.kartenproben() if p["pruefbar"]][0]
    assert zweiter["kaeufe"] == -25.0 and zweiter["anzahl"] == 1
    assert zweiter["differenz"] == 0.0


# ------------------------------- Beide Auszuege in einem Zug (8.8.2026)
KARTE_CSV = ('"Karte";"DKB-VISA-Business-Card";"4998 •••• •••• 8136"\n""\n'
             '"Saldo vom 20.02.2026:";"-0 EUR"\n""\n'
             '"Belegdatum";"Wertstellung";"Status";"Beschreibung";"Umsatztyp";'
             '"Betrag (€)";"Fremdwährungsbetrag"\n'
             '"20.02.26";"20.02.26";"Gebucht";"Ausgleich Kreditkarte gem";'
             '"Lastschrift";"56,93";""\n'
             '"05.02.26";"06.02.26";"Gebucht";"Rossmann 2424";"Im Geschäft";'
             '"-30";""\n'
             '"08.02.26";"09.02.26";"Gebucht";"dm";"Im Geschäft";"-26,93";""\n')


def test_beide_formate_landen_im_selben_bestand():
    """Girokonto und Karte gehen ueber dasselbe Feld – das Format wird an der
    Spaltenzeile erkannt („Buchungsdatum" gegen „Belegdatum")."""
    konto.importieren(_auszug("01.02.2026", "28.02.2026", "1.000,00 €",
                              [("24.02.26", "-56,93")]))
    konto.importieren(KARTE_CSV)
    assert sorted(konto.konten()) == ["DE62120300001310062102", "VISA 8136"]


def test_erst_die_bank_dann_die_karte_loest_den_hinweis_auf():
    """Der Ablauf aus dem Betrieb: erst den Bankmonat, dann den Kartenauszug.
    Nach dem ersten Schritt fehlt der Kartenauszug und wird gemeldet, nach dem
    zweiten nicht mehr."""
    from app import db
    db.anlegen(konto.TABELLE, {"id": "g1", "datum": "2026-02-24", "betrag": -56.93,
                               "gegenpartei": "Deutsche Kreditbank Berlin",
                               "text": "KREDITKARTENABRECHNUNG VISA -ABR. 4998",
                               "konto": "DE62", "umbuchung": True, "kategorie": ""})
    assert len(vs.sammelbuchungen_ohne_karte()) == 1
    konto.importieren(KARTE_CSV)
    assert vs.sammelbuchungen_ohne_karte() == []
    # Und der Ausgleich deckt genau die beiden Kaeufe.
    p = vs.kartenproben()[0]
    assert p["ausgleich"] == 56.93 and p["kaeufe"] == -56.93


def test_die_kontoseite_laesst_sich_nach_dem_umbau_zeichnen():
    """Rauchprobe fuer das mehrfachfaehige Upload-Feld."""
    from app.ui import kontoblatt
    konto.importieren(_auszug("01.02.2026", "28.02.2026", "1.000,00 €",
                              [("24.02.26", "-56,93")]))
    _in_client(kontoblatt.render_konto)


def test_der_kartensaldo_steht_in_eur_nicht_in_euro_zeichen():
    """Am echten VISA-Auszug vom 8.8.2026 aufgefallen: der Vorspann schreibt
    „-548,86 EUR". `betrag` kannte nur „€" – der Kartensaldo blieb still leer
    und die Saldoprobe lief fuer die Karte nie."""
    assert ka.betrag("-548,86 EUR") == -548.86
    assert ka.betrag("-0 EUR") == 0.0
    assert ka.betrag("5.765,34 €") == 5765.34


def test_der_kartenauszug_wird_als_pruefpunkt_gemerkt():
    konto.importieren(KARTE_CSV)
    a = [x for x in vs.auszuege() if x["konto"] == "VISA 8136"]
    assert len(a) == 1 and a[0]["stand"] == 0.0 and a[0]["bis"] == "2026-02-20"


# --------- Der Fehler, den erst die echten Exporte zeigten (8.8.2026)
GIRO_MIT_STICHTAG = '''"DKB-Business";"DE62120300001310062102"
"Zeitraum:";"{von} - {bis}"
"Kontostand vom {stichtag}:";"{stand}"
""
"Buchungsdatum";"Wertstellung";"Status";"Zahlungspflichtige*r";"Zahlungsempfänger*in";"Verwendungszweck";"Umsatztyp";"IBAN";"Betrag (€)";"Gläubiger-ID";"Mandatsreferenz";"Kundenreferenz"
'''


def _export(von, bis, stichtag, stand, zeilen=()):
    text = GIRO_MIT_STICHTAG.format(von=von, bis=bis, stichtag=stichtag, stand=stand)
    for i, (tag, betrag) in enumerate(zeilen):
        text += ZEILE.format(tag=tag, nr=i, betrag=betrag,
                             typ="Eingang" if not betrag.startswith("-") else "Ausgang")
    return text


def test_der_kontostand_gehoert_zum_stichtag_nicht_zum_zeitraum():
    """Die DKB schreibt IMMER den heutigen Stand, egal welchen Zeitraum man
    exportiert. Am 8.8.2026 trugen beide Dateien (Jan–Feb und Mär–Aug)
    denselben Stand vom 08.08."""
    kopf = ka.kopfdaten(ka._zeilen(_export("01.01.2026", "28.02.2026",
                                           "08.08.2026", "2.428,44 €")),
                        ka.GESCHAEFT)
    assert kopf["bis"] == "2026-02-28"
    assert kopf["stichtag"] == "2026-08-08"


def test_zwei_ausschnitte_desselben_downloads_werden_nicht_verglichen():
    """DER Fehler: beide tragen denselben Stand vom selben Tag. Sie zu
    vergleichen ergaebe eine erfundene Differenz in Hoehe aller Umsaetze
    dazwischen – genau die falsche, plausibel aussehende Zahl, gegen die B8
    gebaut ist."""
    konto.importieren(_export("01.01.2026", "28.02.2026", "08.08.2026",
                              "2.428,44 €", [("15.01.26", "500")]))
    konto.importieren(_export("01.03.2026", "08.08.2026", "08.08.2026",
                              "2.428,44 €", [("15.04.26", "300")]))
    assert len(vs.auszuege()) == 1        # ein Stichtag, ein Pruefpunkt
    assert vs.saldospruenge() == []
    assert vs.befund()["saldo_pruefbar"] is False


def test_zwei_downloads_an_verschiedenen_tagen_werden_verglichen():
    """So funktioniert die Probe wirklich: beim naechsten Download."""
    konto.importieren(_export("01.01.2026", "31.01.2026", "31.01.2026",
                              "1.000,00 €", [("15.01.26", "500")]))
    konto.importieren(_export("01.02.2026", "28.02.2026", "28.02.2026",
                              "1.100,00 €", [("15.02.26", "100")]))
    assert vs.befund()["saldo_pruefbar"] is True
    assert vs.saldospruenge() == []


def test_und_meldet_dann_auch_eine_luecke():
    konto.importieren(_export("01.01.2026", "31.01.2026", "31.01.2026",
                              "1.000,00 €", [("15.01.26", "500")]))
    konto.importieren(_export("01.02.2026", "28.02.2026", "28.02.2026",
                              "1.500,00 €", [("15.02.26", "100")]))
    assert vs.saldospruenge()[0]["differenz"] == 400.0


def test_der_kartenauszug_bekommt_seinen_zeitraumbeginn_aus_den_umsaetzen():
    """Der VISA-Auszug hat keine „Zeitraum"-Zeile. Der frueheste Umsatz ist die
    ehrlichste Angabe – alles davor steht nicht in der Datei."""
    konto.importieren(KARTE_CSV)
    a = [x for x in vs.auszuege() if x["konto"] == "VISA 8136"][0]
    assert a["von"] == "2026-02-05"


def test_zwei_ausschnitte_desselben_tages_decken_zusammen_den_zeitraum():
    """Am echten Export: Jan–Feb und Mär–Aug, beide mit Stichtag 08.08. Wuerde
    der zweite den ersten ueberschreiben, gaelte Januar als ungedeckt."""
    konto.importieren(_export("01.01.2026", "28.02.2026", "08.08.2026",
                              "2.428,44 €", [("15.01.26", "500")]))
    konto.importieren(_export("01.03.2026", "08.08.2026", "08.08.2026",
                              "2.428,44 €", [("15.04.26", "300")]))
    a = vs.auszuege()[0]
    assert a["von"] == "2026-01-01" and a["bis"] == "2026-08-08"
    assert vs.luecken() == []


# ------------------ Die Kreditkartenabrechnung als Beleg (8.8.2026)
def test_an_eine_umbuchung_laesst_sich_ein_beleg_haengen():
    """Die Kreditkartenabrechnung (PDF) dokumentiert die Sammelbuchung: „Neuer
    Saldo -185,68" ist genau die Abbuchung auf dem Konto. Fuers Steuerbuero
    gehoert sie dort hin – bisher liess sich an eine Umbuchung nichts haengen.
    """
    from app import db
    db.anlegen(konto.TABELLE, {"id": "g1", "datum": "2026-01-26", "betrag": -185.68,
                               "gegenpartei": "Deutsche Kreditbank Berlin",
                               "text": "KREDITKARTENABRECHNUNG VISA", "konto": "DE62",
                               "umbuchung": True, "kategorie": ""})
    db.anlegen("belege", {"id": "abr", "uploader": "x", "ts": "2026-01-24T10:00:00",
                          "photo": "p.pdf", "merchant": "DKB", "amount": "185,68",
                          "datum": "2026-01-24"})
    assert konto.beleg_anhaengen("g1", "abr") is not None
    assert konto.belege_von(konto.holen("g1")) == ["abr"]


def test_der_beleg_an_der_umbuchung_aendert_keine_zahl():
    """Die Sammelbuchung ist neutral – sie darf durch ein angehaengtes Dokument
    nicht ploetzlich im Ergebnis auftauchen."""
    from app import db, ueberblick as ub
    db.anlegen(konto.TABELLE, {"id": "g1", "datum": "2026-01-26", "betrag": -185.68,
                               "gegenpartei": "DKB", "text": "KREDITKARTENABRECHNUNG",
                               "konto": "DE62", "umbuchung": True, "kategorie": ""})
    db.anlegen("belege", {"id": "abr", "uploader": "x", "ts": "2026-01-24T10:00:00",
                          "photo": "p.pdf", "merchant": "DKB", "amount": "185,68",
                          "datum": "2026-01-24"})
    vorher = ub.monate()
    konto.beleg_anhaengen("g1", "abr")
    assert ub.monate() == vorher == {}
    assert konto.je_kategorie() == {}


def test_an_der_umbuchung_wird_ein_beleg_vorgeschlagen():
    """Damit die schon hochgeladene Abrechnung dort waehlbar ist."""
    from app import belegzuordnung as bz, db
    b = {"id": "g1", "datum": "2026-01-26", "betrag": -185.68,
         "gegenpartei": "Deutsche Kreditbank Berlin",
         "text": "KREDITKARTENABRECHNUNG VISA", "konto": "DE62",
         "umbuchung": True, "kategorie": ""}
    db.anlegen(konto.TABELLE, b)
    db.anlegen("belege", {"id": "abr", "uploader": "x", "ts": "2026-01-24T10:00:00",
                          "photo": "p.pdf", "merchant": "DKB", "amount": "185,68",
                          "datum": "2026-01-24"})
    k = bz.belege_zu(b)
    assert [x["beleg"]["id"] for x in k] == ["abr"]
    assert k[0]["grund"] == "Betrag stimmt"


def test_nur_ein_dokument_je_umbuchung():
    """Ein zweites waere keine Aufteilung, sondern eine Dublette."""
    from app import db
    db.anlegen(konto.TABELLE, {"id": "g1", "datum": "2026-01-26", "betrag": -185.68,
                               "gegenpartei": "DKB", "text": "KREDITKARTENABRECHNUNG",
                               "konto": "DE62", "umbuchung": True, "kategorie": ""})
    for i in ("a", "b"):
        db.anlegen("belege", {"id": i, "uploader": "x", "ts": "2026-01-24T10:00:00",
                              "photo": "p.pdf", "merchant": "DKB", "amount": "185,68",
                              "datum": "2026-01-24"})
    konto.beleg_anhaengen("g1", "a")
    assert konto.beleg_anhaengen("g1", "b") is None
    assert konto.belege_von(konto.holen("g1")) == ["a"]


def test_die_maske_einer_umbuchung_laesst_sich_zeichnen():
    from app.ui import kontoblatt
    from app import db
    b = {"id": "g1", "datum": "2026-01-26", "betrag": -185.68, "gegenpartei": "DKB",
         "text": "KREDITKARTENABRECHNUNG", "konto": "DE62", "umbuchung": True,
         "kategorie": ""}
    db.anlegen(konto.TABELLE, b)
    _in_client(lambda: kontoblatt._beleg_knopf(b, lambda: None))
