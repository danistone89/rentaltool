"""Ein Klick je Zeile – und das Gelernte auch rückwirkend anwenden.

Gemeldet am 8.8.2026: „wie tagge ich denn eine Gehaltszahlung unter konto?"
Dahinter steckten drei Dinge, die am Bestand nachweisbar sind:

* Die **Kategorieauswahl in der Zeile** gab es bis Paket B2; seither muss man
  jede Bewegung erst aufklappen.
* Das **Gelernte wirkte nicht rückwirkend**: nach der Zuordnung von „Valeriya
  Remez" blieben 5 weitere Zahlungen an dieselbe Person ohne Kategorie, weil
  die Erkennung nur beim Einlesen läuft.
* Die Arbeitsliste **„Nicht zugeordnet" wurde nie leer**: eine über die Maske
  vollständig aufgeteilte Bewegung zählte weiter mit, weil sie am Feld
  `kategorie` hängt und die Maske nur Posten anlegt. An den echten Daten war
  genau eine Bewegung betroffen (Gabriel, −280,50 €, `ist_fertig` = True).
"""
from app import konto, stammdaten, zuordnung as z


def _bewegung(betrag, gegenpartei, bid, datum="2026-06-12", text="", kategorie=""):
    from app import db
    satz = {"id": bid, "datum": datum, "betrag": betrag, "gegenpartei": gegenpartei,
            "text": text, "konto": "giro", "umbuchung": False, "kategorie": kategorie}
    db.anlegen(konto.TABELLE, satz)
    return satz


# --------------------------------------------- Die Arbeitsliste wird leer
def test_eine_aufgeteilte_bewegung_gilt_als_zugeordnet():
    """Sonst bleibt der Zähler stehen, egal wie viel man arbeitet."""
    b = _bewegung(-280.50, "Gabriel", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -280.50, "Löhne/Gehälter Minijob")
    assert konto.ohne_zuordnung() == []


def test_eine_halb_aufgeteilte_bewegung_bleibt_in_der_liste():
    """Halb erledigt ist nicht erledigt – sonst fiele der Rest unter den Tisch."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    assert [x["id"] for x in konto.ohne_zuordnung()] == ["w1"]


def test_ohne_alles_bleibt_die_bewegung_offen():
    _bewegung(-100.0, "Baumarkt", "w1")
    assert [x["id"] for x in konto.ohne_zuordnung()] == ["w1"]


def test_das_kategoriefeld_allein_genuegt_weiterhin():
    """Bewegungen aus der Erkennung tragen nur das Feld – sie sind erledigt."""
    _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    assert konto.ohne_zuordnung() == []


# ------------------------------------------------- Ein Klick in der Zeile
def test_ein_klick_ordnet_die_ganze_bewegung_zu():
    b = _bewegung(-280.50, "Valeriya Remez", "w1")
    konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    p = z.posten("w1")
    assert len(p) == 1 and p[0]["betrag"] == -280.50
    assert p[0]["kategorie"] == "Löhne/Gehälter Minijob"
    assert z.ist_fertig(konto.holen("w1"))


def test_der_klick_setzt_auch_das_feld_und_die_klasse():
    """Das Feld traegt die Erkennung und den Rueckfall der Auswertung."""
    _bewegung(-280.50, "Valeriya Remez", "w1")
    konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    b = konto.holen("w1")
    assert b["kategorie"] == "Löhne/Gehälter Minijob"
    assert b["klasse"] == "Ausgabe" and b["herkunft"] == "hand"


def test_der_klick_merkt_sich_den_empfaenger():
    """Der Kern der Bedienung: einmal zuordnen, danach von allein erkannt."""
    _bewegung(-280.50, "Valeriya Remez", "w1")
    konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    k = stammdaten.kreditor_zu("Valeriya Remez")
    assert k and k.get("kategorie") == "Löhne/Gehälter Minijob"


def test_ohne_kategorie_passiert_nichts():
    _bewegung(-280.50, "Valeriya Remez", "w1")
    assert konto.schnell_zuordnen("w1", "")[0] is None
    assert z.posten("w1") == []


def test_wo_schon_posten_haengen_wird_nichts_ueberschrieben():
    """Dort gilt die Maske – ein Klick koennte eine Aufteilung nicht kennen."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    assert konto.schnell_zuordnen("w1", "Ausstattung/GWG (JYSK)")[0] is None
    assert len(z.posten("w1")) == 1


