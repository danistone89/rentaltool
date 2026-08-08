"""B6: die Kategorie gehört an den Posten, nicht an die Bewegung.

Am Bestand nachgesehen (8.8.2026): von 10 Posten trugen 2 keine Kategorie –
darunter ein *Kategorie*-Posten über 790,27 €, der damit gar nichts aussagt.
Entstanden ist er, weil die Maske „— Kategorie —" stehen ließ und trotzdem
buchte. Für die Portalprovision, um die es dort ging, existiert überhaupt keine
Kategorie: die Vorgaben sind wörtlich die des Workbooks, und die Vorkontierung
macht der Betrieb selbst.
"""
from app import buchhaltung as bh, konto, zuordnung as z


def _bewegung(betrag, gegenpartei, bid, datum="2026-06-12", text="", kategorie=""):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": gegenpartei,
            "text": text, "konto": "giro", "umbuchung": False, "kategorie": kategorie}
    db.anlegen(konto.TABELLE, satz)
    return satz


# ------------------------------------------- B6b: kein Posten ohne Kategorie
def test_ein_kategorie_posten_braucht_eine_kategorie():
    """Der Posten über 790,27 € sagte nichts – er trug nur einen Betrag."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    satz, meldung = z.hinzufuegen(b["id"], z.KATEGORIE, -100.0, "")
    assert satz is None
    assert "Kategorie" in meldung


def test_rechnung_und_beleg_gehen_auch_ohne_kategorie():
    """Sie tragen ihr Gegenstück; die Kategorie kann nachgereicht werden."""
    b = _bewegung(1000.0, "Booking.com BV", "w1")
    satz, _m = z.hinzufuegen(b["id"], z.RECHNUNG, 620.0, ziel_id="r1")
    assert satz is not None
    satz, _m = z.hinzufuegen(b["id"], z.BELEG, -50.0, ziel_id="q1")
    assert satz is not None


# ------------------------------------------- B6a: Kategorie am Posten ändern
def test_die_kategorie_eines_postens_laesst_sich_aendern():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    satz, _m = z.hinzufuegen(b["id"], z.KATEGORIE, -100.0, "Wäscherei (Rena)")
    z.kategorie_setzen(satz["id"], "Ausstattung/GWG (JYSK)")
    assert z.posten("w1")[0]["kategorie"] == "Ausstattung/GWG (JYSK)"


def test_jeder_posten_einer_sammelzahlung_kann_eine_andere_tragen():
    """Der eigentliche Punkt von B6: eine Zahlung, zwei Verwendungen."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    a, _ = z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    c, _ = z.hinzufuegen(b["id"], z.KATEGORIE, -40.0, "Ausstattung/GWG (JYSK)")
    assert [x["kategorie"] for x in z.posten("w1")] \
        == ["Wäscherei (Rena)", "Ausstattung/GWG (JYSK)"]


def test_eine_leere_kategorie_wird_nicht_gesetzt():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    satz, _m = z.hinzufuegen(b["id"], z.KATEGORIE, -100.0, "Wäscherei (Rena)")
    assert z.kategorie_setzen(satz["id"], "") is None
    assert z.posten("w1")[0]["kategorie"] == "Wäscherei (Rena)"


# ------------------------------------------------- B6c: sinnvolle Vorbelegung
def test_eine_booking_auszahlung_gibt_die_erloeskategorie_vor():
    b = _bewegung(1000.0, "Booking.com BV", "w1")
    assert z.kategorie_vorschlag(b, z.RECHNUNG) \
        == "Beherbergungserlöse (Booking, netto Auszahlung)"


def test_eine_airbnb_auszahlung_ebenso():
    b = _bewegung(1000.0, "Airbnb", "w1", text="AWV-MELDEPFLICHT")
    assert z.kategorie_vorschlag(b, z.RECHNUNG) \
        == "Beherbergungserlöse (Airbnb, netto Auszahlung)"


def test_eine_direktzahlung_ist_eine_direktbuchung():
    b = _bewegung(620.0, "Ernst, Anja", "w1", text="Fam. Ernst")
    assert z.kategorie_vorschlag(b, z.RECHNUNG) \
        == "Beherbergungserlöse (Direktbuchung, brutto)"


def test_bei_einer_ausgabe_gilt_die_kategorie_der_bewegung():
    b = _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    assert z.kategorie_vorschlag(b, z.KATEGORIE) == "Wäscherei (Rena)"


def test_ohne_anhaltspunkt_wird_nichts_vorgeschlagen():
    """Raten ist hier schlimmer als schweigen – eine falsche Kategorie läuft
    still ins Ergebnis."""
    b = _bewegung(-100.0, "Unbekannt GmbH", "w1")
    assert z.kategorie_vorschlag(b, z.KATEGORIE) == ""


