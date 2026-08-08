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