def test_eine_umbuchung_wird_nicht_zugeordnet():
    from app import db
    db.anlegen(konto.TABELLE, {"id": "u1", "datum": "2026-06-12", "betrag": -500.0,
                               "gegenpartei": "Kreditkartenabrechnung", "text": "",
                               "konto": "giro", "umbuchung": True, "kategorie": ""})
    assert konto.schnell_zuordnen("u1", "Wäscherei (Rena)")[0] is None


# --------------------------------------- Gelerntes rueckwirkend anwenden
def test_die_vorschau_findet_die_gelernten_empfaenger():
    """Nach EINER Zuordnung sollen die uebrigen Zahlungen derselben Person
    gefunden werden – an den echten Daten waren das 5 weitere."""
    _bewegung(-619.77, "Valeriya Remez", "w1")
    konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    _bewegung(-530.00, "Valeriya Remez", "w2", datum="2026-05-05")
    _bewegung(-318.12, "Valeriya Remez", "w3", datum="2026-04-08")
    v = konto.vorschau_gelernt()
    assert sorted(x["bewegung"]["id"] for x in v) == ["w2", "w3"]
    assert v[0]["kategorie"] == "Löhne/Gehälter Minijob"


def test_was_schon_eine_kategorie_hat_bleibt_unberuehrt():
    """Sonst naehme ein spaeterer Lauf eine Handkorrektur wieder zurueck."""
    _bewegung(-619.77, "Valeriya Remez", "w1")
    konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    _bewegung(-530.00, "Valeriya Remez", "w2", datum="2026-05-05",
              kategorie="Ausstattung/GWG (JYSK)")
    assert [x["bewegung"]["id"] for x in konto.vorschau_gelernt()] == []


def test_ohne_gelernten_empfaenger_wird_nichts_vorgeschlagen():
    _bewegung(-176.17, "Gabriel Chukwuneke", "w1")
    assert konto.vorschau_gelernt() == []


def test_anwenden_schreibt_und_legt_posten_an():
    _bewegung(-619.77, "Valeriya Remez", "w1")
    konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    _bewegung(-530.00, "Valeriya Remez", "w2", datum="2026-05-05")
    n = konto.gelerntes_anwenden(konto.vorschau_gelernt())
    assert n == 1
    assert konto.holen("w2")["kategorie"] == "Löhne/Gehälter Minijob"
    assert z.ist_fertig(konto.holen("w2"))
    # Zweiter Lauf findet nichts mehr.
    assert konto.vorschau_gelernt() == []


def test_eingaenge_bekommen_keine_kategorie_verpasst():
    """Was ein Erloes ist, entscheidet die Zuordnung zu einer Rechnung – nicht
    der Name des Absenders."""
    _bewegung(-619.77, "Valeriya Remez", "w1")
    konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    _bewegung(1200.00, "Valeriya Remez", "w2", datum="2026-05-05")
    assert [x["bewegung"]["id"] for x in konto.vorschau_gelernt()] == []


# ------------------------------------------------------------- Die Anzeige
def _in_client(bauen):
    from nicegui import ui
    from nicegui.client import Client
    with Client(lambda: None):
        with ui.card():
            bauen()


def test_die_auswahl_erscheint_an_einer_offenen_ausgabe():
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    b = _bewegung(-280.50, "Valeriya Remez", "w1")
    with Client(lambda: None):
        with ui.card() as karte:
            kontoblatt._kategorie_wahl(b, lambda: None)
    # Nicht bloss „ist durchgelaufen": es muss wirklich ein Feld dastehen.
    assert len(karte.default_slot.children) == 1


