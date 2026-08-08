"""Filter und Blickfeld in der Kontoliste (8.8.2026 gemeldet).

„Bau im Konto bitte einen Filter, damit ich effektiver arbeiten kann … Wenn ich
eine Kategorie zugeordnet hab, soll der Bereich nicht wegspringen, damit man
das Ergebnis prüfen kann."

Bei 238 Bewegungen ist Suchen die halbe Arbeit — und nach jeder Zuordnung
zeichnet sich die Liste neu, wodurch die offene Zeile zuklappte und aus dem
Blickfeld verschwand.
"""
from app import konto


def _bewegung(betrag, gegenpartei, bid, datum="2026-06-12", text="", kategorie=""):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": gegenpartei,
            "text": text, "konto": "giro", "umbuchung": False, "kategorie": kategorie}
    db.anlegen(konto.TABELLE, satz)
    return satz


# ------------------------------------------------------------- Die Suche
def test_die_suche_findet_ueber_den_empfaenger():
    _bewegung(-100.0, "WEG Wohnpark Dresden", "w1")
    _bewegung(-50.0, "Netto Marken-Discount", "w2")
    assert [b["id"] for b in konto.filtern(konto.alle(), suche="weg")] == ["w1"]


def test_die_suche_findet_im_verwendungszweck():
    _bewegung(1000.0, "Booking.com BV", "w1", text="NO.abc/ID.14005823")
    _bewegung(-50.0, "Netto", "w2")
    assert [b["id"] for b in konto.filtern(konto.alle(), suche="14005823")] == ["w1"]


def test_mehrere_woerter_muessen_alle_vorkommen():
    _bewegung(-100.0, "WEG Wohnpark", "w1", datum="2026-07-24")
    _bewegung(-100.0, "WEG Wohnpark", "w2", datum="2026-03-24")
    assert [b["id"] for b in konto.filtern(konto.alle(), suche="weg 2026-07")] == ["w1"]


def test_die_suche_findet_ueber_den_betrag():
    _bewegung(-83.46, "WEG", "w1")
    _bewegung(-50.0, "Netto", "w2")
    assert [b["id"] for b in konto.filtern(konto.alle(), suche="83,46")] == ["w1"]


# --------------------------------------------------------- Nach Kategorie
def test_nach_kategorie_filtern():
    _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    _bewegung(-50.0, "Netto", "w2", kategorie="Reinigung/Verbrauch (dm)")
    f = konto.filtern(konto.alle(), kategorie="Wäscherei (Rena)")
    assert [b["id"] for b in f] == ["w1"]


def test_ohne_kategorie_ist_eine_eigene_auswahl():
    """Die Arbeitsliste: was noch niemand angefasst hat."""
    _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    _bewegung(-50.0, "Unbekannt", "w2")
    f = konto.filtern(konto.alle(), kategorie=konto.OHNE_KATEGORIE)
    assert [b["id"] for b in f] == ["w2"]


# ------------------------------------------------------------ Nach Datum
def test_nach_zeitraum_filtern():
    _bewegung(-10.0, "A", "w1", datum="2026-01-15")
    _bewegung(-10.0, "B", "w2", datum="2026-06-15")
    f = konto.filtern(konto.alle(), von="2026-06-01", bis="2026-06-30")
    assert [b["id"] for b in f] == ["w2"]


def test_die_grenzen_zaehlen_mit():
    _bewegung(-10.0, "A", "w1", datum="2026-06-01")
    _bewegung(-10.0, "B", "w2", datum="2026-06-30")
    f = konto.filtern(konto.alle(), von="2026-06-01", bis="2026-06-30")
    assert len(f) == 2


# ------------------------------------------------------- Alles zusammen
def test_die_bedingungen_wirken_zusammen():
    _bewegung(-100.0, "WEG Wohnpark", "w1", datum="2026-07-24",
              kategorie="Hausgeld WEG Wohnpark")
    _bewegung(-100.0, "WEG Wohnpark", "w2", datum="2026-01-24",
              kategorie="Hausgeld WEG Wohnpark")
    _bewegung(-100.0, "Rena", "w3", datum="2026-07-24", kategorie="Wäscherei (Rena)")
    f = konto.filtern(konto.alle(), suche="weg", kategorie="Hausgeld WEG Wohnpark",
                      von="2026-07-01")
    assert [b["id"] for b in f] == ["w1"]


def test_ohne_angaben_bleibt_alles_stehen():
    _bewegung(-10.0, "A", "w1")
    _bewegung(-10.0, "B", "w2")
    assert len(konto.filtern(konto.alle())) == 2


def test_die_gerade_bearbeitete_zeile_bleibt_sichtbar():
    """Der Kern der Meldung: nach dem Zuordnen faellt die Bewegung aus dem
    Filter – und damit aus dem Blickfeld, bevor man das Ergebnis pruefen
    konnte."""
    _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    _bewegung(-50.0, "Unbekannt", "w2")
    f = konto.filtern(konto.alle(), kategorie=konto.OHNE_KATEGORIE, behalten="w1")
    assert [b["id"] for b in f] == ["w1", "w2"]