def test_der_vorschlag_wird_beim_anlegen_verwendet():
    b = _bewegung(1000.0, "Booking.com BV", "w1")
    satz, _m = z.hinzufuegen(b["id"], z.RECHNUNG, 620.0, ziel_id="r1")
    assert satz["kategorie"] == "Beherbergungserlöse (Booking, netto Auszahlung)"


def test_eine_ausdrueckliche_kategorie_schlaegt_den_vorschlag():
    b = _bewegung(1000.0, "Booking.com BV", "w1")
    satz, _m = z.hinzufuegen(b["id"], z.RECHNUNG, 620.0,
                             kategorie="Beherbergungserlöse (Direktbuchung, brutto)",
                             ziel_id="r1")
    assert satz["kategorie"] == "Beherbergungserlöse (Direktbuchung, brutto)"


# -------------------------------------------------- Auswertung über die Posten
def test_die_summen_kommen_aus_den_posten_nicht_aus_der_bewegung():
    """Eine Zahlung, zwei Kategorien – nach der Bewegung gerechnet stünde
    alles unter einer."""
    b = _bewegung(-100.0, "Baumarkt", "w1", kategorie="Wäscherei (Rena)")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    z.hinzufuegen(b["id"], z.KATEGORIE, -40.0, "Ausstattung/GWG (JYSK)")
    summen = konto.je_kategorie()
    assert summen["Wäscherei (Rena)"] == -60.0
    assert summen["Ausstattung/GWG (JYSK)"] == -40.0


def test_ohne_posten_zaehlt_die_kategorie_der_bewegung():
    """Sonst verschwänden alle Bewegungen, die noch nicht aufgeteilt sind."""
    _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    assert konto.je_kategorie()["Wäscherei (Rena)"] == -100.0


def test_eine_teilweise_aufgeteilte_bewegung_zaehlt_nicht_doppelt():
    """Der Rest gehört noch nirgends – er darf nicht bei der Kategorie der
    Bewegung mitlaufen, sonst wäre die Summe zu hoch."""
    b = _bewegung(-100.0, "Baumarkt", "w1", kategorie="Wäscherei (Rena)")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    summen = konto.je_kategorie()
    assert summen["Wäscherei (Rena)"] == -60.0
    assert summen.get(konto.OHNE_KATEGORIE) == -40.0


def test_umbuchungen_zaehlen_nicht_mit():
    from app import db
    db.anlegen(konto.TABELLE, {"id": "u1", "datum": "2026-06-12", "betrag": -500.0,
                               "gegenpartei": "Kreditkartenabrechnung", "text": "",
                               "konto": "giro", "umbuchung": True, "kategorie": ""})
    assert konto.je_kategorie() == {}


def test_der_zeitraum_wird_beachtet():
    _bewegung(-100.0, "Rena", "w1", datum="2026-06-12",
              kategorie="Wäscherei (Rena)")
    _bewegung(-50.0, "Rena", "w2", datum="2026-07-12",
              kategorie="Wäscherei (Rena)")
    assert konto.je_kategorie("2026-07-01", "2026-07-31")["Wäscherei (Rena)"] == -50.0


def test_die_klasse_kommt_aus_der_kategorie_des_postens():
    """Für den Überblick später: eine Privatentnahme in einer Sammelzahlung
    darf das Ergebnis nicht belasten."""
    assert bh.klasse_fuer("Eigenübertrag / Entnahme") == "Privat/prüfen"
    assert bh.klasse_fuer("Wäscherei (Rena)") == "Ausgabe"


# ------------------------------------------------------------- Die Anzeige
def _in_client(bauen):
    from nicegui import ui
    from nicegui.client import Client
    with Client(lambda: None):
        with ui.card():
            bauen()


def test_die_zuordnungsmaske_laesst_sich_zeichnen():
    """Rauchprobe: Kategorieauswahl je Posten und das „+" daneben."""
    from app.ui import kontoblatt
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    _in_client(lambda: kontoblatt._zuordnungsmaske(b, lambda: None))


def test_die_provisionszeile_laesst_sich_zeichnen():
    """Sie fuehrt jetzt zum Anlegen, wenn keine Provisionskategorie da ist."""
    from app.ui import kontoblatt
    b = _bewegung(1000.0, "Booking.com BV", "w1")
    z.hinzufuegen(b["id"], z.RECHNUNG, 1120.0, ziel_id="r1")
    _in_client(lambda: kontoblatt._provisionszeile(b, -120.0, lambda: None))


def test_eine_geloeschte_kategorie_bricht_die_maske_nicht():
    """Steht am Posten eine Kategorie, die es nicht mehr gibt, lehnte die
    Auswahl den Wert ab – und die ganze Maske brach ab. Der Posten waere dann
    gar nicht mehr erreichbar, um ihn zu berichtigen."""
    from app.ui import kontoblatt
    b = _bewegung(-100.0, "Baumarkt", "w1")
    satz, _m = z.hinzufuegen(b["id"], z.KATEGORIE, -100.0, "Gibt es nicht mehr")
    _in_client(lambda: kontoblatt._posten_kategorie(satz, lambda: None))