def test_die_auswahl_fehlt_wo_schon_posten_haengen():
    """Dort gilt die Maske – ein Klick koennte eine Aufteilung nicht kennen."""
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    with Client(lambda: None):
        with ui.card() as karte:
            kontoblatt._kategorie_wahl(b, lambda: None)
    assert not karte.default_slot.children


def test_der_gelernt_knopf_laesst_sich_zeichnen():
    from app.ui import kontoblatt
    _bewegung(-619.77, "Valeriya Remez", "w1")
    konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    _bewegung(-530.00, "Valeriya Remez", "w2", datum="2026-05-05")
    _in_client(lambda: kontoblatt._gelerntes_knopf(lambda: None))


def test_ohne_vorschlaege_erscheint_der_knopf_nicht():
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    _bewegung(-176.17, "Unbekannt", "w1")
    with Client(lambda: None):
        with ui.card() as karte:
            kontoblatt._gelerntes_knopf(lambda: None)
    assert not karte.default_slot.children


# ------------------------------- Gleicher Empfaenger: sofort mit erledigen
def test_die_uebrigen_zahlungen_desselben_empfaengers_gehen_mit():
    """Gemeldet am 8.8.2026: „habe einer Valeriya-Remez-Buchung Gehaelter
    zugeordnet, bei allen anderen hat sich nichts geaendert."

    Das Lernen griff, aber erst auf Klick. Wer gerade entschieden hat, wofuer
    eine Zahlung an diese Person ist, hat es fuer alle entschieden.
    """
    _bewegung(-619.77, "Valeriya Remez", "w1", datum="2026-06-22")
    _bewegung(-530.00, "Valeriya Remez", "w2", datum="2026-05-05")
    _bewegung(-318.12, "Valeriya Remez", "w3", datum="2026-04-08")
    _bewegung(-176.17, "Gabriel", "w4", datum="2026-05-27")
    _b, weitere = konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    assert sorted(weitere) == ["w2", "w3"]
    assert konto.holen("w2")["kategorie"] == "Löhne/Gehälter Minijob"
    assert z.ist_fertig(konto.holen("w3"))
    # Ein anderer Empfaenger bleibt unberuehrt.
    assert konto.holen("w4")["kategorie"] == ""


def test_was_schon_zugeordnet_ist_wird_nicht_angefasst():
    _bewegung(-619.77, "Valeriya Remez", "w1")
    _bewegung(-530.00, "Valeriya Remez", "w2", datum="2026-05-05",
              kategorie="Ausstattung/GWG (JYSK)")
    _b, weitere = konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    assert weitere == []
    assert konto.holen("w2")["kategorie"] == "Ausstattung/GWG (JYSK)"


def test_eingaenge_desselben_namens_gehen_nicht_mit():
    _bewegung(-619.77, "Valeriya Remez", "w1")
    _bewegung(1200.00, "Valeriya Remez", "w2", datum="2026-05-05")
    _b, weitere = konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    assert weitere == []


def test_das_mitziehen_laesst_sich_zurueckdrehen():
    """Ohne Rueckweg waere das automatische Mitziehen ein Risiko."""
    _bewegung(-619.77, "Valeriya Remez", "w1")
    _bewegung(-530.00, "Valeriya Remez", "w2", datum="2026-05-05")
    _b, weitere = konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    konto.zuruecknehmen(weitere)
    b = konto.holen("w2")
    assert b["kategorie"] == "" and z.posten("w2") == []
    # Die zuerst zugeordnete Bewegung bleibt stehen.
    assert konto.holen("w1")["kategorie"] == "Löhne/Gehälter Minijob"


def test_zuruecknehmen_ruehrt_fremde_posten_nicht_an():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    konto.zuruecknehmen(["w1"])
    assert len(z.posten("w1")) == 1


def test_die_rueckmeldung_zum_mitziehen_laesst_sich_zeichnen():
    from app.ui import kontoblatt
    _bewegung(-619.77, "Valeriya Remez", "w1")
    _bewegung(-530.00, "Valeriya Remez", "w2", datum="2026-05-05")
    _b, weitere = konto.schnell_zuordnen("w1", "Löhne/Gehälter Minijob")
    _in_client(lambda: kontoblatt._mitgezogen_zeigen(
        "Valeriya Remez", "Löhne/Gehälter Minijob", weitere, lambda: None))