def test_behalten_ohne_treffer_stoert_nicht():
    _bewegung(-50.0, "Unbekannt", "w2")
    f = konto.filtern(konto.alle(), kategorie=konto.OHNE_KATEGORIE, behalten="gibtsnicht")
    assert [b["id"] for b in f] == ["w2"]


def test_die_reihenfolge_bleibt_erhalten():
    _bewegung(-10.0, "A", "w1", datum="2026-01-15")
    _bewegung(-10.0, "B", "w2", datum="2026-06-15")
    alle = konto.alle()
    assert [b["id"] for b in konto.filtern(alle)] == [b["id"] for b in alle]


def test_die_vergebenen_kategorien_stehen_zur_auswahl():
    _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    _bewegung(-100.0, "Rena", "w2", kategorie="Wäscherei (Rena)")
    _bewegung(-50.0, "Unbekannt", "w3")
    k = konto.vergebene_kategorien()
    assert k == ["Wäscherei (Rena)"], "jede nur einmal, alphabetisch"


# ------------------------------------------------------------- Die Anzeige
def _in_client(bauen):
    from nicegui import ui
    from nicegui.client import Client
    with Client(lambda: None):
        with ui.card() as karte:
            bauen()
    return karte


def test_die_filterzeile_laesst_sich_zeichnen():
    from app.ui import kontoblatt
    _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    zustand = {"suche": "", "kategorie": "", "von": "", "bis": ""}
    _in_client(lambda: kontoblatt._filterzeile(zustand, lambda: None))


def test_der_filter_wirkt_erst_auf_knopfdruck():
    """Die erste Fassung zeichnete bei JEDEM Tastendruck neu – dabei wurde das
    Suchfeld selbst neu gebaut und von „booking" blieb ein „b" stehen.

    Geprüft wird deshalb, dass am Suchfeld **kein** Änderungs-Handler hängt und
    es stattdessen einen Knopf gibt.
    """
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    zustand = {"suche": "", "kategorie": "", "von": "", "bis": ""}
    with Client(lambda: None):
        with ui.card() as karte:
            kontoblatt._filterzeile(zustand, lambda: None)
    zeile = karte.default_slot.children[0].default_slot.children
    suchfeld = zeile[0]
    assert isinstance(suchfeld, ui.input)
    assert suchfeld._change_handlers == [], "Tippen darf nichts ausloesen"
    knoepfe = [c for c in zeile if isinstance(c, ui.button)]
    assert len(knoepfe) == 2, "Filtern und Zuruecksetzen"


def test_die_kategorienauswahl_kennt_das_ohne():
    from app.ui import kontoblatt
    _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    wahl = kontoblatt._kategoriewahl()
    assert konto.OHNE_KATEGORIE in wahl and "Wäscherei (Rena)" in wahl


def test_die_kontoseite_laesst_sich_mit_filter_zeichnen():
    from app.ui import kontoblatt
    _bewegung(-100.0, "WEG Wohnpark", "w1", kategorie="Hausgeld WEG Wohnpark")
    _bewegung(-50.0, "Unbekannt", "w2")
    _in_client(kontoblatt.render_konto)


# ------------------------------------------- Welche Zeile bleibt offen?
def test_aufklappen_merkt_die_zeile():
    from app.ui import kontoblatt
    assert kontoblatt._offen_merken("", "w1", True) == "w1"


def test_zuklappen_derselben_zeile_vergisst_sie():
    from app.ui import kontoblatt
    assert kontoblatt._offen_merken("w1", "w1", False) == ""


def test_das_zuklappen_der_vorigen_loescht_die_neue_nicht():
    """NiceGUI meldet beim Aufklappen auch das Zuklappen der vorigen – in
    beliebiger Reihenfolge. Wer bedingungslos leert, klappt alles zu."""
    from app.ui import kontoblatt
    assert kontoblatt._offen_merken("w2", "w1", False) == "w2"


# ------------------- Mehrere auswaehlen und gemeinsam zuordnen (8.8.2026)
# "Es waere viel sinnvoller, dass man mehrere Bewegungen auswaehlen kann und
# dann eine Kategorie setzt, als dies automatisch wie bisher zu machen. So kann
# man erst filtern, manuell auswaehlen und dann Kategorie setzen."
def test_mehrere_bewegungen_bekommen_eine_kategorie():
    from app import zuordnung as z
    _bewegung(-153.80, "TARGOBANK AG", "w1", datum="2026-01-02")
    _bewegung(-153.80, "TARGOBANK AG", "w2", datum="2026-02-02")
    _bewegung(-50.0, "Netto", "w3")
    n = konto.mehrere_zuordnen(["w1", "w2"], "Wäscherei (Rena)")
    assert n == 2
    assert konto.holen("w1")["kategorie"] == "Wäscherei (Rena)"
    assert z.ist_fertig(konto.holen("w2"))
    assert konto.holen("w3")["kategorie"] == ""