# ------------------------- Die Schutzregeln in `_setzen` und `zuruecknehmen`
# Sie greifen im normalen Ablauf nie, weil `ohne_zuordnung` schon filtert –
# und blieben deshalb bei der Gegenprobe gruen. Ein Schutz, den kein Test
# festhaelt, verschwindet beim naechsten Umbau unbemerkt.
def test_setzen_ruehrt_eine_zugeordnete_bewegung_nicht_an():
    b = _bewegung(-100.0, "Rena", "w1", kategorie="Wäscherei (Rena)")
    assert konto._setzen(b, "Ausstattung/GWG (JYSK)") is False
    assert konto.holen("w1")["kategorie"] == "Wäscherei (Rena)"


def test_setzen_ruehrt_eine_bewegung_mit_posten_nicht_an():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    assert konto._setzen(b, "Ausstattung/GWG (JYSK)") is False
    assert len(z.posten("w1")) == 1


def test_setzen_ruehrt_einen_eingang_nicht_an():
    """Was ein Erloes ist, entscheidet die Rechnung – nicht der Absendername."""
    b = _bewegung(1200.0, "Valeriya Remez", "w1")
    assert konto._setzen(b, "Löhne/Gehälter Minijob") is False
    assert z.posten("w1") == []


def test_zuruecknehmen_laesst_einen_belegposten_stehen():
    """Ein Beleg-Posten ueber den vollen Betrag ist NICHT so entstanden – er
    haengt an einem Dokument und darf nicht mitgeloescht werden."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.BELEG, -100.0, "Wäscherei (Rena)", ziel_id="q1")
    konto.zuruecknehmen(["w1"])
    assert len(z.posten("w1")) == 1


def test_zuruecknehmen_laesst_eine_aufteilung_stehen():
    """Zwei Posten ueber zusammen den vollen Betrag: von Hand aufgeteilt."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    z.hinzufuegen(b["id"], z.KATEGORIE, -40.0, "Ausstattung/GWG (JYSK)")
    konto.zuruecknehmen(["w1"])
    assert len(z.posten("w1")) == 2


# ------------- Die Maske muss dasselbe tun wie die Zeile (8.8.2026)
# Gemeldet: "wenn ich beispielsweise Targobank zuordne uebernimmt er es nicht
# fuer alle buchungen von targobank." Nachgesehen: zwei der acht Buchungen
# trugen einen Posten, aber der Empfaenger war nicht gelernt - die Maske legte
# nur den Posten an. Zwei Wege, zwei Verhalten; wer die Maske benutzt, tippt
# achtmal.
def test_die_maske_lernt_und_zieht_mit_wie_die_zeile():
    _bewegung(-153.80, "TARGOBANK AG", "w1", datum="2026-01-02")
    _bewegung(-153.80, "TARGOBANK AG", "w2", datum="2026-02-02")
    _bewegung(-153.80, "TARGOBANK AG", "w3", datum="2026-03-02")
    satz, weitere = konto.ganz_zuordnen("w1", "Immobiliendarlehen (Zins abzugsf., Tilgung neutral)")
    assert satz is not None and sorted(weitere) == ["w2", "w3"]
    assert stammdaten.kreditor_zu("TARGOBANK AG") is not None