def test_die_auswahl_zieht_nichts_weiteres_mit():
    """Der Kern: nur was ausgewaehlt ist. Sonst waere es wieder die Automatik,
    gegen die der Wunsch gerichtet war."""
    _bewegung(-153.80, "TARGOBANK AG", "w1", datum="2026-01-02")
    _bewegung(-153.80, "TARGOBANK AG", "w2", datum="2026-02-02")
    konto.mehrere_zuordnen(["w1"], "Wäscherei (Rena)")
    assert konto.holen("w2")["kategorie"] == ""


def test_der_empfaenger_wird_trotzdem_gemerkt():
    """Damit der naechste Auszug ihn von allein erkennt."""
    from app import stammdaten
    _bewegung(-153.80, "TARGOBANK AG", "w1")
    konto.mehrere_zuordnen(["w1"], "Wäscherei (Rena)")
    k = stammdaten.kreditor_zu("TARGOBANK AG")
    assert k and k.get("kategorie") == "Wäscherei (Rena)"


def test_was_schon_posten_traegt_bleibt_unberuehrt():
    from app import zuordnung as z
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    assert konto.mehrere_zuordnen(["w1"], "Ausstattung/GWG (JYSK)") == 0
    assert len(z.posten("w1")) == 1


def test_eine_erkannte_bewegung_laesst_sich_ueberschreiben():
    """Wer auswaehlt, entscheidet – auch gegen die automatische Erkennung."""
    _bewegung(-73.78, "Smoobu GmbH", "w1", kategorie="Reinigung/Verbrauch (dm)")
    konto.mehrere_zuordnen(["w1"], "Software (Smoobu Channelmanager)")
    assert konto.holen("w1")["kategorie"] == "Software (Smoobu Channelmanager)"


def test_ohne_kategorie_passiert_nichts():
    _bewegung(-50.0, "Netto", "w1")
    assert konto.mehrere_zuordnen(["w1"], "") == 0


def test_eine_umbuchung_wird_uebersprungen():
    from app import db
    db.anlegen(konto.TABELLE, {"id": "u1", "datum": "2026-06-12", "betrag": -500.0,
                               "gegenpartei": "Kreditkarte", "text": "",
                               "konto": "giro", "umbuchung": True, "kategorie": ""})
    assert konto.mehrere_zuordnen(["u1"], "Wäscherei (Rena)") == 0


def test_ein_einzelner_klick_zieht_nichts_mehr_mit():
    """Die stille Automatik ist abgeschaltet – gewollt war Kontrolle. Gelernt
    wird weiter, und „Gelerntes anwenden" bleibt der ausdrueckliche Weg."""
    _bewegung(-153.80, "TARGOBANK AG", "w1", datum="2026-01-02")
    _bewegung(-153.80, "TARGOBANK AG", "w2", datum="2026-02-02")
    _satz, weitere = konto.schnell_zuordnen("w1", "Wäscherei (Rena)")
    assert weitere == []
    assert konto.holen("w2")["kategorie"] == ""


def test_gelerntes_anwenden_zieht_weiterhin_mit():
    """Dort ist es ausdruecklich gewollt – der Knopf heisst so."""
    _bewegung(-153.80, "TARGOBANK AG", "w1", datum="2026-01-02")
    konto.mehrere_zuordnen(["w1"], "Wäscherei (Rena)")
    _bewegung(-153.80, "TARGOBANK AG", "w2", datum="2026-02-02")
    _bewegung(-153.80, "TARGOBANK AG", "w3", datum="2026-03-02")
    assert konto.gelerntes_anwenden(konto.vorschau_gelernt()) == 2


def test_die_auswahlleiste_erscheint_erst_mit_einer_auswahl():
    """Ohne Auswahl waere sie eine leere Zeile ueber der Liste."""
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    b = _bewegung(-100.0, "Rena", "w1")
    with Client(lambda: None):
        with ui.card() as leer:
            kontoblatt._auswahlleiste({"auswahl": set()}, [b], lambda: None)
        with ui.card() as voll:
            kontoblatt._auswahlleiste({"auswahl": {"w1"}}, [b], lambda: None)

    def knoepfe(k):
        return sum(1 for c in k.default_slot.children[0].default_slot.children
                   if isinstance(c, ui.button))
    # leer: nur „Alle im Filter" · voll: dazu „+", Setzen, Aufheben
    assert knoepfe(leer) == 1 and knoepfe(voll) > 1


def test_die_kontoseite_mit_auswahl_laesst_sich_zeichnen():
    from app.ui import kontoblatt
    _bewegung(-100.0, "Rena", "w1")
    _bewegung(-50.0, "Netto", "w2", kategorie="Reinigung/Verbrauch (dm)")
    _in_client(kontoblatt.render_konto)