def test_eine_echte_aufteilung_lernt_nichts():
    """Bei zwei Kategorien in einer Zahlung waere nicht zu sagen, welche der
    Empfaenger kuenftig bekommt."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    _bewegung(-100.0, "Baumarkt", "w2", datum="2026-07-01")
    satz, weitere = konto.ganz_zuordnen("w1", "Ausstattung/GWG (JYSK)")
    assert satz is None and weitere == []


# ------------- Aus dem, was schon zugeordnet ist, nachtraeglich lernen
def test_aus_vorhandenen_posten_wird_gelernt():
    """Der Bestand vom 8.8.2026: zwei Targobank-Buchungen waren ueber die Maske
    zugeordnet, gelernt war nichts. Ohne diesen Weg muesste man sie loesen und
    neu zuordnen, nur damit das Lernen greift."""
    b = _bewegung(-153.80, "TARGOBANK AG", "w1", datum="2026-02-02")
    z.hinzufuegen(b["id"], z.KATEGORIE, -153.80, "Immobiliendarlehen (Zins abzugsf., Tilgung neutral)")
    _bewegung(-153.80, "TARGOBANK AG", "w2", datum="2026-03-02")
    assert konto.aus_posten_lernen() == 1
    assert [x["bewegung"]["id"] for x in konto.vorschau_gelernt()] == ["w2"]


def test_aus_einer_aufteilung_wird_nichts_gelernt():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    z.hinzufuegen(b["id"], z.KATEGORIE, -40.0, "Ausstattung/GWG (JYSK)")
    assert konto.aus_posten_lernen() == 0


def test_auch_wenn_der_erste_posten_den_ganzen_betrag_traegt():
    """Schaerfer: hier deckt schon der ERSTE Posten die Bewegung, es haengt
    aber noch einer daran. Welche Kategorie soll der Empfaenger bekommen?
    Keine – sonst lernt das Werkzeug eine Haelfte der Wahrheit."""
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -100.0, "Wäscherei (Rena)")
    z.hinzufuegen(b["id"], z.KATEGORIE, -50.0, "Ausstattung/GWG (JYSK)")
    assert konto.aus_posten_lernen() == 0


def test_ein_belegposten_lehrt_auch(zusatz=None):
    """Auch ueber einen Beleg zugeordnet ist eine Entscheidung des Menschen."""
    b = _bewegung(-73.78, "Smoobu GmbH", "w1")
    z.hinzufuegen(b["id"], z.BELEG, -73.78, "Software (Smoobu Channelmanager)",
                  ziel_id="q1")
    assert konto.aus_posten_lernen() == 1


def test_was_schon_gelernt_ist_wird_nicht_ueberschrieben():
    b = _bewegung(-153.80, "TARGOBANK AG", "w1")
    konto.schnell_zuordnen("w1", "Wäscherei (Rena)")
    b2 = _bewegung(-153.80, "TARGOBANK AG", "w2", datum="2026-03-02")
    z.hinzufuegen(b2["id"], z.KATEGORIE, -153.80, "Ausstattung/GWG (JYSK)")
    konto.aus_posten_lernen()
    assert stammdaten.kreditor_zu("TARGOBANK AG")["kategorie"] == "Wäscherei (Rena)"


def test_die_maske_laesst_sich_nach_dem_umbau_zeichnen():
    from app.ui import kontoblatt
    b = _bewegung(-153.80, "TARGOBANK AG", "w1")
    _in_client(lambda: kontoblatt._zuordnungsmaske(b, lambda: None))


def test_die_zahl_nennt_die_zugeordneten_bewegungen():
    """Die erste nimmt die uebrigen mit – gezaehlt wird, was zugeordnet wurde,
    nicht wie oft zugeordnet wurde. An den echten Daten meldete es „1", waehrend
    sechs Targobank-Buchungen erledigt waren."""
    b = _bewegung(-153.80, "TARGOBANK AG", "w0", datum="2026-01-02")
    z.hinzufuegen(b["id"], z.KATEGORIE, -153.80, "Wäscherei (Rena)")
    for i, tag in enumerate(("2026-02-02", "2026-03-02", "2026-04-01")):
        _bewegung(-153.80, "TARGOBANK AG", f"w{i + 1}", datum=tag)
    v = konto.vorschau_gelernt()
    assert len(v) == 3
    assert konto.gelerntes_anwenden(v) == 3
    assert konto.ohne_zuordnung() == []


# ---- Der tote Klick (8.8.2026 an Smoobu gemeldet)
# Am Bestand: 63 Bewegungen trugen eine Kategorie aus der automatischen
# Erkennung (`herkunft='kreditor'`), aber keinen Posten. Die Auswahl in der
# Zeile erschien trotzdem – und der Klick prallte an der Schutzregel ab, die
# nur fuers Mitziehen gedacht war. Es passierte NICHTS.
def test_eine_erkannte_bewegung_laesst_sich_trotzdem_zuordnen():
    _bewegung(-73.78, "Smoobu GmbH", "w1", kategorie="Software (Smoobu Channelmanager)")
    satz, _weitere = konto.schnell_zuordnen("w1", "Software (Smoobu Channelmanager)")
    assert satz is not None
    assert len(z.posten("w1")) == 1
    assert z.ist_fertig(konto.holen("w1"))


def test_und_laesst_sich_dabei_auch_umkategorisieren():
    """Wer klickt, entscheidet – auch gegen die Erkennung."""
    _bewegung(-73.78, "Smoobu GmbH", "w1", kategorie="Wäscherei (Rena)")
    konto.schnell_zuordnen("w1", "Software (Smoobu Channelmanager)")
    assert konto.holen("w1")["kategorie"] == "Software (Smoobu Channelmanager)"
    assert z.posten("w1")[0]["kategorie"] == "Software (Smoobu Channelmanager)"


def test_mitgezogen_wird_weiterhin_nur_was_noch_nichts_traegt():
    """Beim Mitziehen bleibt die Regel streng: was schon eine Kategorie hat,
    wurde entweder erkannt oder von Hand gesetzt – beides nicht ueberschreiben."""
    _bewegung(-73.78, "Smoobu GmbH", "w1")
    _bewegung(-73.78, "Smoobu GmbH", "w2", datum="2026-03-02",
              kategorie="Wäscherei (Rena)")
    _bewegung(-73.78, "Smoobu GmbH", "w3", datum="2026-04-28")
    _satz, weitere = konto.schnell_zuordnen("w1", "Software (Smoobu Channelmanager)")
    assert weitere == ["w3"]
    assert konto.holen("w2")["kategorie"] == "Wäscherei (Rena)"


def test_eine_erkannte_bewegung_gilt_als_erledigt():
    """Sie zaehlt in der Auswertung mit – also gehoert der Haken an die Zeile.
    Vorher hing er an `ist_fertig`, das Posten verlangt; die Zeile sah aus wie
    unbearbeitet."""
    _bewegung(-73.78, "Smoobu GmbH", "w1", kategorie="Software (Smoobu Channelmanager)")
    assert konto.ist_erledigt(konto.holen("w1")) is True


def test_ohne_kategorie_und_ohne_posten_ist_nichts_erledigt():
    _bewegung(-73.78, "Smoobu GmbH", "w1")
    assert konto.ist_erledigt(konto.holen("w1")) is False


def test_eine_halbe_aufteilung_gilt_nicht_als_erledigt():
    b = _bewegung(-100.0, "Baumarkt", "w1")
    z.hinzufuegen(b["id"], z.KATEGORIE, -60.0, "Wäscherei (Rena)")
    assert konto.ist_erledigt(konto.holen("w1")) is False


def test_eine_umbuchung_ist_immer_erledigt():
    from app import db
    db.anlegen(konto.TABELLE, {"id": "u1", "datum": "2026-06-12", "betrag": -500.0,
                               "gegenpartei": "Kreditkarte", "text": "",
                               "konto": "giro", "umbuchung": True, "kategorie": ""})
    assert konto.ist_erledigt(konto.holen("u1")) is True


def test_die_zeile_zeigt_die_gesetzte_kategorie():
    """Vorher stand dort immer „— zuordnen —" – auch an einer Bewegung, die
    laengst eine erkannte Kategorie trug."""
    from nicegui import ui
    from nicegui.client import Client
    from app.ui import kontoblatt
    b = _bewegung(-73.78, "Smoobu GmbH", "w1",
                  kategorie="Software (Smoobu Channelmanager)")
    with Client(lambda: None):
        with ui.card() as karte:
            kontoblatt._kategorie_wahl(b, lambda: None)
    feld = karte.default_slot.children[0]
    assert feld.value == "Software (Smoobu Channelmanager)"
